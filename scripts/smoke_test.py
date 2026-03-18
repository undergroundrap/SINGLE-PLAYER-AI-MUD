"""
smoke_test.py — Happy-path integration test for the MUD backend.

Usage (run from repo root with backend already running):
    python scripts/smoke_test.py
    python scripts/smoke_test.py --base http://localhost:8001

Exits 0 on all checks passing, 1 on any failure.
"""

import sys
import time
import argparse

# ── CLI args (must parse BEFORE any test code runs) ───────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://localhost:8000", help="Backend base URL")
args = parser.parse_args()

try:
    import requests
except ImportError:
    print("requests not installed — run: pip install requests")
    sys.exit(1)

BASE = args.base

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m·\033[0m"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}{(' — ' + detail) if detail else ''}")
        failures.append(label)


def req(method: str, path: str, **kwargs):
    url = BASE + path
    try:
        r = getattr(requests, method)(url, timeout=15, **kwargs)
        return r
    except Exception as e:
        print(f"  {FAIL} REQUEST FAILED: {method.upper()} {path} — {e}")
        failures.append(path)
        return None


# ── 1. Create character ────────────────────────────────────────────────────────
print("\n[1] Create character")
r = req("post", "/player/create", params={
    "name": "SmokeTest", "race": "Human", "char_class": "Warrior", "pronouns": "They/Them"
})
check("POST /player/create returns 200", r and r.status_code == 200)
if not r or r.status_code != 200:
    print("Cannot continue without a player. Aborting.")
    sys.exit(1)

data = r.json()
player_id = data.get("player_id")
player = data.get("player")
zone = data.get("zone")

check("player_id present", bool(player_id))
check("player.name == SmokeTest", player.get("name") == "SmokeTest")
check("player.level == 1", player.get("level") == 1)
check("zone has locations", isinstance(zone.get("locations"), list) and len(zone["locations"]) > 0)
check("player has current_location_id", bool(player.get("current_location_id")))


# ── 2. Load zone ───────────────────────────────────────────────────────────────
print("\n[2] Load zone")
zone_id = player.get("current_zone_id")
r = req("get", f"/zone/{zone_id}")
check("GET /zone returns 200", r and r.status_code == 200)
z = r.json() if r else {}
check("zone has name", bool(z.get("name")))
check("zone has quests", isinstance(z.get("quests"), list))
check("zone has simulated_players", isinstance(z.get("simulated_players"), list))
check("zone has world_messages field", "world_messages" in z)
check("zone has time_of_day", "time_of_day" in z)
check("zone has weather", "weather" in z)


# ── 3. Zone topology — paths between hub and POIs ─────────────────────────────
print("\n[3] Zone topology")
locations = zone.get("locations", [])
loc_id = player["current_location_id"]
hub = next((l for l in locations if l["id"] == loc_id), None)

# Path locations should have resources = [plant, fish]
path_locations = [l for l in locations if l.get("resources") and len(l["resources"]) >= 2]
check("at least one path location with resources exists", len(path_locations) > 0,
      f"found {len(path_locations)} path locations")
if path_locations:
    pl = path_locations[0]
    check("path location has plant name", bool(pl["resources"][0]))
    check("path location has fish species", bool(pl["resources"][1]))

# Hub should have no resources
hub_resources = (hub or {}).get("resources", [])
check("hub location has no resources (not a path)", len(hub_resources) == 0)


# ── 4. Move — hub to path, then to POI ────────────────────────────────────────
print("\n[4] Move")
exits = hub.get("exits", {}) if hub else {}
path_loc = None
poi_loc = None

if exits:
    # First exit from hub goes to a path location
    direction = next(iter(exits))
    path_loc_id = exits[direction]
    r = req("post", f"/action/move/{player_id}", params={"location_id": path_loc_id})
    check("move hub → path returns 200", r and r.status_code == 200)
    mv = r.json() if r else {}
    check("move.success is True", mv.get("success") is True)
    check("player location updated", mv.get("player", {}).get("current_location_id") == path_loc_id)

    path_loc = next((l for l in locations if l["id"] == path_loc_id), None)
    check("arrived location is a path (has resources)", len((path_loc or {}).get("resources", [])) >= 2)

    # Follow path forward to a POI
    path_exits = (path_loc or {}).get("exits", {})
    poi_loc_id = next((v for k, v in path_exits.items() if v != loc_id), None)
    if poi_loc_id:
        r2 = req("post", f"/action/move/{player_id}", params={"location_id": poi_loc_id})
        check("move path → POI returns 200", r2 and r2.status_code == 200)
        poi_loc = next((l for l in locations if l["id"] == poi_loc_id), None)
        check("POI has no resources (not a path)", len((poi_loc or {}).get("resources", [])) == 0)
        # Move back to path
        req("post", f"/action/move/{player_id}", params={"location_id": path_loc_id})
    else:
        print(f"  {INFO} Path has no forward exit — skipping POI move")

    # Move back to hub
    r3 = req("post", f"/action/move/{player_id}", params={"location_id": loc_id})
    check("move back to hub succeeds", r3 and r3.status_code == 200)
else:
    print(f"  {INFO} Hub has no exits — skipping move tests")


# ── 5. Harvest & Fish (path location) ─────────────────────────────────────────
print("\n[5] Harvest & Fish")
if path_loc:
    path_loc_id = path_loc["id"]
    # Move to the path location first
    req("post", f"/action/move/{player_id}", params={"location_id": path_loc_id})

    r = req("post", f"/action/harvest/{player_id}")
    check("POST /action/harvest returns 200", r and r.status_code == 200)
    hd = r.json() if r else {}
    check("harvest returns an item", bool(hd.get("item")))
    if hd.get("item"):
        check("harvest item has slot=material", hd["item"].get("slot") == "material")
        check("harvest item name matches plant", path_loc["resources"][0].lower() in hd["item"].get("name", "").lower())

    # Cooldown — immediate second harvest should 429
    r2 = req("post", f"/action/harvest/{player_id}")
    check("immediate second harvest hits cooldown (429)", r2 and r2.status_code == 429)

    r3 = req("post", f"/action/fish/{player_id}")
    check("POST /action/fish returns 200", r3 and r3.status_code == 200)
    fd = r3.json() if r3 else {}
    check("fish returns an item", bool(fd.get("item")))
    if fd.get("item"):
        check("fish item has slot=material", fd["item"].get("slot") == "material")

    # Cooldown — immediate second fish should 429
    r4 = req("post", f"/action/fish/{player_id}")
    check("immediate second fish hits cooldown (429)", r4 and r4.status_code == 429)

    # Move back to hub
    req("post", f"/action/move/{player_id}", params={"location_id": loc_id})
else:
    print(f"  {INFO} No path location found — skipping harvest/fish tests")


# ── 6. Combat ─────────────────────────────────────────────────────────────────
print("\n[6] Combat")
# Reload zone to get fresh mob state
r = req("get", f"/zone/{zone_id}")
z2 = r.json() if r else {}
current_loc = next((l for l in z2.get("locations", []) if l["id"] == loc_id), None)
mob = next((m for m in (current_loc or {}).get("mobs", []) if not m.get("respawn_at")), None)

if not mob:
    # Find a POI with alive mobs
    for loc in z2.get("locations", []):
        mob = next((m for m in loc.get("mobs", []) if not m.get("respawn_at")), None)
        if mob:
            req("post", f"/action/move/{player_id}", params={"location_id": loc["id"]})
            break

if mob:
    mob_name = mob["name"]
    r = req("post", f"/action/attack/{player_id}", params={"mob_name": mob_name})
    check("POST /action/attack returns 200", r and r.status_code == 200)
    atk = r.json() if r else {}
    check("attack.messages is list", isinstance(atk.get("messages"), list))
    check("attack.player_hp present", "player_hp" in atk)
    check("attack.mob_hp present", "mob_hp" in atk)

    # Cooldown check
    r2 = req("post", f"/action/attack/{player_id}", params={"mob_name": mob_name})
    check("immediate second attack hits cooldown (429)", r2 and r2.status_code == 429)

    # Kill mob (up to 30 attempts with 2s waits)
    time.sleep(2)
    killed = False
    for _ in range(30):
        r3 = req("post", f"/action/attack/{player_id}", params={"mob_name": mob_name})
        a3 = r3.json() if r3 else {}
        if a3.get("mob_dead"):
            check("mob can be killed", True)
            check("xp awarded on kill", (a3.get("xp_gained") or 0) > 0)
            killed = True
            break
        time.sleep(2)
    if not killed:
        print(f"  {INFO} Mob still alive after 30 hits — may be high HP elite")
else:
    print(f"  {INFO} No alive mobs found in zone — skipping combat test")

# Move back to hub for subsequent tests
req("post", f"/action/move/{player_id}", params={"location_id": loc_id})


# ── 7. Patrol check ───────────────────────────────────────────────────────────
print("\n[7] Patrol check")
# Move to a POI to test (patrol doesn't fire at hub or on paths)
poi_for_patrol = next(
    (l for l in z2.get("locations", [])
     if l["id"] != loc_id and not l.get("resources") and not l.get("npcs")),
    None
)
if poi_for_patrol:
    req("post", f"/action/move/{player_id}", params={"location_id": poi_for_patrol["id"]})
    r = req("post", f"/action/patrol_check/{player_id}")
    check("POST /action/patrol_check returns 200", r and r.status_code == 200)
    pd = r.json() if r else {}
    check("patrol response has 'patrol' key", "patrol" in pd)
    if pd.get("patrol"):
        check("patrol mob_name present", bool(pd.get("mob_name")))
    # Move back
    req("post", f"/action/move/{player_id}", params={"location_id": loc_id})
else:
    print(f"  {INFO} No suitable POI for patrol test — skipping")


# ── 8. Login / Logout (rested XP) ─────────────────────────────────────────────
print("\n[8] Login / Logout (rested XP)")
r = req("post", f"/action/logout/{player_id}")
check("POST /action/logout returns 200", r and r.status_code == 200)

r = req("post", f"/action/login/{player_id}")
check("POST /action/login returns 200", r and r.status_code == 200)
lid = r.json() if r else {}
check("login response has rested_xp", "rested_xp" in lid)
check("login response has rested_xp_cap", "rested_xp_cap" in lid)


# ── 9. Player list & load ──────────────────────────────────────────────────────
print("\n[9] Player list & load")
r = req("get", "/players")
check("GET /players returns 200", r and r.status_code == 200)
pl = r.json() if r else {}
check("players list contains our character", any(p.get("player_id") == player_id for p in pl.get("players", [])))
p_entry = next((p for p in pl.get("players", []) if p.get("player_id") == player_id), {})
check("player list entry has gear_score", "gear_score" in p_entry)

r = req("get", f"/player/{player_id}")
check("GET /player returns 200", r and r.status_code == 200)
ld = r.json() if r else {}
check("loaded player name matches", ld.get("player", {}).get("name") == "SmokeTest")
check("load response has gear_score", "gear_score" in ld)


# ── 10. Talk to NPC ────────────────────────────────────────────────────────────
print("\n[10] NPC talk")
# Hub NPCs
r = req("get", f"/zone/{zone_id}")
z3 = r.json() if r else {}
hub_loc = next((l for l in z3.get("locations", []) if l["id"] == loc_id), None)
npcs = (hub_loc or {}).get("npcs", [])
quest_giver = next((n for n in npcs if n.get("role") == "quest_giver"), None)
vendor = next((n for n in npcs if n.get("role") == "vendor"), None)

if quest_giver:
    r = req("post", f"/action/talk/{player_id}", params={"npc_name": quest_giver["name"]})
    check("POST /action/talk (quest giver) returns 200", r and r.status_code == 200)
    td = r.json() if r else {}
    check("talk.success is True", td.get("success") is True)
    check("dialogue string returned", bool(td.get("dialogue")))
    check("offered_quests is list", isinstance(td.get("offered_quests"), list))
else:
    print(f"  {INFO} No quest giver at hub — skipping NPC talk test")


# ── 11. Quest accept ───────────────────────────────────────────────────────────
print("\n[11] Quest accept")
quests = z3.get("quests", [])
accepted_quest = None
if quests:
    q = quests[0]
    r = req("post", f"/quests/accept/{player_id}", params={"quest_id": q["id"]})
    check("POST /quests/accept returns 200", r and r.status_code == 200)
    qa = r.json() if r else {}
    check("quest accepted successfully", qa.get("success") is True)
    accepted_quest = q
else:
    print(f"  {INFO} No quests in zone — skipping quest accept")


# ── 12. Vendor ─────────────────────────────────────────────────────────────────
print("\n[12] Vendor")
if vendor:
    r = req("get", f"/vendor/{player_id}", params={"npc_name": vendor["name"]})
    check("GET /vendor returns 200", r and r.status_code == 200)
    vd = r.json() if r else {}
    check("vendor stock is list", isinstance(vd.get("stock"), list))
    check("vendor gold present", "gold" in vd)
else:
    print(f"  {INFO} No vendor at hub — skipping vendor test")


# ── 13. Sell material items ────────────────────────────────────────────────────
print("\n[13] Sell Junk (material items)")
if vendor:
    r = req("post", f"/vendor/sell_junk/{player_id}")
    check("POST /vendor/sell_junk returns 200", r and r.status_code == 200)
    sj = r.json() if r else {}
    check("sell_junk has gold_gained", "gold_gained" in sj)
    check("sell_junk has sold_count", "sold_count" in sj)
else:
    print(f"  {INFO} No vendor at hub — skipping sell junk test")


# ── 14. Dungeon gate (level 1 → blocked) ─────────────────────────────────────
print("\n[14] Dungeon gate")
r = req("post", f"/dungeon/enter/{player_id}", params={"is_raid": "false"})
check("dungeon entry blocked at level 1 (non-200)", r and r.status_code != 200,
      f"got {r.status_code if r else 'no response'}")


# ── 15. Zone travel gate (low GS → blocked) ──────────────────────────────────
print("\n[15] Zone travel gate")
r = req("post", f"/zone/travel/{player_id}")
check("zone travel blocked at low GS (non-200)", r and r.status_code != 200,
      f"got {r.status_code if r else 'no response'}")


# ── 16. Describe endpoints ─────────────────────────────────────────────────────
print("\n[16] Describe endpoints")
r = req("get", "/describe/location", params={
    "name": "Test Grove", "loc_description": "A quiet clearing.", "zone": "Testland"
})
check("GET /describe/location returns 200", r and r.status_code == 200)
check("description string returned", bool((r.json() if r else {}).get("description")))

r = req("get", "/describe/entity", params={
    "name": "Goblin", "entity_type": "creature",
    "is_elite": "false", "is_named": "false", "zone": "Testland"
})
check("GET /describe/entity returns 200", r and r.status_code == 200)
check("entity description returned", bool((r.json() if r else {}).get("description")))


# ── 17. Cleanup ────────────────────────────────────────────────────────────────
print("\n[17] Cleanup")
r = req("delete", f"/player/{player_id}")
check("DELETE /player returns 200", r and r.status_code == 200)
r2 = req("get", f"/player/{player_id}")
check("player no longer loadable after delete (404)", r2 and r2.status_code == 404)


# ── Summary ────────────────────────────────────────────────────────────────────
print()
if failures:
    print(f"\033[91m{len(failures)} check(s) failed:\033[0m")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print(f"\033[92mAll checks passed.\033[0m")
    sys.exit(0)
