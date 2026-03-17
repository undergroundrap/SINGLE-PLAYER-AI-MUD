"""
smoke_test.py — Happy-path integration test for the MUD backend.

Usage (from repo root, backend NOT required to be running separately):
    cd backend && .\\venv\\Scripts\\activate && uvicorn main:app --port 8001 &
    python scripts/smoke_test.py

Or against a running server:
    python scripts/smoke_test.py --base http://localhost:8000

Exits 0 on pass, 1 on any failure.
"""

import sys
import time
import argparse
import requests

BASE = "http://localhost:8000"

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m·\033[0m"

failures = []

def check(label: str, condition: bool, detail: str = ""):
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


# ── 3. Move to a location ──────────────────────────────────────────────────────
print("\n[3] Move")
loc_id = player["current_location_id"]
hub = next((l for l in zone["locations"] if l["id"] == loc_id), None)
exits = hub.get("exits", {}) if hub else {}

if exits:
    direction = next(iter(exits))
    target_loc_id = exits[direction]
    r = req("post", f"/action/move/{player_id}", params={"location_id": target_loc_id})
    check("POST /action/move returns 200", r and r.status_code == 200)
    mv = r.json() if r else {}
    check("move.success is True", mv.get("success") is True)
    check("player location updated", mv.get("player", {}).get("current_location_id") == target_loc_id)
    # Move back
    r2 = req("post", f"/action/move/{player_id}", params={"location_id": loc_id})
    check("move back succeeds", r2 and r2.status_code == 200)
else:
    print(f"  {INFO} Hub has no exits — skipping move test")


# ── 4. Attack a mob ────────────────────────────────────────────────────────────
print("\n[4] Combat")
# Find a mob at current location
r = req("get", f"/zone/{zone_id}")
z2 = r.json() if r else {}
current_loc = next((l for l in z2.get("locations", []) if l["id"] == loc_id), None)
mob = next((m for m in (current_loc or {}).get("mobs", []) if not m.get("respawn_at")), None)

if mob:
    mob_name = mob["name"]
    r = req("post", f"/action/attack/{player_id}", params={"mob_name": mob_name})
    check("POST /action/attack returns 200", r and r.status_code == 200)
    atk = r.json() if r else {}
    check("attack.messages is list", isinstance(atk.get("messages"), list))
    check("attack.player_hp present", "player_hp" in atk)
    check("attack.mob_hp present", "mob_hp" in atk)

    # Attack cooldown
    r2 = req("post", f"/action/attack/{player_id}", params={"mob_name": mob_name})
    check("second immediate attack hits cooldown (429)", r2 and r2.status_code == 429)

    # Wait for cooldown and kill mob if not dead
    time.sleep(2)
    for _ in range(30):
        r3 = req("post", f"/action/attack/{player_id}", params={"mob_name": mob_name})
        a3 = r3.json() if r3 else {}
        if a3.get("mob_dead"):
            check("mob can be killed", True)
            check("xp awarded on kill", (a3.get("xp_gained") or 0) > 0)
            break
        time.sleep(2)
    else:
        print(f"  {INFO} Mob still alive after 30 hits — may be high HP elite")
else:
    print(f"  {INFO} No alive mobs at hub — skipping combat test")


# ── 5. Load player list ────────────────────────────────────────────────────────
print("\n[5] Player list")
r = req("get", "/players")
check("GET /players returns 200", r and r.status_code == 200)
pl = r.json() if r else {}
check("players list contains our character", any(p.get("player_id") == player_id for p in pl.get("players", [])))


# ── 6. Load specific player ────────────────────────────────────────────────────
print("\n[6] Load player")
r = req("get", f"/player/{player_id}")
check("GET /player returns 200", r and r.status_code == 200)
ld = r.json() if r else {}
check("loaded player name matches", ld.get("player", {}).get("name") == "SmokeTest")


# ── 7. Talk to NPC ─────────────────────────────────────────────────────────────
print("\n[7] NPC talk")
npcs = (current_loc or {}).get("npcs", [])
quest_giver = next((n for n in npcs if n.get("role") == "quest_giver"), None)
if quest_giver:
    r = req("post", f"/action/talk/{player_id}", params={"npc_name": quest_giver["name"]})
    check("POST /action/talk returns 200", r and r.status_code == 200)
    td = r.json() if r else {}
    check("talk.success is True", td.get("success") is True)
    check("dialogue string returned", bool(td.get("dialogue")))
else:
    print(f"  {INFO} No quest giver at hub — skipping NPC talk test")


# ── 8. Quest accept ────────────────────────────────────────────────────────────
print("\n[8] Quest accept")
quests = z2.get("quests", [])
if quests:
    q = quests[0]
    r = req("post", f"/quests/accept/{player_id}", params={"quest_id": q["id"]})
    check("POST /quests/accept returns 200", r and r.status_code == 200)
    qa = r.json() if r else {}
    check("quest accepted successfully", qa.get("success") is True)
else:
    print(f"  {INFO} No quests in zone — skipping quest accept")


# ── 9. Vendor ─────────────────────────────────────────────────────────────────
print("\n[9] Vendor")
vendor = next((n for n in npcs if n.get("role") == "vendor"), None)
if vendor:
    r = req("get", f"/vendor/{player_id}", params={"npc_name": vendor["name"]})
    check("GET /vendor returns 200", r and r.status_code == 200)
    vd = r.json() if r else {}
    check("vendor stock is list", isinstance(vd.get("stock"), list))
else:
    print(f"  {INFO} No vendor at hub — skipping vendor test")


# ── 10. Describe endpoints ─────────────────────────────────────────────────────
print("\n[10] Describe endpoints")
r = req("get", "/describe/location", params={"name": "Test Grove", "loc_description": "A quiet clearing.", "zone": "Testland"})
check("GET /describe/location returns 200", r and r.status_code == 200)
check("description string returned", bool((r.json() if r else {}).get("description")))

r = req("get", "/describe/entity", params={"name": "Goblin", "entity_type": "creature", "is_elite": "false", "is_named": "false", "zone": "Testland"})
check("GET /describe/entity returns 200", r and r.status_code == 200)
check("entity description returned", bool((r.json() if r else {}).get("description")))


# ── 11. Cleanup ────────────────────────────────────────────────────────────────
print("\n[11] Cleanup")
r = req("delete", f"/player/{player_id}")
check("DELETE /player returns 200", r and r.status_code == 200)
r2 = req("get", f"/player/{player_id}")
check("player no longer loadable after delete", r2 and r2.status_code == 404)


# ── Summary ───────────────────────────────────────────────────────────────────
print()
if failures:
    print(f"\033[91m{len(failures)} check(s) failed:\033[0m")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print(f"\033[92mAll checks passed.\033[0m")
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    args = parser.parse_args()
    BASE = args.base
