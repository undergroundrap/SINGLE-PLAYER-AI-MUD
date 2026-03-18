"""
sim_run.py — Headless game simulation for fast end-to-end testing.

Plays through the full game loop automatically — no browser, no manual input.
Exercises every major system in order so you can verify everything is wired up.

Usage:
    python scripts/sim_run.py
    python scripts/sim_run.py --base http://localhost:8001
    python scripts/sim_run.py --target-level 15
    python scripts/sim_run.py --no-cleanup

What it exercises (in order):
  1. Character creation + login (rested XP)
  2. Zone topology — confirms hub → path → POI structure
  3. Talk to all NPCs at hub (quest givers + vendor)
  4. Accept all available quests
  5. Buy a healing potion if affordable
  6. Zone sweep loop (repeats until target level):
       a. Hub → each path: harvest plant, fish
       b. Path → each POI: kill all alive mobs, forage if quest targets here
       c. Return to hub: turn in quests, sell junk, rebuy potions
  7. Dungeon run — 3 rooms, full party, collect loot
  8. Zone travel attempt (shows GS gate message if blocked)
  9. Final character state printout

Exits 0 on a clean run, 1 on any hard error.
"""

import sys
import time
import argparse

# ── CLI ────────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://localhost:8000")
parser.add_argument("--target-level", type=int, default=12,
                    help="Level to grind to before running dungeon (min 10)")
parser.add_argument("--no-cleanup", action="store_true",
                    help="Keep the test character after the run")
parser.add_argument("--name", default="SimBot",
                    help="Character name to use")
args = parser.parse_args()

try:
    import requests
except ImportError:
    print("requests not installed — run: pip install requests")
    sys.exit(1)

BASE = args.base
TARGET_LEVEL = max(10, args.target_level)

# ── Colours ───────────────────────────────────────────────────────────────────
R   = "\033[91m"
G   = "\033[92m"
Y   = "\033[93m"
B   = "\033[94m"
M   = "\033[95m"
C   = "\033[96m"
W   = "\033[97m"
DIM = "\033[2m"
RST = "\033[0m"

errors: list[str] = []
_sim_start = time.time()
_section_start = time.time()


def _ts() -> str:
    """Wall-clock elapsed since sim start, e.g. [  42.3s]"""
    return f"{DIM}[{time.time() - _sim_start:6.1f}s]{RST}"


def log(msg: str, color: str = W) -> None:
    print(f"  {_ts()} {color}{msg}{RST}")


def warn(msg: str) -> None:
    errors.append(msg)
    log(f"✗ {msg}", R)


def section(title: str) -> None:
    global _section_start
    elapsed = time.time() - _section_start
    _section_start = time.time()
    print(f"\n{Y}{'─' * 64}{RST}")
    if elapsed > 0.5:   # skip on the very first section (no meaningful elapsed yet)
        print(f"{DIM}  (previous section took {elapsed:.1f}s){RST}")
    print(f"{Y}  {title}{RST}")
    print(f"{Y}{'─' * 64}{RST}")


def req(method: str, path: str, **kwargs):
    url = BASE + path
    try:
        r = getattr(requests, method)(url, timeout=20, **kwargs)
        return r
    except Exception as e:
        warn(f"REQUEST FAILED: {method.upper()} {path} — {e}")
        return None


def die(msg: str) -> None:
    log(f"FATAL: {msg}", R)
    sys.exit(1)


# ── State helpers ─────────────────────────────────────────────────────────────

def fresh_zone(zone_id: str) -> dict:
    r = req("get", f"/zone/{zone_id}")
    return r.json() if r and r.status_code == 200 else {}


def fresh_player(pid: str) -> dict:
    r = req("get", f"/player/{pid}")
    d = r.json() if r and r.status_code == 200 else {}
    return d.get("player", {})


def move(pid: str, loc_id: str) -> bool:
    r = req("post", f"/action/move/{pid}", params={"location_id": loc_id})
    ok = bool(r and r.status_code == 200 and r.json().get("success"))
    return ok


def alive_mobs_at(loc: dict) -> list[dict]:
    now = time.time()
    return [m for m in loc.get("mobs", []) if not m.get("respawn_at") or m["respawn_at"] <= now]


# ── Combat ────────────────────────────────────────────────────────────────────

def attack_once(pid: str, mob_name: str) -> dict | None:
    """Fire one attack, respecting cooldown. Returns response JSON or None."""
    for _ in range(5):
        r = req("post", f"/action/attack/{pid}", params={"mob_name": mob_name})
        if not r:
            return None
        if r.status_code == 429:
            time.sleep(1.6)
            continue
        if r.status_code == 200:
            return r.json()
        # e.g. 404 mob not found
        return None
    return None


def kill_mob(pid: str, mob_name: str, max_rounds: int = 80) -> dict | None:
    """
    Attack mob until target_dead=True or max_rounds exceeded.
    Returns the killing blow response, or None if mob couldn't be killed.
    NOTE: the backend returns 'target_dead', not 'mob_dead'.
    """
    time.sleep(1.6)
    for i in range(max_rounds):
        a = attack_once(pid, mob_name)
        if a is None:
            return None
        if a.get("target_dead"):
            return a
        if a.get("player_dead"):
            # died — respawn and give up on this mob
            log(f"    ☠ Died fighting {mob_name} — respawned", R)
            time.sleep(1.0)
            return None
        time.sleep(1.6)
    log(f"    Gave up on {mob_name} after {max_rounds} rounds (elite/named?)", Y)
    return None


# ── Quest helpers ─────────────────────────────────────────────────────────────

def accept_all_quests(pid: str, zone: dict) -> int:
    """Accept every zone quest not already active or completed."""
    p = fresh_player(pid)
    active_ids = {q["id"] for q in p.get("active_quests", [])}
    completed_ids = set(p.get("completed_quest_ids", []))
    accepted = 0
    for q in zone.get("quests", []):
        if q["id"] in active_ids or q["id"] in completed_ids:
            continue
        r = req("post", f"/quests/accept/{pid}", params={"quest_id": q["id"]})
        if r and r.status_code == 200:
            log(f"  + Accepted: {q['title']}  [{q.get('quest_type','?')}]", C)
            accepted += 1
    return accepted


def turn_in_all_quests(pid: str) -> int:
    """Turn in every completed active quest. Returns number turned in."""
    p = fresh_player(pid)
    done = [q for q in p.get("active_quests", []) if q.get("is_completed")]
    turned = 0
    for q in done:
        r = req("post", f"/quests/complete/{pid}", params={"quest_id": q["id"]})
        if r and r.status_code == 200:
            d = r.json()
            xp = d.get("xp_reward", 0)
            log(f"  ★ Turned in '{q['title']}'  +{xp} XP", G)
            turned += 1
    return turned


def sync_kill_progress(pid: str, mob_name: str, atk_result: dict, zone: dict) -> None:
    """Push kill/gather quest progress for this kill to backend."""
    p = fresh_player(pid)
    for q in p.get("active_quests", []):
        if q.get("is_completed"):
            continue
        qt = q.get("quest_type", "")
        if qt in ("kill", "gather", "hunt"):
            target = q.get("target_id", "").lower()
            if target in mob_name.lower() or mob_name.lower() in target:
                new_prog = min(q["target_count"], q["current_progress"] + 1)
                req("post", f"/quests/progress/{pid}",
                    params={"quest_id": q["id"], "progress": new_prog})


# ── Vendor helpers ────────────────────────────────────────────────────────────

def sell_junk(pid: str) -> None:
    r = req("post", f"/vendor/sell_junk/{pid}")
    if r and r.status_code == 200:
        sj = r.json()
        if sj.get("sold_count", 0) > 0:
            log(f"  Sold {sj['sold_count']} junk item(s)  +{sj['gold_gained']} gold", G)


def buy_healing_potion(pid: str, vendor_name: str) -> bool:
    """Buy a healing potion from vendor if we can afford one and don't have one."""
    p = fresh_player(pid)
    has_potion = any(
        i.get("stats", {}).get("heal_pct") for i in p.get("inventory", [])
    )
    if has_potion:
        return False
    r = req("get", f"/vendor/{pid}", params={"npc_name": vendor_name})
    if not r or r.status_code != 200:
        return False
    vd = r.json()
    stock = vd.get("stock", [])
    gold = vd.get("gold", 0)
    potion = next((i for i in stock if i.get("stats", {}).get("heal_pct")), None)
    if not potion:
        return False
    price = potion.get("price", 9999)
    if gold < price:
        return False
    r2 = req("post", f"/vendor/buy/{pid}",
             params={"npc_name": vendor_name, "item_id": potion["id"]})
    if r2 and r2.status_code == 200:
        log(f"  Bought: {potion['name']} for {price} gold", G)
        return True
    return False


def use_healing_potion_if_low(pid: str) -> bool:
    """Use a healing potion if HP below 40%."""
    p = fresh_player(pid)
    hp, max_hp = p.get("hp", 100), p.get("max_hp", 100)
    if hp / max_hp > 0.40:
        return False
    potion = next(
        (i for i in p.get("inventory", []) if i.get("stats", {}).get("heal_pct")),
        None
    )
    if not potion:
        return False
    r = req("post", f"/action/use/{pid}", params={"item_id": potion["id"]})
    if r and r.status_code == 200:
        new_hp = r.json().get("player_hp", hp)
        log(f"  🧪 Used {potion['name']}  HP: {hp} → {new_hp}", G)
        return True
    return False


# ── Zone sweep ────────────────────────────────────────────────────────────────

def do_zone_sweep(pid: str, zone_id: str, hub_loc_id: str, vendor_name: str | None) -> int:
    """
    Walk hub → each path → each POI → back to hub.
    Returns total kills this sweep.
    """
    zone = fresh_zone(zone_id)
    loc_map = {l["id"]: l for l in zone.get("locations", [])}
    hub = loc_map.get(hub_loc_id)
    if not hub:
        return 0

    kills = 0
    exits = hub.get("exits", {})

    for direction, next_id in exits.items():
        spoke = loc_map.get(next_id)
        if not spoke:
            continue

        # ── PATH LOCATION ──────────────────────────────────────────────────────
        if spoke.get("resources") and len(spoke["resources"]) >= 2:
            plant, fish = spoke["resources"][0], spoke["resources"][1]
            log(f"  [{direction.upper()}] → Path: {spoke['name']}  "
                f"({plant} / {fish})", C)
            move(pid, spoke["id"])

            # Harvest
            r = req("post", f"/action/harvest/{pid}")
            if r and r.status_code == 200:
                item = r.json().get("item", {})
                log(f"    🌿 Harvested {item.get('name','?')}", G)
            elif r and r.status_code == 429:
                log(f"    🌿 Harvest on cooldown", DIM)
            else:
                warn(f"harvest failed ({r.status_code if r else 'no response'})")

            # Fish
            r = req("post", f"/action/fish/{pid}")
            if r and r.status_code == 200:
                item = r.json().get("item", {})
                log(f"    🎣 Caught {item.get('name','?')}", G)
            elif r and r.status_code == 429:
                log(f"    🎣 Fish on cooldown", DIM)
            else:
                warn(f"fish failed ({r.status_code if r else 'no response'})")

            # Continue to POI through path's forward exit
            path_exits = spoke.get("exits", {})
            poi_id = next((v for k, v in path_exits.items() if v != hub_loc_id), None)
            if poi_id:
                poi = loc_map.get(poi_id, {})
                log(f"    → POI: {poi.get('name','?')}", C)
                move(pid, poi_id)
                kills += _clear_location(pid, poi_id, zone_id)
                move(pid, spoke["id"])   # back to path

            # Back to hub
            move(pid, hub_loc_id)

        # ── DIRECT POI (old zone without paths) ────────────────────────────────
        else:
            log(f"  [{direction.upper()}] → POI: {spoke['name']}", C)
            move(pid, spoke["id"])
            kills += _clear_location(pid, spoke["id"], zone_id)
            move(pid, hub_loc_id)

    return kills


def _clear_location(pid: str, loc_id: str, zone_id: str) -> int:
    """Kill all alive mobs at a location and forage if a quest targets here."""
    kills = 0
    zone = fresh_zone(zone_id)
    loc_map = {l["id"]: l for l in zone.get("locations", [])}
    loc = loc_map.get(loc_id)
    if not loc:
        return 0

    # Kill every unique alive mob type here
    mobs = alive_mobs_at(loc)
    seen_names: set[str] = set()
    for mob in mobs:
        name = mob["name"]
        if name in seen_names:
            continue
        seen_names.add(name)
        label = ("⚑ " if mob.get("is_named") else "★ " if mob.get("is_elite") else "") + name
        log(f"    ⚔ Attacking {label}  lv{mob['level']}  HP {mob['hp']}/{mob['max_hp']}", Y)
        use_healing_potion_if_low(pid)
        result = kill_mob(pid, name)
        if result:
            kills += 1
            xp_g = result.get("xp_gained", 0)
            gold_g = result.get("gold_gained", 0)
            loot = result.get("loot_item")
            lvl = result.get("player_level", 0)
            msg = f"    Killed {name}  +{xp_g} XP  +{gold_g} gold"
            if loot:
                msg += f"  [{loot.get('rarity')} {loot.get('name')}]"
            log(msg, G)
            if result.get("leveled_up"):
                log(f"    ★★★ LEVEL UP → {lvl} ★★★", M)
            sync_kill_progress(pid, name, result, zone)
        else:
            log(f"    Could not kill {name} — skipping", Y)

        # Reload location in case mobs changed
        zone = fresh_zone(zone_id)
        loc_map = {l["id"]: l for l in zone.get("locations", [])}
        loc = loc_map.get(loc_id, loc)

    # Forage if a quest targets this location
    player = fresh_player(pid)
    forage_q = next(
        (q for q in player.get("active_quests", [])
         if q.get("quest_type") == "forage"
         and q.get("target_id") == loc_id
         and not q.get("is_completed")),
        None
    )
    if forage_q:
        remaining = forage_q["target_count"] - forage_q["current_progress"]
        log(f"    Foraging: {forage_q['title']}  ({forage_q['current_progress']}/{forage_q['target_count']})", C)
        for _ in range(remaining):
            r = req("post", f"/action/gather/{pid}")
            if r and r.status_code == 200:
                msgs = r.json().get("messages", [])
                for m in msgs:
                    log(f"      {m}", DIM)
                time.sleep(8.5)   # gather cooldown
            elif r and r.status_code == 429:
                time.sleep(8.5)
            else:
                log(f"      Gather failed: {r.status_code if r else 'no response'}", R)
                break

    return kills


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

print(f"\n{M}{'═' * 64}{RST}")
print(f"{M}  SINGLE PLAYER AI MUD — Headless Simulation{RST}")
print(f"{M}  Target level: {TARGET_LEVEL}  |  Backend: {BASE}{RST}")
print(f"{M}{'═' * 64}{RST}")


# ── 1. Create character ───────────────────────────────────────────────────────
section("1. CREATE CHARACTER")
r = req("post", "/player/create", params={
    "name": args.name, "race": "Orc", "char_class": "Warrior", "pronouns": "They/Them"
})
if not r or r.status_code != 200:
    die("Could not create character. Is the backend running?")

data       = r.json()
pid        = data["player_id"]
player     = data["player"]
zone       = data["zone"]
zone_id    = player["current_zone_id"]
hub_loc_id = player["current_location_id"]
loc_map    = {l["id"]: l for l in zone["locations"]}
hub_loc    = loc_map.get(hub_loc_id, {})

log(f"Created {player['name']} (Orc Warrior)  id: {pid[:8]}…", G)
log(f"Zone: {zone['name']}  |  Hub: {hub_loc.get('name','?')}", C)
log(f"Locations: {len(zone['locations'])}  |  Quests: {len(zone['quests'])}", DIM)

# Login for rested XP
req("post", f"/action/login/{pid}")


# ── 2. Zone topology check ────────────────────────────────────────────────────
section("2. ZONE TOPOLOGY")
path_locs = [l for l in zone["locations"] if len(l.get("resources", [])) >= 2]
poi_locs  = [l for l in zone["locations"]
             if l["id"] != hub_loc_id
             and not l.get("resources")
             and not l.get("npcs")]

log(f"Hub:   {hub_loc.get('name','?')}", W)
log(f"Paths: {len(path_locs)}  — " + ", ".join(l["name"] for l in path_locs), C)
log(f"POIs:  {len(poi_locs)}   — " + ", ".join(l["name"] for l in poi_locs), Y)

if not path_locs:
    warn("No path locations found — world_generator path insertion may be broken")


# ── 3. Talk to NPCs at hub ────────────────────────────────────────────────────
section("3. TALK TO NPCS")
hub_npcs = hub_loc.get("npcs", [])
hub_vendor = next((n for n in hub_npcs if n["role"] == "vendor"), None)
quest_givers = [n for n in hub_npcs if n["role"] == "quest_giver"]

for npc in hub_npcs:
    r = req("post", f"/action/talk/{pid}", params={"npc_name": npc["name"]})
    if r and r.status_code == 200:
        td = r.json()
        log(f"  Talked to {npc['name']} ({npc['role']})", G)
        if td.get("dialogue"):
            log(f"    \"{td['dialogue'][:80]}…\"", DIM)
        offered = td.get("offered_quests", [])
        if offered:
            log(f"    Offers {len(offered)} quest(s)", DIM)
    else:
        warn(f"Talk to {npc['name']} failed ({r.status_code if r else 'no response'})")


# ── 4. Accept all quests ──────────────────────────────────────────────────────
section("4. ACCEPT QUESTS")
zone = fresh_zone(zone_id)
n_accepted = accept_all_quests(pid, zone)
log(f"Accepted {n_accepted} quest(s)", G if n_accepted else Y)
p = fresh_player(pid)
for q in p.get("active_quests", []):
    log(f"  [{q['quest_type']:7}] {q['title']}  ({q['current_progress']}/{q['target_count']})", DIM)


# ── 5. Buy healing potion ─────────────────────────────────────────────────────
section("5. VENDOR — BUY POTION")
if hub_vendor:
    bought = buy_healing_potion(pid, hub_vendor["name"])
    if not bought:
        log("No potion bought (not affordable yet or already have one)", DIM)
else:
    log("No vendor at hub — skipping", DIM)


# ── 6. Grind loop ─────────────────────────────────────────────────────────────
section(f"6. GRIND TO LEVEL {TARGET_LEVEL}")

sweep = 0
respawn_waits = 0

while True:
    p = fresh_player(pid)
    level = p.get("level", 1)
    xp    = p.get("xp", 0)
    nxp   = p.get("next_level_xp", 100)
    gold  = p.get("gold", 0)
    hp    = p.get("hp", 0)
    mhp   = p.get("max_hp", 1)
    log(f"── Sweep {sweep + 1}  Lv{level}  XP {xp}/{nxp}  HP {hp}/{mhp}  Gold {gold}", C)

    if level >= TARGET_LEVEL:
        log(f"Reached target level {TARGET_LEVEL}!", G)
        break

    kills = do_zone_sweep(pid, zone_id, hub_loc_id, hub_vendor["name"] if hub_vendor else None)
    sweep += 1

    # Back at hub — turn in, sell, rebuy potion
    move(pid, hub_loc_id)
    turned = turn_in_all_quests(pid)
    if turned:
        zone = fresh_zone(zone_id)
        accept_all_quests(pid, zone)

    if hub_vendor:
        sell_junk(pid)
        buy_healing_potion(pid, hub_vendor["name"])

    if kills == 0:
        respawn_waits += 1
        log(f"  No kills this sweep — waiting 15s for respawns ({respawn_waits}/6)…", DIM)
        time.sleep(15)
        if respawn_waits >= 6:
            warn("Stuck — too many empty sweeps. Mobs may not be respawning.")
            break
    else:
        respawn_waits = 0

    if sweep > 40:
        warn(f"Hit sweep limit (40) at level {level} — stopping grind")
        break


# ── Back to hub, final turn-in ────────────────────────────────────────────────
move(pid, hub_loc_id)
turn_in_all_quests(pid)
if hub_vendor:
    sell_junk(pid)


# ── 7. Dungeon run ────────────────────────────────────────────────────────────
section("7. DUNGEON RUN")
p = fresh_player(pid)
log(f"Entering as Lv{p['level']}…", C)

r = req("post", f"/dungeon/enter/{pid}", params={"is_raid": "false"})
if not r or r.status_code != 200:
    body = {}
    if r:
        try:
            body = r.json()
        except Exception:
            pass
    detail = body.get("detail", (r.text if r else "no response")[:100])
    warn(f"Dungeon entry failed ({r.status_code if r else '?'}): {detail}")
else:
    run    = r.json()
    run_id = run["id"]
    log(f"Entered: {run['dungeon_name']}  (lv{run['dungeon_level']})", G)
    log(f"Party: " + ", ".join(f"{m['name']} [{m['role']}]" for m in run["party"]), DIM)

    while run.get("status") == "active":
        room_idx  = run["room_index"]
        room      = run["rooms"][room_idx]
        total_rooms = 5 if run.get("is_raid") else 3
        alive_ct  = sum(1 for m in room.get("mobs", []) if m.get("hp", 0) > 0)
        log(f"  Room {room_idx + 1}/{total_rooms}: {room['name']}  ({alive_ct} alive)", Y)

        cleared = False
        for _ in range(60):
            r2 = req("post", f"/dungeon/attack/{run_id}", params={"player_id": pid})
            if not r2 or r2.status_code != 200:
                warn(f"Dungeon attack failed ({r2.status_code if r2 else '?'})")
                break
            rd  = r2.json()
            run = rd["run"]

            for line in rd.get("round_log", []):
                log(f"    {line}", DIM)

            if rd.get("wiped"):
                warn("Party wiped in dungeon")
                cleared = True
                break

            if rd.get("run_cleared"):
                log("  ★ Dungeon cleared!", G)
                loot = rd.get("loot", [])
                if loot:
                    for item in loot:
                        log(f"    Loot: [{item.get('rarity')}] {item.get('name')} "
                            f"({item.get('slot')})", M)
                else:
                    warn("Dungeon cleared but no loot returned")
                cleared = True
                break

            if rd.get("room_cleared"):
                log(f"  Room {room_idx + 1} cleared!", G)
                r3 = req("post", f"/dungeon/advance/{run_id}", params={"player_id": pid})
                if r3 and r3.status_code == 200:
                    run = r3.json()["run"]
                cleared = True
                break

            time.sleep(0.05)

        if not cleared:
            warn(f"Room {room_idx + 1} didn't clear after 60 rounds")
            break

        if run.get("status") != "active":
            break


# ── 8. Sell dungeon loot, zone travel ─────────────────────────────────────────
move(pid, hub_loc_id)
if hub_vendor:
    sell_junk(pid)

section("8. ZONE TRAVEL ATTEMPT")
p = fresh_player(pid)
log(f"Lv{p['level']}  Dungeons cleared: {p.get('dungeons_cleared',0)}  Gold: {p.get('gold',0)}", C)

r = req("post", f"/zone/travel/{pid}")
if r and r.status_code == 200:
    new_zone = r.json().get("zone", {})
    log(f"★ Zone travel succeeded! → {new_zone.get('name','?')}", G)
elif r:
    try:
        detail = r.json().get("detail", r.text[:100])
    except Exception:
        detail = r.text[:100]
    log(f"Zone travel blocked (expected if GS gate not met): {detail}", Y)
else:
    warn("Zone travel request failed entirely")


# ── 9. Final state ────────────────────────────────────────────────────────────
section("9. FINAL CHARACTER STATE")
p = fresh_player(pid)
log(f"Name:     {p['name']}", W)
log(f"Level:    {p['level']}", W)
log(f"HP:       {p['hp']}/{p['max_hp']}", W)
log(f"XP:       {p['xp']}/{p['next_level_xp']}", W)
log(f"Gold:     {p['gold']}", W)
log(f"Kills:    {p['kills']}", W)
log(f"Deaths:   {p['deaths']}", W)
log(f"Dungeons: {p.get('dungeons_cleared',0)}", W)
log(f"Quests completed: {len(p.get('completed_quest_ids',[]))}", W)

equip = p.get("equipment", {})
log("Equipment:", W)
for slot, item in equip.items():
    if item.get("name") and item["name"] != "None":
        stats = ", ".join(f"{k}+{v}" for k, v in item.get("stats", {}).items())
        log(f"  {slot:10} {item['name']:30} [{item.get('rarity','?')}]  {stats}", DIM)

inv = p.get("inventory", [])
log(f"Inventory: {len(inv)} item(s)", W)
for item in inv:
    log(f"  {item.get('name','?'):30} [{item.get('rarity','?')}]  slot={item.get('slot','?')}", DIM)


# ── Cleanup ───────────────────────────────────────────────────────────────────
if not args.no_cleanup:
    section("CLEANUP")
    r = req("delete", f"/player/{pid}")
    if r and r.status_code == 200:
        log(f"Deleted {args.name}", G)
    else:
        warn(f"Delete failed: {r.status_code if r else 'no response'}")
else:
    section("KEEPING CHARACTER")
    log(f"'{args.name}'  player_id: {pid}", Y)
    log("Run 'python scripts/reset_data.py' to wipe when done.", DIM)


# ── Summary ───────────────────────────────────────────────────────────────────
total = time.time() - _sim_start
print(f"\n{M}{'═' * 64}{RST}")
print(f"{M}  Total time: {total:.1f}s ({total/60:.1f} min){RST}")
if errors:
    print(f"{R}  {len(errors)} issue(s) during simulation:{RST}")
    for e in errors:
        print(f"{R}    - {e}{RST}")
    print(f"{M}{'═' * 64}{RST}\n")
    sys.exit(1)
else:
    print(f"{G}  Simulation completed without errors.{RST}")
    print(f"{M}{'═' * 64}{RST}\n")
    sys.exit(0)
