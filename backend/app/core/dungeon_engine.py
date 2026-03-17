"""
dungeon_engine.py
Round-based instanced dungeon system.

Dungeon (5-player): 3 rooms — trash → trash+elite → boss
Raid   (10-player): 5 rooms — trash → trash+elite → mini-boss → trash → final boss (phase 2 enrage)

All combatants resolve in the same round tick:
  player → party members → surviving mobs counter-attack
"""
import random
import uuid
import time
from app.models.schemas import DungeonMember, DungeonRoom, DungeonRun, Mob, Player
from app.core.scaling_math import ScalingMath, CLASS_STATS
from app.core.combat_engine import CombatEngine
from app.core.world_generator import _make_mobs, _roll_loot

combat_engine = CombatEngine()

# ── Gear score ───────────────────────────────────────────────────────────────
_RARITY_GS = {"Common": 1.0, "Uncommon": 1.5, "Rare": 2.5, "Epic": 4.0, "Legendary": 7.0}
RAID_GEAR_MIN = 100  # minimum gear score to enter a raid

def calculate_gear_score(player) -> int:
    """Sum of all equipped item stat values × rarity multiplier."""
    score = 0
    for item in player.equipment.values():
        if not item or not item.stats:
            continue
        mult = _RARITY_GS.get(item.rarity, 1.0)
        score += int(sum(item.stats.values()) * mult)
    return score

# ── NPC archetype pool ────────────────────────────────────────────────────────
# (name, char_class, role, hp_mult, dmg_mult)
_NPC_POOL = [
    ("Theron",  "Warrior", "tank",   1.30, 0.80),
    ("Valdris", "Paladin", "tank",   1.25, 0.75),
    ("Sylvara", "Hunter",  "dps",    1.00, 1.10),
    ("Drake",   "Rogue",   "dps",    0.90, 1.20),
    ("Elowen",  "Druid",   "healer", 0.90, 0.70),
    ("Ashe",    "Priest",  "healer", 0.85, 0.65),
    ("Vex",     "Mage",    "dps",    0.80, 1.30),
    ("Kael",    "Shaman",  "dps",    1.10, 1.05),
]

# Class passive procs reused from main.py (kept local to avoid circular import)
_CLASS_PROCS = {
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

# ── Dungeon name templates ─────────────────────────────────────────────────────
_DUNGEON_NAMES = [
    "The Sunken Vault", "Ashen Catacombs", "The Blighted Spire",
    "Caverns of the Damned", "The Shattered Keep", "Ruins of Valdrath",
    "The Festering Pit", "Temple of the Forgotten", "Ironhold Depths",
    "The Crimson Warren",
]

_ROOM_NAMES = [
    ["The Antechamber", "The Outer Hall", "The Entrance Passage"],
    ["The Inner Sanctum", "The Warden's Hall", "The Sealed Chamber"],
    ["The Boss Chamber", "The Throne Room", "The Inner Keep"],      # dungeon boss / raid mini-boss
    ["The Deeper Reaches", "The Forsaken Hall", "The Blood Corridor"],  # raid only
    ["The Final Sanctum", "The Throne of Ruin", "The Eternal Chamber"], # raid final boss
]

# Mob type pools for dungeon rooms keyed by level tier
_DUNGEON_MOB_POOLS = {
    (1, 10):  ["Skeleton", "Zombie", "Ghoul", "Cultist", "Tomb Rat"],
    (11, 20): ["Undead Knight", "Plague Hound", "Void Shade", "Dark Acolyte"],
    (21, 35): ["Infernal Imp", "Chaos Warrior", "Soul Reaper", "Blight Wraith"],
    (36, 60): ["Demon Warden", "Cursed Colossus", "Ancient Specter", "Void Tyrant"],
}


def _get_mob_pool(level: int) -> list[str]:
    for (lo, hi), pool in _DUNGEON_MOB_POOLS.items():
        if lo <= level <= hi:
            return pool
    return _DUNGEON_MOB_POOLS[(36, 60)]


def _build_party(player: Player, is_raid: bool = False) -> list[DungeonMember]:
    """Assign AI party members based on player role and dungeon type."""
    tank_classes   = {"Warrior", "Paladin"}
    healer_classes = {"Priest"}

    if is_raid:
        # 10-player: 2 tanks + 2 healers + 6 DPS (player + 9 NPCs)
        roles = ["tank", "tank", "healer", "healer", "dps", "dps", "dps", "dps", "dps"]
    elif player.char_class in tank_classes:
        # Player is tank: bring 1 healer + 3 DPS
        roles = ["healer", "dps", "dps", "dps"]
    elif player.char_class in healer_classes:
        # Player is healer: bring 1 tank + 3 DPS
        roles = ["tank", "dps", "dps", "dps"]
    else:
        # Player is DPS: bring 1 tank + 1 healer + 2 DPS
        roles = ["tank", "healer", "dps", "dps"]

    # Pick NPCs matching roles, no repeats
    used_names: set[str] = {player.name}
    members: list[DungeonMember] = []
    pool = list(_NPC_POOL)
    random.shuffle(pool)

    for role in roles:
        candidates = [n for n in pool if n[2] == role and n[0] not in used_names]
        if not candidates:
            candidates = [n for n in pool if n[0] not in used_names]
        if not candidates:
            continue
        npc = candidates[0]
        pool.remove(npc)
        name, char_class, npc_role, hp_mult, dmg_mult = npc
        used_names.add(name)
        base_hp  = int(ScalingMath.get_max_hp(player.level)  * hp_mult)
        base_dmg = int(ScalingMath.get_damage(player.level) * dmg_mult)
        members.append(DungeonMember(
            id=f"npc_{name.lower()}_{uuid.uuid4().hex[:6]}",
            name=name,
            char_class=char_class,
            role=npc_role,
            hp=base_hp,
            max_hp=base_hp,
            damage=base_dmg,
        ))
    return members


def _build_rooms(level: int, run_id: str, is_raid: bool = False) -> list[DungeonRoom]:
    mob_pool  = _get_mob_pool(level)
    # Dungeon: rooms 0-2 (3 rooms).  Raid: rooms 0-4 (5 rooms).
    room_defs = [
        # (name_index, count, force_boss, level_bump)
        (0, 4, False, 0),
        (1, 3, False, 0),
        (2, 1, True,  0),    # dungeon boss / raid mini-boss
    ]
    if is_raid:
        room_defs += [
            (3, 5, False, 1),   # deeper trash — harder (+1 level)
            (4, 1, True,  2),   # final boss — significantly harder (+2 levels)
        ]

    rooms = []
    for i, (name_idx, count, force_boss, level_bump) in enumerate(room_defs):
        room_name = random.choice(_ROOM_NAMES[name_idx])
        mob_name  = random.choice(mob_pool)
        mob_level = level + level_bump
        mobs = _make_mobs(mob_name, mob_level, run_id, i, count=count, force_boss=force_boss)
        for j, m in enumerate(mobs):
            m.id = f"mob_{run_id}_{i}_{j}"
        rooms.append(DungeonRoom(index=i, name=room_name, mobs=mobs))
    return rooms


def generate_run(player: Player, is_raid: bool = False) -> DungeonRun:
    run_id = uuid.uuid4().hex[:12]
    return DungeonRun(
        id=run_id,
        player_id=player.id if hasattr(player, 'id') else player.name.lower(),
        dungeon_name=random.choice(_DUNGEON_NAMES),
        dungeon_level=player.level,
        is_raid=is_raid,
        rooms=_build_rooms(player.level, run_id, is_raid=is_raid),
        party=_build_party(player, is_raid=is_raid),
    )


# ── Round resolution ──────────────────────────────────────────────────────────

def _member_as_mob(m: DungeonMember) -> Mob:
    """Wrap a DungeonMember in a Mob-like object for combat_engine reuse."""
    return Mob(
        id=m.id, name=m.name, level=1,
        hp=m.hp, max_hp=m.max_hp, damage=m.damage,
        description="",
    )


def _roll_proc(member: DungeonMember, target: Mob, log: list) -> bool:
    """Roll class proc for an AI party member. Returns True if dodge (skip mob counter)."""
    proc = _CLASS_PROCS.get(member.char_class)
    if not proc or random.random() > proc["chance"]:
        return False
    ptype, mult, label = proc["type"], proc["mult"], proc["label"]
    if ptype == "damage":
        bonus = max(1, int(member.damage * mult))
        target.hp = max(0, target.hp - bonus)
        log.append(f"  ★ {member.name} {label}! +{bonus} dmg!")
    elif ptype == "heal":
        heal = max(1, int(member.max_hp * mult))
        member.hp = min(member.max_hp, member.hp + heal)
        log.append(f"  ✦ {member.name} {label}! +{heal} HP!")
    elif ptype == "drain":
        bonus = max(1, int(member.damage * mult))
        member.hp = min(member.max_hp, member.hp + bonus // 2)
        target.hp = max(0, target.hp - bonus)
        log.append(f"  ✧ {member.name} {label}! -{bonus} / +{bonus//2} HP!")
    elif ptype == "dodge":
        log.append(f"  ☽ {member.name} {label}!")
    return ptype == "dodge"


def resolve_round(run: DungeonRun, player: Player) -> dict:
    """
    Resolve one full combat round for the current room.
    Returns a result dict consumed by the /dungeon/attack endpoint.
    """
    room = run.rooms[run.room_index]
    alive_mobs = [m for m in room.mobs if m.hp > 0]
    round_log: list[str] = []
    xp_gained  = 0
    gold_gained = 0
    taunt_active = False

    if not alive_mobs:
        return {"run": run, "round_log": ["Room is already clear."],
                "room_cleared": True, "run_cleared": run.room_index >= len(run.rooms) - 1,
                "wiped": False, "xp_gained": 0, "gold_gained": 0}

    primary_mob = alive_mobs[0]

    # ── 1. Player attacks primary mob ────────────────────────────────────────
    atk_msgs, mob_dead = combat_engine.resolve_tick(player, primary_mob)
    round_log.extend(atk_msgs)

    # ── 2. Each living party member acts ────────────────────────────────────
    living_members = [m for m in run.party if m.is_alive]
    alive_mobs_after = [m for m in room.mobs if m.hp > 0]

    for member in living_members:
        if not alive_mobs_after:
            break
        target = alive_mobs_after[0]

        if member.role == "healer":
            # Heal the most injured combatant (player or party member) if below 40%
            candidates = [(player.hp / player.max_hp, "player")] + \
                         [(m.hp / m.max_hp, m.id) for m in living_members]
            neediest_ratio, neediest_id = min(candidates, key=lambda x: x[0])
            if neediest_ratio < 0.40:
                heal = int(member.max_hp * 0.18)
                if neediest_id == "player":
                    player.hp = min(player.max_hp, player.hp + heal)
                    member.last_action = f"✦ HEAL → You +{heal}"
                    round_log.append(f"  ✦ {member.name} heals you for {heal}!")
                else:
                    target_m = next((m for m in living_members if m.id == neediest_id), None)
                    if target_m:
                        target_m.hp = min(target_m.max_hp, target_m.hp + heal)
                        member.last_action = f"✦ HEAL → {target_m.name} +{heal}"
                        round_log.append(f"  ✦ {member.name} heals {target_m.name} for {heal}!")
                continue
            # No one needs healing — attack instead
            atk, dead = combat_engine.resolve_tick(_member_as_mob(member), target)
            # Sync damage back (resolve_tick modified target directly via hp ref)
            member.last_action = atk[0] if atk else ""
            round_log.extend(atk)
            _roll_proc(member, target, round_log)

        elif member.role == "tank":
            if random.random() < 0.25:
                taunt_active = True
                member.last_action = "⚑ TAUNT"
                round_log.append(f"  ⚑ {member.name} taunts — mob damage -20% this round!")
            else:
                atk, dead = combat_engine.resolve_tick(_member_as_mob(member), target)
                member.last_action = atk[0] if atk else ""
                round_log.extend(atk)
                _roll_proc(member, target, round_log)

        else:  # dps
            atk, dead = combat_engine.resolve_tick(_member_as_mob(member), target)
            member.last_action = atk[0] if atk else ""
            round_log.extend(atk)
            _roll_proc(member, target, round_log)

        alive_mobs_after = [m for m in room.mobs if m.hp > 0]

    # ── 3. Surviving mobs counter-attack ────────────────────────────────────
    surviving_mobs = [m for m in room.mobs if m.hp > 0]
    all_living = [("player", player)] + [("member", m) for m in living_members]
    if surviving_mobs and all_living:
        for mob in surviving_mobs:
            target_type, target_obj = random.choice(all_living)
            # Taunt redirects to the tank if present
            if taunt_active:
                tank = next((m for m in living_members if m.role == "tank"), None)
                if tank:
                    target_type, target_obj = "member", tank

            orig_damage = mob.damage
            if taunt_active:
                mob.damage = int(mob.damage * 0.8)
            if target_type == "player":
                ctr_msgs, player_dead = combat_engine.resolve_tick(mob, player)
                round_log.extend(ctr_msgs)
            else:
                # Build a temporary Mob proxy to attack the DungeonMember
                proxy = Mob(id=target_obj.id, name=target_obj.name, level=player.level,
                            hp=target_obj.hp, max_hp=target_obj.max_hp,
                            damage=target_obj.damage, description="")
                ctr_msgs, member_dead = combat_engine.resolve_tick(mob, proxy)
                target_obj.hp = proxy.hp  # sync HP back
                if target_obj.hp <= 0:
                    target_obj.is_alive = False
                    target_obj.last_action = "💀 DEAD"
                    round_log.append(f"  💀 {target_obj.name} has fallen!")
                round_log.extend(ctr_msgs)
            mob.damage = orig_damage  # restore after this tick

    # ── 4. Handle newly dead mobs ────────────────────────────────────────────
    for mob in room.mobs:
        if mob.hp <= 0:
            xp_base  = ScalingMath.get_xp_required(mob.level) // 8
            xp_mult  = 4 if mob.is_named else (2 if mob.is_elite else 1)
            xp_gained   += xp_base * xp_mult
            gold_gained += random.randint(1, max(1, mob.level)) * (3 if mob.is_named or mob.is_elite else 1)

    # ── 5. Boss enrage check (raid phase 2 — triggers once at ≤30% HP) ────────
    is_final_room = run.room_index == len(run.rooms) - 1
    if run.is_raid and is_final_room and not run.boss_enraged:
        boss_mob = next((m for m in room.mobs if m.is_named or m.is_elite), None)
        if boss_mob and boss_mob.hp > 0 and (boss_mob.hp / boss_mob.max_hp) <= 0.30:
            run.boss_enraged = True
            boss_mob.damage = int(boss_mob.damage * 1.4)
            round_log.append(f"  ⚡ {boss_mob.name} ENRAGES — damage +40%! Finish them!")

    # ── 6. Check room/run state ──────────────────────────────────────────────
    room_cleared = all(m.hp <= 0 for m in room.mobs)
    if room_cleared:
        room.cleared = True

    all_dead = player.hp <= 0 and all(not m.is_alive for m in run.party)
    player_dead = player.hp <= 0
    if player_dead:
        round_log.append("  💀 You have fallen!")

    run_cleared = room_cleared and run.room_index >= len(run.rooms) - 1

    # ── 7. Wipe check ────────────────────────────────────────────────────────
    wiped = all_dead
    if wiped:
        run.status = "wiped"
        round_log.append("☠ PARTY WIPED.")
    elif run_cleared:
        run.status = "cleared"
        round_log.append("★ RAID CLEARED! A new tier of content awaits." if run.is_raid else "★ DUNGEON CLEARED!")

    # ── 8. Apply XP and gold ─────────────────────────────────────────────────
    player.xp   += xp_gained
    player.gold += gold_gained

    # Level-up loop
    leveled_up = False
    hp_mult, dmg_mult = CLASS_STATS.get(player.char_class, (1.0, 1.0))
    while player.xp >= player.next_level_xp:
        player.xp -= player.next_level_xp
        player.level += 1
        player.next_level_xp = ScalingMath.get_xp_required(player.level)
        leveled_up = True
        player.max_hp = int(ScalingMath.get_max_hp(player.level) * hp_mult)
        player.hp = player.max_hp
        player.damage = int(ScalingMath.get_damage(player.level) * dmg_mult)
        round_log.append(f"  ⬆ LEVEL UP! Now level {player.level}!")

    # ── 9a. Keep rolling combat log (last 5 meaningful lines) ────────────────
    run.combat_log = (run.combat_log + round_log)[-5:]

    # ── 9. Roll loot on boss death ────────────────────────────────────────────
    # Dungeon: zone_tier="dungeon" (1.6× stats), 1-2 items
    # Raid:    zone_tier="raid"    (2.8× stats), 2-3 items, guaranteed Epic+
    loot_items = []
    if run_cleared:
        boss = next((m for m in room.mobs if m.is_named), room.mobs[0] if room.mobs else None)
        if boss:
            tier = "raid" if run.is_raid else "dungeon"
            rolls = 3 if run.is_raid else (2 if boss.is_named else 1)
            for _ in range(rolls):
                item = _roll_loot(boss.level, boss.loot_table,
                                  char_class=player.char_class, zone_tier=tier)
                if item:
                    player.inventory.append(item)
                    loot_items.append(item.model_dump(mode='json'))

    return {
        "run":          run.model_dump(mode='json'),
        "round_log":    round_log,
        "room_cleared": room_cleared,
        "run_cleared":  run_cleared,
        "wiped":        wiped,
        "player_dead":  player_dead,
        "xp_gained":    xp_gained,
        "gold_gained":  gold_gained,
        "leveled_up":   leveled_up,
        "loot":         loot_items,
    }
