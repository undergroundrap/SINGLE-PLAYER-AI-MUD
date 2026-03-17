from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from app.models.schemas import Player, Zone, Mob, Item, Location, Quest, DungeonRun
from app.core.world_generator import world_gen, _roll_loot
from app.core.scaling_math import ScalingMath, RARITY, CLASS_STATS
from app.core.vector_db import vec_db
from app.core.combat_engine import combat_engine
from app.core.simulation import sim_engine
from app.core.dungeon_engine import generate_run, resolve_round, calculate_gear_score, RAID_GEAR_MIN
import uuid
import asyncio
import random
import time
import math

# ──────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────

ATTACK_COOLDOWN      = 1.5    # seconds between attacks per player
GATHER_COOLDOWN      = 8.0    # seconds between gather actions
POTION_HEAL_COOLDOWN = 60.0   # shared healing potion cooldown
POTION_XP_COOLDOWN   = 300.0  # elixir of insight cooldown (5 min)
BAG_SIZE             = 16     # maximum inventory slots (matches UI grid)

_attack_times:     dict[str, float] = {}  # player_id -> last attack timestamp
_gather_times:     dict[str, float] = {}  # player_id -> last gather timestamp
_potion_cooldowns: dict[str, float] = {}  # "{player_id}:heal" | "{player_id}:xp" -> last use time
_active_xp_buffs:  dict[str, dict]  = {}  # player_id -> {"bonus_pct": int, "charges": int}
_dungeon_runs:     dict[str, DungeonRun] = {}  # run_id -> DungeonRun (ephemeral)


# ── Class passive proc table ───────────────────────────────────────────────
# Each class has a chance-per-attack to trigger a unique passive effect.
# "damage" = bonus damage to mob | "heal" = restore HP | "drain" = damage + lifesteal
# "dodge"  = skip mob counter-attack entirely this tick
# Druid: heal (REJUVENATION) — 25 % chance, restores 15 % max HP. Differentiates from
#   Rogue (dodge) which previously made Druid a strictly-dominated choice. Druid is now
#   the self-sustaining generalist (1.0× HP/dmg, frequent self-heals).
_CLASS_PROCS: dict[str, dict] = {
    "Warrior":  {"chance": 0.20, "type": "damage", "mult": 2.0,  "label": "⚔ BATTLE FURY"},
    "Paladin":  {"chance": 0.20, "type": "heal",   "mult": 0.15, "label": "✦ DIVINE GRACE"},
    "Hunter":   {"chance": 0.20, "type": "damage", "mult": 2.5,  "label": "⚡ POWER SHOT"},
    "Rogue":    {"chance": 0.25, "type": "dodge",  "mult": 0,    "label": "☽ EVASION"},
    "Priest":   {"chance": 0.25, "type": "heal",   "mult": 0.20, "label": "✦ HOLY MEND"},
    "Shaman":   {"chance": 0.20, "type": "damage", "mult": 1.8,  "label": "⚡ CHAIN LIGHTNING"},
    "Mage":     {"chance": 0.25, "type": "damage", "mult": 1.8,  "label": "✦ ARCANE SURGE"},
    "Warlock":  {"chance": 0.20, "type": "drain",  "mult": 1.5,  "label": "✧ SOUL DRAIN"},
    "Druid":    {"chance": 0.25, "type": "heal",   "mult": 0.15, "label": "✦ REJUVENATION"},
}

def _apply_class_proc(player: "Player", target_mob: "Mob", messages: list) -> bool:
    """Roll the player's class passive proc. Returns True if mob counter-attack should be skipped."""
    proc = _CLASS_PROCS.get(player.char_class)
    if not proc or random.random() > proc["chance"]:
        return False
    ptype, mult, label = proc["type"], proc["mult"], proc["label"]
    # Use effective max hit so proc damage scales with weapon upgrades, same as normal attacks
    effective_max = combat_engine.get_effective_max_hit(player)
    if ptype == "damage":
        bonus = max(1, int(effective_max * mult))
        target_mob.hp = max(0, target_mob.hp - bonus)
        messages.append(f"  ★ {label}! +{bonus} bonus damage!")
    elif ptype == "heal":
        heal = max(1, int(player.max_hp * mult))
        player.hp = min(player.max_hp, player.hp + heal)
        messages.append(f"  ★ {label}! Restored {heal} HP!")
    elif ptype == "drain":
        bonus = max(1, int(effective_max * mult))
        heal  = bonus // 2
        target_mob.hp = max(0, target_mob.hp - bonus)
        player.hp = min(player.max_hp, player.hp + heal)
        messages.append(f"  ★ {label}! Drained {bonus} life! (+{heal} HP)")
    elif ptype == "dodge":
        messages.append(f"  ★ {label}! Counter-attack evaded!")
        return True
    return False


def _consider(mob_level: int, player_level: int) -> str:
    """EverQuest-style danger assessment."""
    diff = mob_level - player_level
    if diff >= 6:  return "☠ CERTAIN DEATH — do not engage."
    if diff >= 4:  return "⚠ Very dangerous — death is likely."
    if diff >= 2:  return "⚡ Challenging — you may struggle."
    if diff == 1:  return "• Slightly above your level."
    if diff == 0:  return "• An even match."
    if diff >= -3: return "◦ Weaker than you — easy fight."
    return "· Trivial — barely worth your time."

app = FastAPI(title="AI MUD API")

@app.on_event("startup")
async def startup_event():
    await sim_engine.start()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _apply_levelups(player: Player, messages: list) -> bool:
    """Loop level-ups until XP is below threshold. Returns True if leveled."""
    leveled = False
    hp_mult, dmg_mult = CLASS_STATS.get(player.char_class, (1.0, 1.0))
    while player.xp >= player.next_level_xp:
        player.xp -= player.next_level_xp
        player.level += 1
        player.next_level_xp = ScalingMath.get_xp_required(player.level)
        player.max_hp = int(ScalingMath.get_max_hp(player.level) * hp_mult)
        player.hp = player.max_hp
        player.damage = int(ScalingMath.get_damage(player.level) * dmg_mult)
        leveled = True
        messages.append(f"⬆ LEVEL UP! You are now level {player.level}!")
    return leveled


# ──────────────────────────────────────────────
# PLAYER
# ──────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "AI MUD Backend Running"}


@app.get("/players")
async def list_players():
    """Return summary cards for all saved characters — used by the load-game screen."""
    try:
        rows = vec_db.get_all_players()
        summaries = []
        for raw in rows:
            summaries.append({
                "player_id":           raw.get("id", ""),
                "name":                raw.get("name", "Unknown"),
                "level":               raw.get("level", 1),
                "race":                raw.get("race", ""),
                "char_class":          raw.get("char_class", ""),
                "pronouns":            raw.get("pronouns", "They/Them"),
                "hp":                  raw.get("hp", 0),
                "max_hp":              raw.get("max_hp", 0),
                "gold":                raw.get("gold", 0),
                "kills":               raw.get("kills", 0),
                "deaths":              raw.get("deaths", 0),
                "current_zone_id":     raw.get("current_zone_id", ""),
                "completed_quest_ids": len(raw.get("completed_quest_ids") or []),
            })
        summaries.sort(key=lambda p: (p["level"], p["kills"]), reverse=True)
        return {"players": summaries}
    except Exception as e:
        return {"players": [], "error": str(e)}


@app.get("/player/{player_id}")
async def load_player(player_id: str):
    """Load a specific player + their current zone for the load-game screen."""
    p_data = await vec_db.get_player(player_id)
    if not p_data:
        raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    z_data = await vec_db.get_zone(player.current_zone_id)
    if not z_data:
        raise HTTPException(status_code=404, detail="Zone not found — data may be corrupt")

    return {"player_id": player_id, "player": player, "zone": z_data,
            "gear_score": calculate_gear_score(player)}


@app.delete("/player/{player_id}")
async def delete_player(player_id: str):
    """Delete a single character and all zones they own. Irreversible."""
    result = await vec_db.delete_player(player_id)
    if not result.get("deleted"):
        raise HTTPException(status_code=404, detail=result.get("error", "Player not found"))
    _attack_times.pop(player_id, None)
    return {
        "success": True,
        "message": "Character deleted.",
        "zones_removed": result.get("zones_removed", 0),
    }


@app.post("/player/create")
async def create_player(name: str, race: str, char_class: str, pronouns: str = "They/Them"):
    player_id = str(uuid.uuid4())
    initial_zone = await world_gen.generate_zone(level=1)

    hp_mult, dmg_mult = CLASS_STATS.get(char_class, (1.0, 1.0))
    base_hp  = int(ScalingMath.get_max_hp(1)  * hp_mult)
    base_dmg = int(ScalingMath.get_damage(1)  * dmg_mult)

    hub_id = initial_zone.locations[0].id if initial_zone.locations else None
    player = Player(
        name=name,
        level=1,
        hp=base_hp,
        max_hp=base_hp,
        damage=base_dmg,
        xp=0,
        next_level_xp=ScalingMath.get_xp_required(1),
        race=race,
        char_class=char_class,
        pronouns=pronouns,
        current_zone_id=initial_zone.id,
        current_location_id=hub_id,
        explored_location_ids=[hub_id] if hub_id else [],
        visited_zone_ids=[initial_zone.id],
    )

    await vec_db.save_zone(initial_zone.id, initial_zone.model_dump(mode='json'))
    await vec_db.save_player(player_id, player.model_dump(mode='json'))

    return {"player_id": player_id, "player": player, "zone": initial_zone}


# ──────────────────────────────────────────────
# NARRATIVE
# ──────────────────────────────────────────────

@app.get("/narrative/stream/{player_id}")
async def stream_narrative(player_id: str, action: str):
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    z_data = await vec_db.get_zone(player.current_zone_id)
    zone = Zone(**z_data)
    loc = next((l for l in zone.locations if l.id == player.current_location_id), None)

    prompt = (
        f"Player {player.name} ({player.race} {player.char_class}) just performed: {action}. "
        f"Describe the immediate outcome in 1-2 sentences. "
        f"Location: {loc.name if loc else 'Unknown'}. "
        "Include a 'HINT:' at the end suggesting a gameplay command."
    )

    from app.core.ai_client import ai_client
    return StreamingResponse(ai_client.stream_content(prompt), media_type="text/event-stream")


# ──────────────────────────────────────────────
# QUESTS
# ──────────────────────────────────────────────

@app.post("/quests/accept/{player_id}")
async def accept_quest(player_id: str, quest_id: str):
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")

    player = Player(**p_data)
    z_data = await vec_db.get_zone(player.current_zone_id)
    zone = Zone(**z_data)

    quest = next((q for q in zone.quests if q.id == quest_id), None)
    if not quest: raise HTTPException(status_code=404, detail="Quest not found in zone")

    if any(q.id == quest_id for q in player.active_quests):
        return {"message": "Quest already active"}

    player.active_quests.append(quest)
    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {"message": f"Quest '{quest.title}' accepted", "quest": quest}


@app.post("/quests/progress/{player_id}")
async def update_quest_progress(player_id: str, quest_id: str, progress: int):
    """Sync frontend kill/gather progress to the DB."""
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")

    player = Player(**p_data)
    for q in player.active_quests:
        if q.id == quest_id:
            q.current_progress = min(q.target_count, progress)
            if q.current_progress >= q.target_count:
                q.is_completed = True
            break

    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {"success": True}


@app.post("/quests/complete/{player_id}")
async def complete_quest(player_id: str, quest_id: str):
    """Turn in a completed quest at the hub NPC, grant rewards."""
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")

    player = Player(**p_data)
    quest = next((q for q in player.active_quests if q.id == quest_id and q.is_completed), None)
    if not quest:
        raise HTTPException(status_code=400, detail="Quest not found or not yet completed")

    messages = [f"Quest Complete: {quest.title}!", f"Reward: {quest.xp_reward} XP"]
    player.xp += quest.xp_reward

    item_reward = None
    item_placement = None  # "inventory" | "equipped" | "dropped" | None
    equipped_slot  = None
    if quest.item_reward:
        item_reward = Item(**quest.item_reward) if isinstance(quest.item_reward, dict) else quest.item_reward
        if len(player.inventory) < BAG_SIZE:
            player.inventory.append(item_reward)
            item_placement = "inventory"
            messages.append(f"Item Reward: {item_reward.name}")
        else:
            # Bags full — auto-equip if it's an upgrade, otherwise warn
            current = player.equipment.get(item_reward.slot) if item_reward.slot else None
            curr_sum = sum(current.stats.values()) if current and current.stats else 0
            new_sum = sum(item_reward.stats.values()) if item_reward.stats else 0
            if item_reward.slot and new_sum > curr_sum:
                player.equipment[item_reward.slot] = item_reward
                item_placement = "equipped"
                equipped_slot  = item_reward.slot
                messages.append(f"Item Reward: {item_reward.name} (auto-equipped — bags were full)")
            else:
                item_placement = "dropped"
                messages.append(f"⚠ Bags full — [{item_reward.name}] left on the ground! Sell junk first.")

    leveled = _apply_levelups(player, messages)

    player.active_quests = [q for q in player.active_quests if q.id != quest_id]
    player.completed_quest_ids.append(quest_id)

    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {
        "success":        True,
        "messages":       messages,
        "xp_reward":      quest.xp_reward,
        "leveled_up":     leveled,
        "new_level":      player.level,
        "new_xp":         player.xp,
        "new_next_level_xp": player.next_level_xp,
        "new_max_hp":     player.max_hp,
        "item_reward":    item_reward.model_dump(mode='json') if item_reward else None,
        "item_placement": item_placement,   # frontend uses this to update state correctly
        "equipped_slot":  equipped_slot,
        "gear_score":     calculate_gear_score(player) if (leveled or item_placement == "equipped") else None,
    }


# ──────────────────────────────────────────────
# MOVEMENT
# ──────────────────────────────────────────────

@app.post("/action/move/{player_id}")
async def move_player(player_id: str, location_id: str):
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")

    player = Player(**p_data)
    player.current_location_id = location_id

    # Track explored locations
    if location_id not in player.explored_location_ids:
        player.explored_location_ids = player.explored_location_ids + [location_id]

    # Auto-complete explore quests targeting this location
    explore_completed = []
    for q in player.active_quests:
        if q.quest_type == "explore" and q.target_id == location_id and not q.is_completed:
            q.current_progress = 1
            q.is_completed = True
            explore_completed.append({"id": q.id, "title": q.title, "xp_reward": q.xp_reward})

    # Reset alive mobs at the destination to full HP.
    # Mobs that were partially damaged before the player left now recover, matching
    # standard MMO out-of-combat regen. Dead mobs (respawn_at set) are untouched.
    z_data = await vec_db.get_zone(player.current_zone_id)
    zone_changed = False
    if z_data:
        zone = Zone(**z_data)
        dest_loc = next((l for l in zone.locations if l.id == location_id), None)
        if dest_loc:
            for m in dest_loc.mobs:
                if m.respawn_at is None and m.hp < m.max_hp:
                    m.hp = m.max_hp
                    zone_changed = True
        if zone_changed:
            await vec_db.save_zone(zone.id, zone.model_dump(mode='json'))

    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    sim_engine.mark_player_zone(player.current_zone_id)
    return {"success": True, "location_id": location_id, "explore_completed": explore_completed}


@app.get("/zone/{zone_id}")
async def get_zone(zone_id: str):
    z_data = await vec_db.get_zone(zone_id)
    if not z_data: raise HTTPException(status_code=404, detail="Zone not found")
    return z_data


@app.post("/zone/travel/{player_id}")
async def travel_to_zone(player_id: str, is_dungeon: bool = False, is_raid: bool = False):
    """Generate and travel to a new zone scaled to the player's level."""
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")

    player = Player(**p_data)

    # Raids require at least level 20; dungeons at least level 10
    if is_raid and player.level < 20:
        raise HTTPException(status_code=400, detail="You need level 20+ to enter a raid.")
    if is_dungeon and player.level < 10:
        raise HTTPException(status_code=400, detail="You need level 10+ to enter a dungeon.")

    # Zone travel gate — must complete at least 2 quests from the current zone first
    if not is_dungeon and not is_raid:
        current_zone_id = player.current_zone_id
        zone_quests_done = sum(1 for qid in player.completed_quest_ids if qid.endswith(current_zone_id))
        if zone_quests_done < 2:
            raise HTTPException(
                status_code=400,
                detail=f"Complete at least 2 quests before moving on. ({zone_quests_done}/2 done)"
            )

    # Each completed raid pushes open-world zones 3 levels harder — infinite tier progression
    zone_level = player.level + (player.raids_cleared * 3)
    new_zone = await world_gen.generate_zone(level=zone_level, is_dungeon=is_dungeon, is_raid=is_raid)
    await vec_db.save_zone(new_zone.id, new_zone.model_dump(mode='json'))

    if not new_zone.locations:
        raise HTTPException(status_code=500, detail="Zone generation failed — no locations created.")
    player.current_zone_id = new_zone.id
    player.current_location_id = new_zone.locations[0].id
    if new_zone.id not in player.visited_zone_ids:
        player.visited_zone_ids = player.visited_zone_ids + [new_zone.id]

    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {"success": True, "zone": new_zone}


# ──────────────────────────────────────────────
# COMBAT
# ──────────────────────────────────────────────

@app.post("/action/attack/{player_id}")
async def attack(player_id: str, mob_name: str):
    # ── Rate limit ─────────────────────────────
    now = time.time()
    last = _attack_times.get(player_id, 0)
    if now - last < ATTACK_COOLDOWN:
        wait = round(ATTACK_COOLDOWN - (now - last), 2)
        return {"success": False, "message": f"Not ready. ({wait}s remaining)", "on_cooldown": True}
    _attack_times[player_id] = now

    # ── Load state ─────────────────────────────
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    z_data = await vec_db.get_zone(player.current_zone_id)
    zone = Zone(**z_data)
    loc = next((l for l in zone.locations if l.id == player.current_location_id), None)

    # ── Restore respawned mobs to full HP ──────
    # respawn_at is never cleared — once the timer fires the mob is "alive"
    # but still has hp=0 from when it died. Reset here before any targeting.
    for m in (loc.mobs if loc else []):
        if m.respawn_at is not None and now >= m.respawn_at:
            m.hp = m.max_hp
            m.respawn_at = None

    # ── Find a living mob ──────────────────────
    # Prefer exact name match so "attack Boar" never accidentally targets
    # "Veteran Boar". Fall back to substring only if no exact match exists.
    living = [m for m in (loc.mobs if loc else []) if m.respawn_at is None]
    target_mob = (
        next((m for m in living if m.name.lower() == mob_name.lower()), None)
        or next((m for m in living if mob_name.lower() in m.name.lower()), None)
    )
    if not target_mob:
        dead_mob = next(
            (m for m in (loc.mobs if loc else [])
             if mob_name.lower() in m.name.lower() and m.respawn_at and now < m.respawn_at),
            None
        )
        if dead_mob:
            remaining = int(dead_mob.respawn_at - now)
            return {"success": False, "message": f"The {mob_name} is dead. Respawns in {remaining}s."}
        return {"success": False, "message": f"There is no {mob_name} here."}

    messages = []
    consider_text = _consider(target_mob.level, player.level)

    # ── Combat resolution ──────────────────────
    atk_msgs, target_dead = combat_engine.resolve_tick(player, target_mob)
    messages.extend(atk_msgs)

    # Class passive proc — fires between player attack and mob counter-attack
    skip_counter = False
    if not target_dead:
        skip_counter = _apply_class_proc(player, target_mob, messages)
        target_dead = target_mob.hp <= 0  # re-check in case proc finished the mob

    player_dead = False
    if not target_dead and not skip_counter:
        ctr_msgs, player_dead = combat_engine.resolve_tick(target_mob, player)
        messages.extend(ctr_msgs)

    xp_gained    = 0
    gold_gained  = 0
    rested_bonus = 0
    loot_item    = None
    auto_equipped = False
    displaced_item = None
    leveled_up   = False
    respawn_location_id = None

    if target_dead:
        # XP: elites give 2×, named give 4×
        xp_base  = ScalingMath.get_xp_required(target_mob.level) // 8
        xp_mult  = 4 if target_mob.is_named else (2 if target_mob.is_elite else 1)
        xp_gained = xp_base * xp_mult

        # Apply rested XP bonus (2× while pool lasts)
        if player.rested_xp > 0:
            rested_bonus = min(xp_gained, player.rested_xp)
            xp_gained   += rested_bonus
            player.rested_xp -= rested_bonus

        # Apply active Elixir of Insight buff if present
        xp_buff = _active_xp_buffs.get(player_id)
        if xp_buff:
            bonus = int(xp_gained * xp_buff["bonus_pct"] / 100)
            xp_gained += bonus
            xp_buff["charges"] -= 1
            if xp_buff["charges"] <= 0:
                del _active_xp_buffs[player_id]
                messages.append(f"✨ Elixir of Insight: +{bonus} XP! (faded)")
            else:
                messages.append(f"✨ Elixir of Insight: +{bonus} XP! ({xp_buff['charges']} kills left)")

        player.xp    += xp_gained
        player.kills += 1

        leveled_up = _apply_levelups(player, messages)

        # Gold drop (1–5 per level, elites 3×)
        gold_gained = random.randint(1, max(1, target_mob.level)) * (3 if target_mob.is_elite or target_mob.is_named else 1)
        player.gold += gold_gained

        # Mark mob dead with respawn timer
        respawn_delay = (60 if target_mob.is_named else 45 if target_mob.is_elite else 30) + target_mob.level * 2
        for zloc in zone.locations:
            for mob in zloc.mobs:
                if mob.id == target_mob.id:
                    mob.hp = 0
                    mob.respawn_at = now + respawn_delay
                    break

        # Roll loot + auto-itemization (class-biased, zone-tier boosted)
        zone_tier = "raid" if zone.is_raid else "dungeon" if zone.is_dungeon else "open"
        loot_item = _roll_loot(target_mob.level, target_mob.loot_table, player.char_class, zone_tier)
        if loot_item and loot_item.slot:
            current = player.equipment.get(loot_item.slot)
            current_sum = sum(current.stats.values()) if current and current.stats else 0
            new_sum = sum(loot_item.stats.values())
            bag_space = len(player.inventory) < BAG_SIZE
            if new_sum > current_sum:
                # Auto-equip the upgrade; displaced item only goes to bag if space exists
                has_displaced = current and current.name != "None"
                if has_displaced and bag_space:
                    displaced_item = current
                    player.inventory.append(current)
                elif has_displaced:
                    messages.append(f"⚠ Bags full — [{current.name}] left on the ground!")
                player.equipment[loot_item.slot] = loot_item
                auto_equipped = True
                stat_key = next(iter(loot_item.stats), "stat")
                old_label = f"+{current_sum} {stat_key}" if current_sum else "empty slot"
                messages.append(
                    f"⬆ Auto-equipped [{loot_item.name}] (+{new_sum} {stat_key})"
                    f" — replaces {displaced_item.name if displaced_item else 'empty slot'} ({old_label})"
                )
            elif bag_space:
                player.inventory.append(loot_item)
                stat_key = next(iter(loot_item.stats), "stat")
                cmp = f" (equipped: +{current_sum} {stat_key})" if current_sum else ""
                messages.append(f"🎒 [{loot_item.name}] +{new_sum} {stat_key} ({loot_item.rarity}){cmp}")
            else:
                messages.append(f"⚠ Bags full — [{loot_item.name}] left on the ground!")
        elif loot_item:
            if len(player.inventory) < BAG_SIZE:
                player.inventory.append(loot_item)
                messages.append(f"🎒 [{loot_item.name}] ({loot_item.rarity}) added to bag")
            else:
                messages.append(f"⚠ Bags full — [{loot_item.name}] left on the ground!")

        # Named kill or Epic+ drop — flag for special frontend treatment
        if target_mob.is_named or (loot_item and loot_item.rarity in ("Epic", "Legendary")):
            messages.append(f"★★★ RARE DROP: [{loot_item.name if loot_item else 'nothing'}] from {target_mob.name}! ★★★")

        if gold_gained:
            messages.append(f"+{gold_gained} gold")

    else:
        # ── KEY FIX: persist mob's current HP even when it survives ──
        for zloc in zone.locations:
            for mob in zloc.mobs:
                if mob.id == target_mob.id:
                    mob.hp = target_mob.hp
                    break

    # Always save zone so HP damage persists between attack requests
    await vec_db.save_zone(zone.id, zone.model_dump(mode='json'))
    sim_engine.mark_player_zone(zone.id)

    if player_dead:
        player.deaths += 1
        # Death penalty: lose 15 % of XP accumulated toward the current level
        xp_penalty = int(player.xp * 0.15)
        player.xp = max(0, player.xp - xp_penalty)
        player.hp = max(1, player.max_hp // 2)
        if zone.locations:
            player.current_location_id = zone.locations[0].id
            respawn_location_id = zone.locations[0].id
        penalty_msg = f" Lost {xp_penalty:,} XP." if xp_penalty else ""
        messages.append(f"☠ You have been defeated!{penalty_msg} You wake at the settlement.")

    await vec_db.save_player(player_id, player.model_dump(mode='json'))

    return {
        "success":             True,
        "messages":            messages,
        "consider":            consider_text,
        "player_hp":           player.hp,
        "player_max_hp":       player.max_hp,
        "player_xp":           player.xp,
        "player_dead":         player_dead,
        "respawn_location_id": respawn_location_id,
        "mob_hp":              target_mob.hp,
        "mob_respawn_at":      target_mob.respawn_at,
        "target_name":         target_mob.name,
        "target_max_hp":       target_mob.max_hp,
        "target_level":        target_mob.level,
        "target_dead":         target_dead,
        "target_is_elite":     target_mob.is_elite,
        "target_is_named":     target_mob.is_named,
        "xp_gained":           xp_gained,
        "rested_bonus":        rested_bonus,
        "rested_xp":           player.rested_xp,
        "gold_gained":         gold_gained,
        "loot_item":           loot_item.model_dump(mode='json') if loot_item else None,
        "auto_equipped":        auto_equipped,
        "displaced_item":       displaced_item.model_dump(mode='json') if displaced_item else None,
        "leveled_up":           leveled_up,
        "player_level":         player.level,
        "player_max_hp":        player.max_hp,
        "player_damage":        player.damage,
        "player_next_level_xp": player.next_level_xp,
        "player_gold":          player.gold,
        "player_kills":         player.kills,
        # Return gear score whenever equipment or level changes so UI stays in sync
        "gear_score":           calculate_gear_score(player) if (leveled_up or auto_equipped) else None,
        # Consumable state — frontend uses these to keep buff/cooldown display in sync
        "active_xp_buff":       _active_xp_buffs.get(player_id),
        "heal_cd":              max(0, int(POTION_HEAL_COOLDOWN - (now - _potion_cooldowns.get(f"{player_id}:heal", 0)))),
        "xp_cd":                max(0, int(POTION_XP_COOLDOWN   - (now - _potion_cooldowns.get(f"{player_id}:xp",   0)))),
    }


# ──────────────────────────────────────────────
# GATHER (forage quests)
# ──────────────────────────────────────────────

@app.post("/action/gather/{player_id}")
async def gather(player_id: str):
    p_data = await vec_db.get_player(player_id)
    if not p_data:
        raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    # Find active forage quests targeting the player's current location
    forage_quests = [
        q for q in player.active_quests
        if q.quest_type == "forage"
        and q.target_id == player.current_location_id
        and not q.is_completed
    ]
    if not forage_quests:
        # Check if a forage quest is done but not yet turned in
        done_forage = next((q for q in player.active_quests if q.quest_type == "forage" and q.is_completed), None)
        if done_forage:
            return {"success": False, "message": f'"{done_forage.title}" is complete — return to the quest giver to turn it in.'}
        # Give a helpful hint pointing to the right location
        all_forage = [q for q in player.active_quests if q.quest_type == "forage" and not q.is_completed]
        if all_forage:
            z_data = await vec_db.get_zone(player.current_zone_id)
            if z_data:
                zone = Zone(**z_data)
                q0 = all_forage[0]
                target_loc = next((l for l in zone.locations if l.id == q0.target_id), None)
                if target_loc:
                    return {"success": False, "message": f"Nothing to forage here. Travel to {target_loc.name} to gather {q0.collect_name or 'resources'}."}
        return {"success": False, "message": "No active forage quest. Talk to a quest giver for a gathering assignment."}

    # Apply cooldown only when there's actually something to gather
    now = time.time()
    last = _gather_times.get(player_id, 0)
    if now - last < GATHER_COOLDOWN:
        wait = round(GATHER_COOLDOWN - (now - last), 2)
        return {"success": False, "message": f"You search carefully... ({wait}s remaining)", "on_cooldown": True}
    _gather_times[player_id] = now

    messages = []
    quest_updates = []
    for q in forage_quests:
        q.current_progress = min(q.target_count, q.current_progress + 1)
        resource = q.collect_name or "resource"
        messages.append(f"You gather {resource}. ({q.current_progress}/{q.target_count})")
        if q.current_progress >= q.target_count:
            q.is_completed = True
            messages.append(f"✓ Quest complete: {q.title}!")
        quest_updates.append({"id": q.id, "progress": q.current_progress, "completed": q.is_completed})

    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {"success": True, "messages": messages, "quest_updates": quest_updates}


# ──────────────────────────────────────────────
# PATROL ENCOUNTERS
# ──────────────────────────────────────────────

@app.post("/action/patrol_check/{player_id}")
async def patrol_check(player_id: str):
    p_data = await vec_db.get_player(player_id)
    if not p_data:
        return {"patrol": False}
    player = Player(**p_data)

    z_data = await vec_db.get_zone(player.current_zone_id)
    if not z_data:
        return {"patrol": False}
    zone = Zone(**z_data)
    loc = next((l for l in zone.locations if l.id == player.current_location_id), None)
    if not loc:
        return {"patrol": False}

    # No patrol in hub (safe zone with NPCs) or while mobs are already alive here
    living = [m for m in loc.mobs if m.respawn_at is None and m.hp > 0]
    if living or loc.npcs:
        return {"patrol": False}

    # 25% chance per check
    if random.random() > 0.25:
        return {"patrol": False}

    # Pick a mob type already present in the zone for thematic consistency
    zone_mob_names = list({
        m.name for l in zone.locations for m in l.mobs
        if not m.is_named and not m.is_elite
    })
    if not zone_mob_names:
        return {"patrol": False}

    mob_name = random.choice(zone_mob_names)
    lvl = max(1, player.level + random.randint(-1, 1))
    patrol_mob = Mob(
        id=f"patrol_{player_id}_{int(time.time())}",
        name=mob_name,
        level=lvl,
        hp=ScalingMath.get_max_hp(lvl),
        max_hp=ScalingMath.get_max_hp(lvl),
        damage=ScalingMath.get_damage(lvl),
        description=f"A {mob_name.lower()} that wandered into the area.",
        loot_table=[],
    )
    loc.mobs.append(patrol_mob)
    await vec_db.save_zone(zone.id, zone.model_dump(mode='json'))

    return {"patrol": True, "mob_name": mob_name, "mob_level": lvl, "zone_id": zone.id}


# ──────────────────────────────────────────────
# INVENTORY / EQUIPMENT
# ──────────────────────────────────────────────

@app.post("/action/equip/{player_id}")
async def equip_item(player_id: str, item_id: str):
    """Move an item from inventory to the appropriate equipment slot."""
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")

    player = Player(**p_data)
    item = next((i for i in player.inventory if i.id == item_id), None)
    if not item: raise HTTPException(status_code=404, detail="Item not in inventory")
    if not item.slot: raise HTTPException(status_code=400, detail="Item has no equip slot")

    # Swap: put current equipped item back into inventory (if it has a real name)
    current = player.equipment.get(item.slot)
    inv_without_item = [i for i in player.inventory if i.id != item_id]
    has_displaced = current and current.name != "None"
    if has_displaced and len(inv_without_item) >= BAG_SIZE:
        raise HTTPException(status_code=400, detail=f"Bags full — unequip or sell something to make room for [{current.name}].")
    if has_displaced:
        inv_without_item.append(current)

    player.equipment[item.slot] = item
    player.inventory = inv_without_item

    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {"success": True, "equipped": item.model_dump(mode='json'), "slot": item.slot,
            "gear_score": calculate_gear_score(player)}


@app.post("/action/unequip/{player_id}")
async def unequip_item(player_id: str, slot: str):
    """Move an equipped item back to inventory, leaving the slot empty."""
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    item = player.equipment.get(slot)
    if not item or item.name == "None":
        raise HTTPException(status_code=400, detail=f"Nothing equipped in {slot}")
    if len(player.inventory) >= BAG_SIZE:
        raise HTTPException(status_code=400, detail=f"Bags full — sell something before unequipping [{item.name}].")

    player.inventory.append(item)
    # Reset slot to empty sentinel
    player.equipment[slot] = Item(id="", name="None", description="", level=0, rarity="Common", stats={}, slot=slot)

    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {"success": True, "unequipped": item.model_dump(mode='json'), "slot": slot,
            "gear_score": calculate_gear_score(player)}


@app.post("/action/use/{player_id}")
async def use_item(player_id: str, item_id: str):
    """Use a consumable item from the player's inventory (potion, elixir, etc.)."""
    p_data = await vec_db.get_player(player_id)
    if not p_data:
        raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    item = next((i for i in player.inventory if i.id == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not in inventory")
    if item.slot != "consumable":
        raise HTTPException(status_code=400, detail="That item cannot be used")

    now = time.time()
    messages = []

    if "heal_pct" in item.stats:
        cd_key = f"{player_id}:heal"
        last   = _potion_cooldowns.get(cd_key, 0)
        if now - last < POTION_HEAL_COOLDOWN:
            wait = int(POTION_HEAL_COOLDOWN - (now - last))
            return {"success": False, "message": f"Healing potion on cooldown. ({wait}s remaining)",
                    "player_hp": player.hp, "player_max_hp": player.max_hp}
        heal = max(1, int(player.max_hp * item.stats["heal_pct"] / 100))
        player.hp = min(player.max_hp, player.hp + heal)
        _potion_cooldowns[cd_key] = now
        messages.append(f"🧪 {item.name}: Restored {heal} HP! ({player.hp}/{player.max_hp})")

    elif "xp_bonus_pct" in item.stats:
        cd_key  = f"{player_id}:xp"
        last    = _potion_cooldowns.get(cd_key, 0)
        if now - last < POTION_XP_COOLDOWN:
            wait = int(POTION_XP_COOLDOWN - (now - last))
            return {"success": False, "message": f"Elixir on cooldown. ({wait}s remaining)",
                    "player_hp": player.hp, "player_max_hp": player.max_hp}
        charges = item.stats.get("xp_charges", 5)
        pct     = item.stats["xp_bonus_pct"]
        _active_xp_buffs[player_id] = {"bonus_pct": pct, "charges": charges}
        _potion_cooldowns[cd_key] = now
        messages.append(f"✨ {item.name}: Next {charges} kills grant +{pct}% XP!")

    else:
        raise HTTPException(status_code=400, detail="Unknown consumable effect")

    player.inventory = [i for i in player.inventory if i.id != item_id]
    await vec_db.save_player(player_id, player.model_dump(mode='json'))

    heal_cd_remaining = max(0, int(POTION_HEAL_COOLDOWN - (now - _potion_cooldowns.get(f"{player_id}:heal", 0))))
    xp_cd_remaining   = max(0, int(POTION_XP_COOLDOWN   - (now - _potion_cooldowns.get(f"{player_id}:xp",   0))))
    return {
        "success":          True,
        "messages":         messages,
        "player_hp":        player.hp,
        "player_max_hp":    player.max_hp,
        "active_xp_buff":   _active_xp_buffs.get(player_id),
        "heal_cd":          heal_cd_remaining,
        "xp_cd":            xp_cd_remaining,
    }


@app.post("/action/rest/{player_id}")
async def rest_player(player_id: str, hp: int):
    """Persist out-of-combat HP regen from the client.
    Called by the frontend regen timer every ~10 seconds while the player is healing.
    Clamps HP to [1, max_hp] server-side so the client can never over-heal."""
    p_data = await vec_db.get_player(player_id)
    if not p_data:
        raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)
    player.hp = max(1, min(player.max_hp, hp))
    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {"success": True, "hp": player.hp, "max_hp": player.max_hp}


@app.post("/action/login/{player_id}")
async def player_login(player_id: str):
    """Called when the player loads their character.
    Computes rested XP accumulated since last logout: next_level_xp/8 per real hour,
    capped at 1.5× next_level_xp. Returns the current rested pool."""
    p_data = await vec_db.get_player(player_id)
    if not p_data:
        raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    dirty = False

    # Clear orphaned dungeon run if server restarted and run is gone from memory
    if player.active_dungeon_run_id and player.active_dungeon_run_id not in _dungeon_runs:
        player.active_dungeon_run_id = None
        dirty = True

    if player.last_logout_time > 0:
        hours_offline = (time.time() - player.last_logout_time) / 3600.0
        rest_rate     = player.next_level_xp / 8  # 1 full level's rest in 8 hours
        rest_gained   = int(hours_offline * rest_rate)
        cap           = int(player.next_level_xp * 1.5)
        player.rested_xp       = min(player.rested_xp + rest_gained, cap)
        player.last_logout_time = 0.0  # clear — they're online now
        dirty = True

    if dirty:
        await vec_db.save_player(player_id, player.model_dump(mode='json'))

    return {
        "rested_xp":     player.rested_xp,
        "rested_xp_cap": int(player.next_level_xp * 1.5),
    }


@app.post("/action/logout/{player_id}")
async def player_logout(player_id: str):
    """Stamps the logout time so rested XP can accumulate while offline."""
    p_data = await vec_db.get_player(player_id)
    if not p_data:
        raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)
    player.last_logout_time = time.time()
    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {"ok": True}


# ──────────────────────────────────────────────
# NPC DIALOGUE
# ──────────────────────────────────────────────

@app.post("/action/talk/{player_id}")
async def talk_to_npc(player_id: str, npc_name: str):
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    z_data = await vec_db.get_zone(player.current_zone_id)
    zone = Zone(**z_data)

    loc = next((l for l in zone.locations if l.id == player.current_location_id), None)
    npc = next((n for n in (loc.npcs if loc else []) if npc_name.lower() in n.name.lower()), None)

    if not npc:
        return {"message": f"There is no one named '{npc_name}' here.", "success": False}

    from app.core.ai_client import ai_client

    # Vendors get a special response showing their wares
    if npc.role == "vendor":
        items_preview = ", ".join(
            f"{i['name']} ({i['price']}g)" for i in npc.vendor_items[:5]
        ) if npc.vendor_items else "nothing in stock"
        return {
            "success": True,
            "npc_name": npc.name,
            "dialogue": f"{npc.name}: \"{npc.dialogue[0] if npc.dialogue else 'Welcome!'}\" — Today's wares: {items_preview}. Type 'shop' to browse.",
            "offered_quests": [],
            "is_vendor": True,
            "vendor_items": npc.vendor_items,
        }

    # Resolve the exact quests this NPC is offering
    offered_quests = [q for q in zone.quests if q.id in (npc.quests_offered or [])]
    not_yet_active = [
        q for q in offered_quests
        if not any(aq.id == q.id for aq in player.active_quests)
        and q.id not in player.completed_quest_ids
        # Don't re-offer explore quests for already-visited locations
        and not (q.quest_type == "explore" and q.target_id in player.explored_location_ids)
    ]

    # Build a tight quest brief so the NPC dialogue is directly about the actual objectives
    if not_yet_active:
        quest_lines = "\n".join(
            f'- "{q.title}": {q.objective} ({q.description})'
            for q in not_yet_active
        )
        quest_brief = (
            f"You have {len(not_yet_active)} quest(s) to offer:\n{quest_lines}\n"
            "Your dialogue MUST reference these exact quests by name. "
            "Tease the danger or urgency of the specific target (e.g. spiders, supply crates). "
        )
    else:
        # All quests already accepted — check for completions
        completed = [q for q in offered_quests if any(aq.id == q.id and aq.is_completed for aq in player.active_quests)]
        if completed:
            quest_brief = f"The player has completed: {', '.join(q.title for q in completed)}. Congratulate them briefly. "
        else:
            quest_brief = "All your quests are already in progress. Encourage the player to keep going. "

    system_prompt = (
        f"You are {npc.name}, a {npc.role} in a gritty high-fantasy world. "
        "Be direct, atmospheric, and in character. Never invent quests that don't exist."
    )
    prompt = (
        f"{quest_brief}"
        f"The player {player.name} (a {player.race} {player.char_class}, level {player.level}) approaches you. "
        "Respond in 1-2 sentences in character. "
        "End with exactly one 'HINT:' gameplay suggestion relevant to the quests (e.g. 'HINT: Type accept all')."
    )

    try:
        dialogue = await ai_client.generate_content(prompt, system_prompt, max_tokens=120)
    except Exception:
        # Contextual fallback — always reference the actual quests/state
        if not_yet_active:
            titles = " and ".join(f'"{q.title}"' for q in not_yet_active)
            targets = ", ".join(
                f"{q.target_count} {q.target_id}{'s' if q.target_count > 1 else ''}"
                for q in not_yet_active
            )
            dialogue = (
                f"Adventurer! I need your help with {titles}. "
                f"The task: {targets}. "
                f"HINT: Type 'accept all' to take on every quest."
            )
        else:
            completed_here = [q for q in offered_quests if any(aq.id == q.id and aq.is_completed for aq in player.active_quests)]
            if completed_here:
                cnames = " and ".join(f'"{q.title}"' for q in completed_here)
                dialogue = f"You've done it — {cnames} complete! Your rewards await. HINT: Type 'turn in' to claim them."
            else:
                in_prog = [q for q in offered_quests if any(aq.id == q.id for aq in player.active_quests)]
                if in_prog:
                    q = in_prog[0]
                    aq = next(aq for aq in player.active_quests if aq.id == q.id)
                    dialogue = f"Keep at it — {aq.current_progress}/{q.target_count} on '{q.title}'. Don't stop now."
                else:
                    dialogue = npc.dialogue[0] if npc.dialogue else "Speak quickly, adventurer. There is much to do."

    return {
        "success": True,
        "npc_name": npc.name,
        "dialogue": dialogue,
        "offered_quests": [q.model_dump(mode='json') for q in not_yet_active],
    }


# ──────────────────────────────────────────────
# WORLD CHAT
# ──────────────────────────────────────────────

@app.post("/narrative/summarize_chat")
async def summarize_chat(history: str, player_name: str, zone_name: str = ""):
    """Condense recent world chat into one sentence for long-term context."""
    from app.core.ai_client import ai_client
    zone_hint = f" in {zone_name}" if zone_name else ""
    prompt = (
        f"Summarize what {player_name} talked about in this in-game chat{zone_hint} in one plain sentence:\n"
        f"{history}"
    )
    system_prompt = "Summarize a game chat log in one sentence. Plain text only, no quotes, no preamble."
    try:
        summary = await ai_client.generate_content(prompt, system_prompt, max_tokens=60)
        return {"summary": summary.strip().strip('"\'') }
    except Exception:
        return {"summary": ""}

_CHAT_PERSONALITIES = [
    ("veteran",      "You've played MMOs forever. Dry, tired humor. Occasionally useful. Never hyped."),
    ("try-hard",     "You're grinding and focused. Slightly impatient. Talks about kills and progress."),
    ("reckless",     "You die a lot and find it funny. Self-deprecating, chaotic, always doing something dumb."),
    ("quiet",        "Few words, chill vibe. Responds briefly when spoken to. Never volunteers information."),
    ("complainer",   "Nothing is ever good enough. Talks normally but complains about the game — mobs, loot, zone, whatever."),
    ("helper",       "Laid back and helpful when it comes up naturally. Does NOT open with offers to help. Talks like a friend, not support staff."),
]

@app.post("/narrative/world_chat")
async def world_chat_ai(
    message: str,
    player_name: str,
    player_bio: str = "",
    history: str = "",
    zone_name: str = "",
    location_name: str = "",
    weather: str = "",
    mobs_nearby: str = "",
    time_of_day: str = "",
    active_quests: str = "",
    sim_player_names: str = "",
    chat_context: str = "",
):
    from app.core.ai_client import ai_client
    import re as _re
    name_pool = [n.strip() for n in sim_player_names.split(",") if n.strip()]
    if not name_pool:
        return {"name": "", "text": ""}

    # If the player addressed someone by name, that person should respond.
    # Matches: full name, first camelCase token, or any prefix >= 3 chars at a word boundary.
    # e.g. "oz" -> Ozric | "iron" -> IronGrog | "mist" -> MistRunner
    message_lower = message.lower()
    def _name_mentioned(name: str) -> bool:
        nl = name.lower()
        # Split camelCase into tokens: "IronGrog" -> ["iron", "grog"]
        tokens = [t for t in _re.split(r'(?<=[a-z])(?=[A-Z])', name) if t]
        candidates = {nl}
        for tok in tokens:
            tl = tok.lower()
            if len(tl) >= 3:
                candidates.add(tl)
        # Also add any prefix of the full name >= 3 chars that a word in the message starts with
        msg_words = _re.findall(r'\b[a-z]+', message_lower)
        for word in msg_words:
            if len(word) >= 3 and nl.startswith(word):
                candidates.add(word)
        for candidate in candidates:
            if _re.search(r'\b' + _re.escape(candidate) + r'\b', message_lower):
                return True
        return False
    # Detect group address ("you guys", "everyone", etc.) or multiple names mentioned
    _GROUP_TRIGGERS = {"you guys", "everyone", "all of you", "hey guys", "yall", "y'all", "anyone", "anybody", "you all"}
    is_group_message = any(t in message_lower for t in _GROUP_TRIGGERS)
    addressed_names = [n for n in name_pool if _name_mentioned(n)]
    multi_response = is_group_message or len(addressed_names) >= 2

    if addressed_names:
        friend = addressed_names[0]
    else:
        friend = name_pool[uuid.uuid4().int % len(name_pool)]

    persona_idx = sum(ord(c) for c in friend) % len(_CHAT_PERSONALITIES)
    persona_name, persona_desc = _CHAT_PERSONALITIES[persona_idx]

    # Ground the AI firmly in what actually exists in this zone
    loc_str = location_name or zone_name or "the zone"
    mob_list = mobs_nearby if mobs_nearby else ""
    # Only surface dramatic weather — mundane weather just pollutes the chat
    dramatic_weather = {"stormy", "raining", "foggy", "blizzard"}
    weather_hint = f" ({weather})" if weather and weather.lower() in dramatic_weather else ""

    # Who else is in the zone — for factual "who's online" answers
    others_in_zone = [n for n in name_pool if n != friend]
    # Keep this factual only — don't let the model start addressing other sim players
    online_hint = f" Also online in this zone: {', '.join(others_in_zone)}." if others_in_zone else ""

    # The conversation is directed at the player — make sure the responder knows who to reply to
    reply_target = f" You are replying to {player_name}." if player_name not in ("__ambient__",) else ""

    # If the player asked a question, nudge the responder to actually answer it
    question_nudge = f" {player_name} asked a question — answer it." if message_lower.rstrip().endswith("?") and player_name not in ("__ambient__",) else ""

    # Occasionally reference another player by name naturally (not to address them directly)
    ref_nudge = ""
    if others_in_zone and random.random() < 0.25:
        ref_nudge = f" You can mention {random.choice(others_in_zone)} by name in passing if it fits naturally."

    context_hint = f" Earlier: {chat_context}" if chat_context else ""

    mob_rule = (
        f"The ONLY creatures in this zone are: {mob_list}. Do not use any other creature names."
        if mob_list else "There are no creatures nearby. Do not invent any."
    )

    system_prompt = (
        # Hard rules first so small models read them before persona
        f"STRICT RULES: under 12 words. all lowercase. no emojis. no asterisks. no quotes.\n"
        f"{mob_rule}\n"
        f"NEVER invent prices, lore, game mechanics, NPC names, spawn rates, mob counts, or timers. NEVER describe the weather or scenery.\n"
        f"Do NOT roleplay as a fantasy character. Write like a normal person texting in a game chat.\n"
        # Identity
        f"You are {friend}, a real person playing a fantasy MMO, typing in world chat. "
        f"{persona_desc} Zone: {loc_str}{weather_hint}.{online_hint}{context_hint}"
        f"{reply_target}{question_nudge}{ref_nudge}"
    )

    # Chat-log completion: build history as plain text, let LLM complete next line
    # Keep last 10 lines, but always include the last 3 lines from the responding player for continuity
    # Strip lines that mention hallucinated names (not in known_names or mob list) to prevent snowballing
    history_lines = []
    if history:
        for line in history.strip().split("\n"):
            if "]:" in line:
                parts = line.split("]:", 1)
                speaker = parts[0].lstrip("[")
                text = parts[1].strip()
                history_lines.append((speaker, text))

    friend_lines = [(s, t) for s, t in history_lines if s == friend][-3:]
    other_lines  = [(s, t) for s, t in history_lines if s != friend][-7:]
    combined = sorted(set(friend_lines + other_lines), key=lambda x: history_lines.index(x) if x in history_lines else 0)
    history_block = "\n".join(f"{s}: {t}" for s, t in combined[-10:]) + "\n" if combined else ""
    prompt = f"{history_block}{player_name}: {message}\n{friend}:"

    try:
        reply = await ai_client.generate_content(prompt, system_prompt, max_tokens=45)
        reply = reply.split("\n")[0]
        if reply.lower().startswith(f"{friend.lower()}:"):
            reply = reply[len(f"{friend}:"):].strip()
        reply = reply.replace("**", "").replace("*", "").strip().strip('"\'')
    except Exception:
        mob = mobs_nearby.split(',')[0].strip() if mobs_nearby else None
        bucket = int(time.time() // 30)
        name_hash = sum(ord(c) for c in friend)
        # Only use contextual fallbacks when the player's message is actually about that topic
        msg_words = set(message_lower.split())
        fallbacks_ctx = []
        if mob and any(w in message_lower for w in [mob.lower(), "mob", "farm", "loot", "kill", "drop"]):
            fallbacks_ctx += [
                f"yeah {mob}s have been dropping decent loot",
                f"pulled too many {mob}s and died lmao",
                f"those {mob}s hit harder than they look",
                f"good luck, {mob}s are annoying today",
            ]
        if zone_name and any(w in message_lower for w in [zone_name.lower(), "zone", "area", "here", "farm"]):
            fallbacks_ctx += [
                f"{zone_name} has been decent today",
                f"yeah this zone is alright for grinding",
                f"first time in {zone_name}? watch the elites",
            ]
        if weather in ("foggy", "stormy") and any(w in message_lower for w in ["weather", "fog", "storm", "see", "visibility"]):
            fallbacks_ctx += [
                "yeah the weather out here is rough",
                "this fog makes everything harder ngl",
            ]
        fallbacks_generic = [
            "lol same",
            "gl out there",
            "honestly yeah",
            "wait what level are you",
            "drop rates feel nerfed today",
            "loot's been dry all session",
            "just died to something embarrassing ngl",
            "that sounds about right",
            "i feel that",
            "nice one",
            "oof",
            "wait really? how",
            "same but worse",
            "bro i just respawned",
            "LF group for the named boss anyone?",
            "what class are you running",
            "grind never stops fr",
            "this zone has been rough today",
            "respawn timers are actually killing me",
            "elite near here hits hard watch out",
            "i've died here like 5 times already",
            "how are you still alive lmao",
            "that tracks",
            "lmaooo",
            "been farming here for an hour send help",
        ]
        pool = fallbacks_ctx + fallbacks_generic
        reply = pool[(name_hash + bucket) % len(pool)]

    responses = [{"name": friend, "text": reply}]

    # Generate a second response if the player addressed multiple people or said "you guys" etc.
    if multi_response and len(name_pool) >= 2:
        if len(addressed_names) >= 2:
            second = addressed_names[1]
        else:
            second_pool = [n for n in name_pool if n != friend]
            second = random.choice(second_pool)

        second_persona_idx = sum(ord(c) for c in second) % len(_CHAT_PERSONALITIES)
        _, second_persona_desc = _CHAT_PERSONALITIES[second_persona_idx]
        second_system = system_prompt.replace(f"You are {friend},", f"You are {second},", 1).replace(persona_desc, second_persona_desc, 1)
        second_prompt = f"{history_block}{player_name}: {message}\n{second}:"
        try:
            sr = await ai_client.generate_content(second_prompt, second_system, max_tokens=45)
            sr = sr.split("\n")[0]
            if sr.lower().startswith(f"{second.lower()}:"):
                sr = sr[len(f"{second}:"):].strip()
            sr = sr.replace("**", "").replace("*", "").strip().strip('"\'')
            if sr and sr != reply:
                responses.append({"name": second, "text": sr})
        except Exception:
            pass

    return {"name": responses[0]["name"], "text": responses[0]["text"], "responses": responses}


# ──────────────────────────────────────────────
# VENDOR
# ──────────────────────────────────────────────

@app.get("/vendor/{player_id}")
async def get_vendor_stock(player_id: str, npc_name: str):
    """Return the vendor's item list and player's current gold."""
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    z_data = await vec_db.get_zone(player.current_zone_id)
    zone = Zone(**z_data)
    loc = next((l for l in zone.locations if l.id == player.current_location_id), None)
    npc = next(
        (n for n in (loc.npcs if loc else [])
         if npc_name.lower() in n.name.lower() and n.role == "vendor"),
        None
    )
    if not npc:
        raise HTTPException(status_code=404, detail="Vendor not found here")

    return {"vendor_name": npc.name, "items": npc.vendor_items, "player_gold": player.gold}


@app.post("/vendor/buy/{player_id}")
async def vendor_buy(player_id: str, npc_name: str, item_id: str):
    """Purchase an item from a vendor."""
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    z_data = await vec_db.get_zone(player.current_zone_id)
    zone = Zone(**z_data)
    loc = next((l for l in zone.locations if l.id == player.current_location_id), None)
    npc = next(
        (n for n in (loc.npcs if loc else [])
         if npc_name.lower() in n.name.lower() and n.role == "vendor"),
        None
    )
    if not npc:
        raise HTTPException(status_code=404, detail="Vendor not found here")

    item_data = next((i for i in npc.vendor_items if i["id"] == item_id), None)
    if not item_data:
        raise HTTPException(status_code=404, detail="Item not sold by this vendor")

    price = item_data.get("price", 0)
    if player.gold < price:
        return {"success": False, "message": f"Not enough gold. Need {price}, have {player.gold}."}
    if len(player.inventory) >= BAG_SIZE:
        return {"success": False, "message": "Bags full. Sell something to make room."}

    player.gold -= price
    bought = Item(**{k: v for k, v in item_data.items() if k != "price"})
    player.inventory.append(bought)

    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {
        "success": True,
        "message": f"Purchased [{bought.name}] for {price} gold.",
        "item": bought.model_dump(mode='json'),
        "player_gold": player.gold,
    }


@app.post("/vendor/sell/{player_id}")
async def vendor_sell(player_id: str, item_id: str):
    """Sell an item from inventory for 40% of its value."""
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    item = next((i for i in player.inventory if i.id == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not in inventory")

    # Sell price: ~40% of vendor buy price (vendor = stat * level * 2, sell = stat * level * 0.8)
    stat_total = sum(item.stats.values()) if item.stats else 0
    sell_price = max(1, int(item.level * stat_total * 0.8))

    player.gold += sell_price
    player.inventory = [i for i in player.inventory if i.id != item_id]

    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {
        "success": True,
        "message": f"Sold [{item.name}] for {sell_price} gold.",
        "sell_price": sell_price,
        "player_gold": player.gold,
    }


@app.post("/vendor/sell_junk/{player_id}")
async def vendor_sell_junk(player_id: str):
    """Sell every Common-rarity non-consumable item in inventory at once."""
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    junk = [i for i in player.inventory if i.rarity == "Common" and i.slot != "consumable"]
    if not junk:
        return {"success": True, "message": "No Common items to sell.", "gold_gained": 0,
                "player_gold": player.gold, "sold_count": 0}

    total_gold = sum(max(1, int(i.level * sum(i.stats.values()) * 0.8)) for i in junk)
    player.gold += total_gold
    junk_ids = {i.id for i in junk}
    player.inventory = [i for i in player.inventory if i.id not in junk_ids]

    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {
        "success":    True,
        "message":    f"Sold {len(junk)} Common item(s) for {total_gold} gold.",
        "gold_gained": total_gold,
        "player_gold": player.gold,
        "sold_count":  len(junk),
    }


# ──────────────────────────────────────────────
# FLEE
# ──────────────────────────────────────────────

@app.post("/action/flee/{player_id}")
async def flee_combat(player_id: str, mob_name: str):
    """Attempt to flee from a mob. 60% escape chance; on failure, take one hit."""
    now = time.time()
    p_data = await vec_db.get_player(player_id)
    if not p_data: raise HTTPException(status_code=404, detail="Player not found")
    player = Player(**p_data)

    z_data = await vec_db.get_zone(player.current_zone_id)
    zone = Zone(**z_data)
    loc = next((l for l in zone.locations if l.id == player.current_location_id), None)

    # Restore any mobs whose respawn timer has fired (same cleanup as attack endpoint)
    for m in (loc.mobs if loc else []):
        if m.respawn_at is not None and now >= m.respawn_at:
            m.hp = m.max_hp
            m.respawn_at = None

    target_mob = next(
        (m for m in (loc.mobs if loc else [])
         if mob_name.lower() in m.name.lower() and m.respawn_at is None),
        None
    )
    if not target_mob:
        return {"success": True, "fled": True, "message": "Nothing to flee from."}

    messages = []
    fled = random.random() < 0.60
    player_dead = False
    respawn_location_id = None

    if fled:
        messages.append(f"You successfully flee from {target_mob.name}!")
    else:
        # Take a counter-hit on failed flee
        _, player_dead = combat_engine.resolve_tick(target_mob, player)
        messages.append(f"Failed to escape! {target_mob.name} lands a parting blow!")
        if player_dead:
            player.deaths += 1
            xp_penalty = int(player.xp * 0.15)
            player.xp = max(0, player.xp - xp_penalty)
            player.hp = max(1, player.max_hp // 2)
            if zone.locations:
                player.current_location_id = zone.locations[0].id
                respawn_location_id = zone.locations[0].id
            penalty_msg = f" Lost {xp_penalty:,} XP." if xp_penalty else ""
            messages.append(f"☠ You were slain while fleeing!{penalty_msg} You wake at the settlement.")

    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {
        "success":             True,
        "fled":                fled,
        "messages":            messages,
        "player_hp":           player.hp,
        "player_xp":           player.xp,
        "player_dead":         player_dead,
        "respawn_location_id": respawn_location_id,
    }


# ──────────────────────────────────────────────
# ENTITY DESCRIPTIONS
# ──────────────────────────────────────────────

_desc_cache: dict[str, str] = {}

@app.get("/describe/entity")
async def describe_entity(
    name: str,
    entity_type: str = "creature",
    is_elite: bool = False,
    is_named: bool = False,
    zone: str = "",
):
    cache_key = f"{entity_type}:{name.lower()}"
    if cache_key in _desc_cache:
        return {"description": _desc_cache[cache_key]}

    from app.core.ai_client import ai_client

    rank = "legendary named " if is_named else "elite " if is_elite else ""
    location = f" in {zone}" if zone else ""

    if entity_type == "npc":
        prompt = (
            f"Describe {name}, an NPC{location}, in 2 sentences. "
            f"Cover their appearance and one personality trait. No stats, no markdown."
        )
    elif entity_type == "death":
        prompt = (
            f"Write a 2-sentence dramatic death scene. The player was killed by a {rank}{name}{location}. "
            f"Describe the fatal moment vividly. No stats, no markdown, past tense."
        )
    else:
        prompt = (
            f"Describe a {rank}{name}{location} in 2 sentences for a fantasy RPG. "
            f"Cover its appearance and how it moves or threatens. Be vivid and specific. No stats, no markdown."
        )

    system_prompt = "You are a fantasy RPG narrator. Write concise, atmospheric descriptions. Plain text only."

    try:
        desc = await ai_client.generate_content(prompt, system_prompt, max_tokens=80)
        if desc and len(desc.strip()) > 20:
            if entity_type != "death":  # death scenes are never cached — each death is unique
                _desc_cache[cache_key] = desc.strip()
            return {"description": desc.strip()}
    except Exception:
        pass
    return {"description": None}


@app.get("/describe/location")
async def describe_location(name: str, loc_description: str = "", zone: str = ""):
    cache_key = f"loc:{name.lower()}"
    if cache_key in _desc_cache:
        return {"description": _desc_cache[cache_key]}

    from app.core.ai_client import ai_client

    context = f" in {zone}" if zone else ""
    prompt = (
        f"Location: {name}{context}. Known as: {loc_description}\n"
        f"Write 1 sentence of atmospheric flavour — what it feels like to stand here right now. "
        f"Sensory detail. No stats, no markdown."
    )
    system_prompt = "You are a fantasy RPG narrator. One sentence, plain text, vivid and grounded."

    try:
        desc = await ai_client.generate_content(prompt, system_prompt, max_tokens=60)
        if desc and len(desc.strip()) > 15:
            _desc_cache[cache_key] = desc.strip()
            return {"description": desc.strip()}
    except Exception:
        pass
    return {"description": None}


# ──────────────────────────────────────────────
# ADMIN / DEV TOOLS
# ──────────────────────────────────────────────

# ── Dungeon endpoints ─────────────────────────────────────────────────────────

@app.post("/dungeon/enter/{player_id}")
async def dungeon_enter(player_id: str, is_raid: bool = False):
    p_data = await vec_db.get_player(player_id)
    if not p_data:
        raise HTTPException(status_code=404, detail="Player not found.")
    player = Player(**p_data)

    min_level = 20 if is_raid else 10
    if player.level < min_level:
        raise HTTPException(status_code=400,
            detail=f"You must be level {min_level}+ to enter {'a raid' if is_raid else 'a dungeon'}.")
    if is_raid:
        gs = calculate_gear_score(player)
        if gs < RAID_GEAR_MIN:
            raise HTTPException(status_code=400,
                detail=f"Gear score too low for a raid ({gs}/{RAID_GEAR_MIN}). Farm dungeons first.")

    run = generate_run(player, is_raid=is_raid)
    _dungeon_runs[run.id] = run
    player.active_dungeon_run_id = run.id
    await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return run.model_dump(mode='json')


@app.post("/dungeon/attack/{run_id}")
async def dungeon_attack(run_id: str, player_id: str):
    run = _dungeon_runs.get(run_id)
    if not run or run.status != "active":
        raise HTTPException(status_code=404, detail="Dungeon run not found or already ended.")

    p_data = await vec_db.get_player(player_id)
    if not p_data:
        raise HTTPException(status_code=404, detail="Player not found.")
    player = Player(**p_data)

    result = resolve_round(run, player)

    # Track clears on the player record
    if result.get("run_cleared"):
        if run.is_raid:
            player.raids_cleared = (player.raids_cleared or 0) + 1
        else:
            player.dungeons_cleared = (player.dungeons_cleared or 0) + 1

    # Evict terminal runs and clear player pointer BEFORE saving so DB is consistent
    updated_run = DungeonRun(**result["run"])
    if updated_run.status in ("cleared", "wiped"):
        _dungeon_runs.pop(run_id, None)
        player.active_dungeon_run_id = None
    else:
        _dungeon_runs[run_id] = updated_run

    await vec_db.save_player(player_id, player.model_dump(mode='json'))

    return {
        **result,
        "player_hp":    player.hp,
        "player_max_hp": player.max_hp,
        "player_xp":    player.xp,
        "player_gold":  player.gold,
        "player_level": player.level,
        "player_inventory": [i.model_dump(mode='json') for i in player.inventory],
    }


@app.post("/dungeon/advance/{run_id}")
async def dungeon_advance(run_id: str, player_id: str):
    run = _dungeon_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Dungeon run not found.")
    if not run.rooms[run.room_index].cleared:
        raise HTTPException(status_code=400, detail="Current room is not cleared yet.")
    if run.room_index >= len(run.rooms) - 1:
        raise HTTPException(status_code=400, detail="Already in the final room.")
    run.room_index += 1
    _dungeon_runs[run_id] = run  # persist advance so disconnect doesn't regress room
    return run.model_dump(mode='json')


@app.post("/dungeon/flee/{run_id}")
async def dungeon_flee(run_id: str, player_id: str):
    _dungeon_runs.pop(run_id, None)
    p_data = await vec_db.get_player(player_id)
    if p_data:
        player = Player(**p_data)
        player.active_dungeon_run_id = None
        await vec_db.save_player(player_id, player.model_dump(mode='json'))
    return {"success": True}


@app.post("/admin/reset")
async def reset_all_data():
    """
    Wipe all persisted game data (SQLite rows + in-memory caches).
    Creates a clean slate — player must recreate their character.
    No server restart needed. Intended for development / testing only.
    """
    _attack_times.clear()
    vec_db.reset_all()
    return {
        "success": True,
        "message": "All game data cleared. Create a new character to begin.",
    }
