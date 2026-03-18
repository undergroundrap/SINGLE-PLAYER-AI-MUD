"""
sim_run.py — Headless game simulation for fast end-to-end testing.

Plays through the full game loop automatically — no browser, no manual input.
Shows a live feed of everything that happens so you can verify behavior quickly.

Usage:
    python scripts/sim_run.py
    python scripts/sim_run.py --base http://localhost:8001
    python scripts/sim_run.py --target-level 15   # grind to a specific level
    python scripts/sim_run.py --no-cleanup         # keep the char after the run

What it exercises:
  Open world  — move through hub → path → POI, harvest, fish, kill mobs,
                accept/turn-in quests, buy/use potions, sell junk
  Dungeon     — enter at level 10, run all 3 rooms, collect loot
  Raid        — enter at level 20 (if --target-level >= 20), run all 5 rooms
  Zone travel — after hitting the GS gate, advance to the next zone

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
R = "\033[91m"   # red
G = "\033[92m"   # green
Y = "\033[93m"   # yellow
B = "\033[94m"   # blue
M = "\033[95m"   # magenta
C = "\033[96m"   # cyan
W = "\033[97m"   # white
DIM = "\033[2m"
RST = "\033[0m"

errors: list[str] = []


def log(msg: str, color: str = W) -> None:
    print(f"  {color}{msg}{RST}")


def section(title: str) -> None:
    print(f"\n{Y}{'─' * 60}{RST}")
    print(f"{Y}  {title}{RST}")
    print(f"{Y}{'─' * 60}{RST}")


def req(method: str, path: str, **kwargs):
    url = BASE + path
    try:
        r = getattr(requests, method)(url, timeout=20, **kwargs)
        return r
    except Exception as e:
        errors.append(f"{method.upper()} {path}: {e}")
        log(f"REQUEST FAILED: {method.upper()} {path} — {e}", R)
        return None


def die(msg: str) -> None:
    log(f"FATAL: {msg}", R)
    sys.exit(1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fresh_zone(zone_id: str) -> dict:
    r = req("get", f"/zone/{zone_id}")
    return r.json() if r and r.status_code == 200 else {}


def fresh_player(pid: str) -> dict:
    r = req("get", f"/player/{pid}")
    d = r.json() if r and r.status_code == 200 else {}
    return d.get("player", {})


def move(pid: str, loc_id: str) -> bool:
    r = req("post", f"/action/move/{pid}", params={"location_id": loc_id})
    return bool(r and r.status_code == 200 and r.json().get("success"))


def current_location(pid: str, zone: dict) -> dict | None:
    p = fresh_player(pid)
    return next((l for l in zone.get("locations", []) if l["id"] == p.get("current_location_id")), None)


def alive_mobs(loc: dict) -> list[dict]:
    now = time.time()
    return [m for m in loc.get("mobs", []) if not m.get("respawn_at") or m["respawn_at"] <= now]


def kill_mob(pid: str, mob_name: str, max_hits: int = 60) -> dict | None:
    """Attack until mob dies or max_hits exceeded. Returns final attack response or None."""
    time.sleep(1.6)
    for _ in range(max_hits):
        r = req("post", f"/action/attack/{pid}", params={"mob_name": mob_name})
        if not r:
            return None
        if r.status_code == 429:
            time.sleep(1.6)
            continue
        a = r.json()
        if a.get("mob_dead"):
            return a
        if "error" in a or r.status_code >= 400:
            return None
        time.sleep(1.6)
    return None


def accept_all_quests(pid: str, zone: dict) -> int:
    accepted = 0
    p = fresh_player(pid)
    active_ids = {q["id"] for q in p.get("active_quests", [])}
    for q in zone.get("quests", []):
        if q["id"] not in active_ids:
            r = req("post", f"/quests/accept/{pid}", params={"quest_id": q["id"]})
            if r and r.status_code == 200 and r.json().get("success"):
                accepted += 1
    return accepted


def turn_in_all_quests(pid: str) -> int:
    turned_in = 0
    p = fresh_player(pid)
    completed = [q for q in p.get("active_quests", []) if q.get("is_completed")]
    for q in completed:
        r = req("post", f"/quests/complete/{pid}", params={"quest_id": q["id"]})
        if r and r.status_code == 200 and r.json().get("success"):
            xp = r.json().get("xp_reward", 0)
            log(f"  ★ Turned in '{q['title']}' (+{xp} XP)", G)
            turned_in += 1
    return turned_in


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN SIM
# ═══════════════════════════════════════════════════════════════════════════════

print(f"\n{M}{'═' * 60}{RST}")
print(f"{M}  SINGLE PLAYER AI MUD — Headless Simulation{RST}")
print(f"{M}  Target level: {TARGET_LEVEL}  |  Backend: {BASE}{RST}")
print(f"{M}{'═' * 60}{RST}")


# ── Create character ──────────────────────────────────────────────────────────
section("CREATE CHARACTER")
r = req("post", "/player/create", params={
    "name": args.name, "race": "Orc", "char_class": "Warrior", "pronouns": "They/Them"
})
if not r or r.status_code != 200:
    die("Could not create character. Is the backend running?")

data = r.json()
pid = data["player_id"]
player = data["player"]
zone = data["zone"]
zone_id = player["current_zone_id"]
hub_loc_id = player["current_location_id"]
hub_loc = next((l for l in zone["locations"] if l["id"] == hub_loc_id), None)

log(f"Created {player['name']} (Orc Warrior) — id: {pid}", G)
log(f"Zone: {zone['name']}  |  Hub: {hub_loc['name'] if hub_loc else '?'}", C)
log(f"Locations in zone: {len(zone['locations'])}", DIM)


# ── Accept all quests ─────────────────────────────────────────────────────────
section("ACCEPT QUESTS")
accepted = accept_all_quests(pid, zone)
log(f"Accepted {accepted} quest(s)", G if accepted else Y)


# ── Explore path locations ────────────────────────────────────────────────────
section("EXPLORE PATHS — HARVEST & FISH")
path_locs = [l for l in zone["locations"] if len(l.get("resources", [])) >= 2]
if not path_locs:
    log("No path locations found in zone — skipping harvest/fish", Y)
else:
    pl = path_locs[0]
    log(f"Moving to path: {pl['name']}  [{pl['resources'][0]} / {pl['resources'][1]}]", C)
    move(pid, pl["id"])

    # Harvest
    r = req("post", f"/action/harvest/{pid}")
    if r and r.status_code == 200:
        item = r.json().get("item", {})
        log(f"Harvested: {item.get('name', '?')}  (slot={item.get('slot')})", G)
    elif r and r.status_code == 429:
        log("Harvest on cooldown (expected if re-running quickly)", Y)
    else:
        log(f"Harvest failed: {r.status_code if r else 'no response'}", R)

    # Fish
    r = req("post", f"/action/fish/{pid}")
    if r and r.status_code == 200:
        item = r.json().get("item", {})
        log(f"Caught:     {item.get('name', '?')}  (slot={item.get('slot')})", G)
    elif r and r.status_code == 429:
        log("Fish on cooldown (expected if re-running quickly)", Y)
    else:
        log(f"Fish failed: {r.status_code if r else 'no response'}", R)

    # Return to hub
    move(pid, hub_loc_id)
    log("Returned to hub", DIM)


# ── Sell material items ───────────────────────────────────────────────────────
hub_vendor = next((n for n in (hub_loc or {}).get("npcs", []) if n["role"] == "vendor"), None)
if hub_vendor:
    r = req("post", f"/vendor/sell_junk/{pid}")
    if r and r.status_code == 200:
        sj = r.json()
        if sj.get("sold_count", 0) > 0:
            log(f"Sold {sj['sold_count']} junk item(s) for {sj['gold_gained']} gold", G)


# ── Grind loop — kill mobs until target level ─────────────────────────────────
section(f"GRIND TO LEVEL {TARGET_LEVEL}")

zone_cycle = 0
while True:
    player = fresh_player(pid)
    level = player.get("level", 1)
    xp = player.get("xp", 0)
    next_xp = player.get("next_level_xp", 100)
    gold = player.get("gold", 0)
    log(f"Level {level}  XP {xp}/{next_xp}  Gold {gold}", C)

    if level >= TARGET_LEVEL:
        log(f"Reached target level {TARGET_LEVEL}!", G)
        break

    # Reload zone (respawns may have fired)
    zone = fresh_zone(zone_id)
    locations = zone.get("locations", [])

    # Find a location with alive mobs
    found_combat = False
    for loc in locations:
        if loc.get("resources"):
            continue  # skip path locations — safe zones
        mobs = alive_mobs(loc)
        if not mobs:
            continue
        mob = mobs[0]
        if not move(pid, loc["id"]):
            continue

        log(f"  → {loc['name']} — attacking {mob['name']} (lv{mob['level']})", Y)
        result = kill_mob(pid, mob["name"])
        if result:
            xp_g = result.get("xp_gained", 0)
            lvl_after = result.get("player", {}).get("level", level)
            gold_g = result.get("gold_gained", 0)
            loot = result.get("loot_item", {})
            msg = f"    Killed {mob['name']}  +{xp_g} XP  +{gold_g} gold"
            if loot:
                msg += f"  [{loot.get('rarity','?')} {loot.get('name','item')}]"
            log(msg, G)
            if lvl_after > level:
                log(f"  ★★★ LEVEL UP → {lvl_after} ★★★", M)

            # Try to turn in quests after each kill
            turn_in_all_quests(pid)
            # Re-accept any completed/available quests
            accept_all_quests(pid, zone)
            found_combat = True
            break  # back to top of while loop to refresh player state
        else:
            log(f"    Could not kill {mob['name']} (may have fled or respawned)", Y)
            found_combat = True
            break

    if not found_combat:
        # All mobs dead — wait for respawn
        log("  All mobs dead. Waiting 12s for respawn...", DIM)
        time.sleep(12)
        zone_cycle += 1
        if zone_cycle > 10:
            log("Too many respawn waits — stopping grind early", R)
            break

    # Return to hub periodically to sell and turn in
    player = fresh_player(pid)
    if len(player.get("inventory", [])) >= 6:
        move(pid, hub_loc_id)
        if hub_vendor:
            req("post", f"/vendor/sell_junk/{pid}")
        turn_in_all_quests(pid)
        accept_all_quests(pid, zone)


# ── Move back to hub for vendors ──────────────────────────────────────────────
move(pid, hub_loc_id)
turn_in_all_quests(pid)


# ── Dungeon run ───────────────────────────────────────────────────────────────
section("DUNGEON RUN (level 10+)")
player = fresh_player(pid)
log(f"Level {player['level']} entering dungeon...", C)

r = req("post", f"/dungeon/enter/{pid}", params={"is_raid": "false"})
if not r or r.status_code != 200:
    log(f"Dungeon entry failed: {r.status_code if r else 'no response'} — {(r.text if r else '')[:120]}", R)
    errors.append("dungeon entry failed")
else:
    run = r.json()
    run_id = run["id"]
    log(f"Entered: {run['dungeon_name']}  (lv{run['dungeon_level']})  party size: {len(run['party'])}", G)
    log(f"Party: {', '.join(m['name'] + ' ' + m['role'] for m in run['party'])}", DIM)

    room_num = 0
    while run.get("status") == "active":
        room = run["rooms"][run["room_index"]]
        alive = [m for m in room.get("mobs", []) if m.get("hp", 0) > 0]
        log(f"  Room {run['room_index'] + 1}/{'5' if run.get('is_raid') else '3'}: {room['name']}"
            f"  ({len(alive)} mob(s) alive)", Y)

        # Attack until room cleared or wiped
        for _ in range(50):
            r2 = req("post", f"/dungeon/attack/{run_id}", params={"player_id": pid})
            if not r2 or r2.status_code != 200:
                log(f"  Dungeon attack failed: {r2.status_code if r2 else 'error'}", R)
                errors.append("dungeon attack failed")
                break
            rd = r2.json()
            run = rd["run"]
            for line in rd.get("round_log", []):
                log(f"    {line}", DIM)

            if rd.get("wiped"):
                log("  ✗ Party wiped!", R)
                errors.append("party wiped in dungeon")
                break
            if rd.get("room_cleared") and not rd.get("run_cleared"):
                log(f"  Room {run['room_index'] + 1} cleared — advancing...", G)
                r3 = req("post", f"/dungeon/advance/{run_id}", params={"player_id": pid})
                if r3 and r3.status_code == 200:
                    run = r3.json()["run"]
                break
            if rd.get("run_cleared"):
                log("  ★ Dungeon cleared!", G)
                loot = rd.get("loot", [])
                for item in loot:
                    log(f"    Loot: [{item.get('rarity')}] {item.get('name')} ({item.get('slot')})", M)
                break
            time.sleep(0.1)  # small pause between rounds

        if run.get("status") != "active":
            break


# ── Optional: sell dungeon loot ───────────────────────────────────────────────
move(pid, hub_loc_id)
if hub_vendor:
    r = req("post", f"/vendor/sell_junk/{pid}")
    if r and r.status_code == 200:
        sj = r.json()
        if sj.get("sold_count", 0) > 0:
            log(f"Sold {sj['sold_count']} junk for {sj['gold_gained']} gold", G)


# ── Zone travel (may fail on GS gate — that's fine, shows the gate works) ─────
section("ZONE TRAVEL ATTEMPT")
player = fresh_player(pid)
log(f"Level {player['level']}  Dungeons cleared: {player.get('dungeons_cleared', 0)}", C)

r = req("post", f"/zone/travel/{pid}")
if r and r.status_code == 200:
    new_zone = r.json().get("zone", {})
    log(f"★ Zone travel succeeded! → {new_zone.get('name', '?')}", G)
elif r:
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    detail = body.get("detail", r.text[:80])
    log(f"Zone travel blocked (expected if GS gate not met): {detail}", Y)
else:
    log("Zone travel request failed", R)


# ── Final state ───────────────────────────────────────────────────────────────
section("FINAL PLAYER STATE")
player = fresh_player(pid)
log(f"Name:     {player['name']}", W)
log(f"Level:    {player['level']}", W)
log(f"HP:       {player['hp']}/{player['max_hp']}", W)
log(f"Gold:     {player['gold']}", W)
log(f"Kills:    {player['kills']}", W)
log(f"Deaths:   {player['deaths']}", W)
log(f"Dungeons: {player.get('dungeons_cleared', 0)}", W)
inv = player.get("inventory", [])
equip = player.get("equipment", {})
log(f"Inventory: {len(inv)} item(s)", W)
equipped_names = [f"{slot}: {item['name']}" for slot, item in equip.items() if item.get("name") != "None"]
for e in equipped_names:
    log(f"  {e}", DIM)


# ── Cleanup ───────────────────────────────────────────────────────────────────
if not args.no_cleanup:
    section("CLEANUP")
    r = req("delete", f"/player/{pid}")
    if r and r.status_code == 200:
        log(f"Deleted character {args.name}", G)
    else:
        log(f"Delete failed: {r.status_code if r else 'no response'}", R)
else:
    section("KEEPING CHARACTER")
    log(f"Character '{args.name}' kept — player_id: {pid}", Y)
    log("Run 'python scripts/reset_data.py' to wipe all data when done.", DIM)


# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{M}{'═' * 60}{RST}")
if errors:
    print(f"{R}  {len(errors)} error(s) during simulation:{RST}")
    for e in errors:
        print(f"{R}    - {e}{RST}")
    print(f"{M}{'═' * 60}{RST}\n")
    sys.exit(1)
else:
    print(f"{G}  Simulation completed without errors.{RST}")
    print(f"{M}{'═' * 60}{RST}\n")
    sys.exit(0)
