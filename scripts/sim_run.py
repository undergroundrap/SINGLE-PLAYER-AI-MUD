"""
sim_run.py — Headless game simulation following the full progression meta.

Plays the complete game loop automatically:
  Open world sweeps → level 10 → dungeon loop (until GS 100 + level 20)
  → raid loop (until zone travel gate met) → zone travel

Usage:
    python scripts/sim_run.py                   # full meta run
    python scripts/sim_run.py --quick           # one sweep + one dungeon, then stop
    python scripts/sim_run.py --no-cleanup      # keep character after run
    python scripts/sim_run.py --skip-to-dungeon # boost to lv10 ~94 GS, skip Phase 1
    python scripts/sim_run.py --skip-to-raid    # boost to lv20 ~280 GS, skip Phases 1+2
    python scripts/sim_run.py --base http://localhost:8001

Exits 0 on a clean run, 1 on any hard error.
"""

import sys
import time
import argparse

# ── CLI ────────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://localhost:8000")
parser.add_argument("--quick", action="store_true",
                    help="Stop after first dungeon clear — fast smoke check")
parser.add_argument("--no-cleanup", action="store_true",
                    help="Keep the test character after the run")
parser.add_argument("--skip-to-dungeon", action="store_true",
                    help="Instantly boost to level 10 ~94 GS, skip Phase 1 (saves ~35-50 min)")
parser.add_argument("--skip-to-raid", action="store_true",
                    help="Instantly boost to level 20 ~280 GS, skip Phases 1+2 (saves ~60-90 min)")
parser.add_argument("--name", default="SimBot")
args = parser.parse_args()

try:
    import requests
except ImportError:
    print("requests not installed — run: pip install requests")
    sys.exit(1)

BASE = args.base

# Progression gates (must match backend)
DUNGEON_LEVEL_GATE = 10
RAID_LEVEL_GATE    = 20
RAID_GS_GATE       = 100
MAX_DUNGEONS       = 20   # safety cap — prevents infinite loops if GS never rises
MAX_RAIDS          = 10
MAX_SWEEPS         = 60

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
_sim_start      = time.time()
_section_start  = time.time()


def _ts() -> str:
    return f"{DIM}[{time.time() - _sim_start:6.1f}s]{RST}"


def log(msg: str, color: str = W) -> None:
    print(f"  {_ts()} {color}{msg}{RST}")


def warn(msg: str) -> None:
    errors.append(msg)
    log(f"✗ {msg}", R)


def milestone(title: str, pid: str) -> None:
    """Print a loud phase-transition banner with current player stats."""
    p, gs = fresh_player(pid)
    elapsed = time.time() - _sim_start
    print(f"\n{M}{'█' * 64}{RST}")
    print(f"{M}  ★ MILESTONE: {title}{RST}")
    print(f"{M}  Lv{p.get('level','?')}  GS {gs}  "
          f"Dungeons {p.get('dungeons_cleared',0)}  Raids {p.get('raids_cleared',0)}  "
          f"Gold {p.get('gold',0)}  [{elapsed:.0f}s elapsed]{RST}")
    eq = p.get("equipment", {})
    gear_lines = [
        f"    {slot:10} {item.get('name','?'):28} [{item.get('rarity','?'):9}] "
        f"stat={list(item.get('stats',{}).values())[0] if item.get('stats') else '?'}"
        for slot, item in eq.items()
        if item.get("name") and item["name"] != "None"
    ]
    for line in gear_lines:
        print(f"{DIM}{line}{RST}")
    print(f"{M}{'█' * 64}{RST}\n")


def section(title: str) -> None:
    global _section_start
    elapsed = time.time() - _section_start
    _section_start = time.time()
    print(f"\n{Y}{'─' * 64}{RST}")
    if elapsed > 0.5:
        print(f"{DIM}  (previous section took {elapsed:.1f}s){RST}")
    print(f"{Y}  {title}{RST}")
    print(f"{Y}{'─' * 64}{RST}")


# ── HTTP ──────────────────────────────────────────────────────────────────────

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


def fresh_player(pid: str) -> tuple[dict, int]:
    """Returns (player_dict, gear_score)."""
    r = req("get", f"/player/{pid}")
    d = r.json() if r and r.status_code == 200 else {}
    return d.get("player", {}), d.get("gear_score", 0)


def move(pid: str, loc_id: str) -> bool:
    r = req("post", f"/action/move/{pid}", params={"location_id": loc_id})
    return bool(r and r.status_code == 200 and r.json().get("success"))


def alive_mobs_at(loc: dict) -> list[dict]:
    now = time.time()
    return [m for m in loc.get("mobs", []) if not m.get("respawn_at") or m["respawn_at"] <= now]


# ── Combat ────────────────────────────────────────────────────────────────────

def attack_once(pid: str, mob_name: str) -> dict | None:
    for _ in range(5):
        r = req("post", f"/action/attack/{pid}", params={"mob_name": mob_name})
        if not r:
            return None
        if r.status_code == 429:
            time.sleep(1.6)
            continue
        if r.status_code == 200:
            return r.json()
        return None
    return None


def kill_mob(pid: str, mob_name: str, max_rounds: int = 80) -> dict | None:
    """Attack until target_dead=True. Returns kill response or None."""
    time.sleep(1.6)
    for _ in range(max_rounds):
        a = attack_once(pid, mob_name)
        if a is None:
            return None
        if a.get("target_dead"):
            return a
        if a.get("player_dead"):
            log(f"    ☠ Died fighting {mob_name} — respawned", R)
            time.sleep(1.0)
            return None
        time.sleep(1.6)
    log(f"    Gave up on {mob_name} after {max_rounds} rounds", Y)
    return None


# ── Quest helpers ─────────────────────────────────────────────────────────────

def accept_all_quests(pid: str, zone: dict) -> int:
    p, _ = fresh_player(pid)
    active_ids    = {q["id"] for q in p.get("active_quests", [])}
    completed_ids = set(p.get("completed_quest_ids", []))
    accepted = 0
    for q in zone.get("quests", []):
        if q["id"] in active_ids or q["id"] in completed_ids:
            continue
        r = req("post", f"/quests/accept/{pid}", params={"quest_id": q["id"]})
        if r and r.status_code == 200:
            log(f"  + Quest: {q['title']}  [{q.get('quest_type','?')}]", C)
            accepted += 1
    return accepted


def turn_in_all_quests(pid: str) -> int:
    p, _ = fresh_player(pid)
    done = [q for q in p.get("active_quests", []) if q.get("is_completed")]
    turned = 0
    for q in done:
        r = req("post", f"/quests/complete/{pid}", params={"quest_id": q["id"]})
        if r and r.status_code == 200:
            xp = r.json().get("xp_reward", 0)
            log(f"  ★ Turned in '{q['title']}'  +{xp} XP", G)
            turned += 1
    return turned


def sync_kill_progress(pid: str, mob_name: str) -> None:
    p, _ = fresh_player(pid)
    for q in p.get("active_quests", []):
        if q.get("is_completed"):
            continue
        if q.get("quest_type") in ("kill", "gather", "hunt"):
            target = q.get("target_id", "").lower()
            if target in mob_name.lower() or mob_name.lower() in target:
                new_prog = min(q["target_count"], q["current_progress"] + 1)
                req("post", f"/quests/progress/{pid}",
                    params={"quest_id": q["id"], "progress": new_prog})


# ── Vendor helpers ────────────────────────────────────────────────────────────

def sell_junk(pid: str) -> int:
    r = req("post", f"/vendor/sell_junk/{pid}")
    if r and r.status_code == 200:
        sj = r.json()
        if sj.get("sold_count", 0) > 0:
            log(f"  Sold {sj['sold_count']} junk  +{sj['gold_gained']} gold", G)
        return sj.get("gold_gained", 0)
    return 0


def buy_potions(pid: str, vendor_name: str) -> None:
    """Buy healing potions and XP elixirs if affordable."""
    p, _ = fresh_player(pid)
    r = req("get", f"/vendor/{pid}", params={"npc_name": vendor_name})
    if not r or r.status_code != 200:
        return
    vd    = r.json()
    stock = vd.get("stock", [])
    gold  = vd.get("gold", 0)

    for item in stock:
        stats = item.get("stats", {})
        is_consumable = item.get("slot") == "consumable"
        if not is_consumable:
            continue
        price = item.get("price", 9999)
        if gold < price:
            continue
        # Check if we already have one
        has_it = any(
            i.get("id") == item["id"] or
            (i.get("stats", {}).get("heal_pct") and stats.get("heal_pct")) or
            (i.get("stats", {}).get("xp_bonus_pct") and stats.get("xp_bonus_pct"))
            for i in p.get("inventory", [])
        )
        if has_it:
            continue
        r2 = req("post", f"/vendor/buy/{pid}",
                 params={"npc_name": vendor_name, "item_id": item["id"]})
        if r2 and r2.status_code == 200:
            log(f"  Bought: {item['name']}  ({price}g)", G)
            gold -= price


def use_potion_if_low(pid: str) -> None:
    p, _ = fresh_player(pid)
    hp, mhp = p.get("hp", 100), p.get("max_hp", 100)
    if hp / mhp > 0.40:
        return
    potion = next(
        (i for i in p.get("inventory", []) if i.get("stats", {}).get("heal_pct")), None
    )
    if not potion:
        return
    r = req("post", f"/action/use/{pid}", params={"item_id": potion["id"]})
    if r and r.status_code == 200:
        new_hp = r.json().get("player_hp", hp)
        log(f"  🧪 Healing potion  {hp} → {new_hp} HP", G)


# ── Location clearing ─────────────────────────────────────────────────────────

def _clear_location(pid: str, loc_id: str, zone_id: str) -> int:
    """Kill all alive mobs at a location, then forage if a quest targets here."""
    kills = 0
    zone    = fresh_zone(zone_id)
    loc_map = {l["id"]: l for l in zone.get("locations", [])}
    loc     = loc_map.get(loc_id)
    if not loc:
        return 0

    mobs = alive_mobs_at(loc)
    for mob in mobs:
        name = mob["name"]
        rank  = ("⚑ " if mob.get("is_named") else "★ " if mob.get("is_elite") else "")
        log(f"    ⚔ {rank}{name}  lv{mob['level']}  {mob['hp']}/{mob['max_hp']} HP", Y)
        use_potion_if_low(pid)
        result = kill_mob(pid, name)
        if result:
            kills += 1
            xp   = result.get("xp_gained", 0)
            gold = result.get("gold_gained", 0)
            loot = result.get("loot_item")
            lvl  = result.get("player_level", 0)
            msg  = f"    Killed {name}  +{xp} XP  +{gold}g"
            if loot:
                msg += f"  [{loot.get('rarity')} {loot.get('name')}]"
            log(msg, G)
            if result.get("leveled_up"):
                log(f"    ★★★ LEVEL UP → {lvl} ★★★", M)
            sync_kill_progress(pid, name)
        else:
            log(f"    Skipped {name}", Y)

        # Reload location
        zone    = fresh_zone(zone_id)
        loc_map = {l["id"]: l for l in zone.get("locations", [])}
        loc     = loc_map.get(loc_id, loc)

    # Forage quest at this location?
    p, _ = fresh_player(pid)
    forage_q = next(
        (q for q in p.get("active_quests", [])
         if q.get("quest_type") == "forage"
         and q.get("target_id") == loc_id
         and not q.get("is_completed")),
        None
    )
    if forage_q:
        remaining = forage_q["target_count"] - forage_q["current_progress"]
        log(f"    Foraging: {forage_q['title']}  "
            f"({forage_q['current_progress']}/{forage_q['target_count']})", C)
        for _ in range(remaining):
            r = req("post", f"/action/gather/{pid}")
            if r and r.status_code == 200:
                for m in r.json().get("messages", []):
                    log(f"      {m}", DIM)
                time.sleep(8.5)
            elif r and r.status_code == 429:
                time.sleep(8.5)
            else:
                log(f"      Gather failed", R)
                break

    return kills


# ── Zone sweep ────────────────────────────────────────────────────────────────

def do_zone_sweep(pid: str, zone_id: str, hub_loc_id: str, vendor_name: str | None) -> int:
    """Hub → each path (harvest+fish) → each POI (kill+forage) → back to hub."""
    zone    = fresh_zone(zone_id)
    loc_map = {l["id"]: l for l in zone.get("locations", [])}
    hub     = loc_map.get(hub_loc_id)
    if not hub:
        return 0

    kills = 0
    for direction, next_id in hub.get("exits", {}).items():
        spoke = loc_map.get(next_id)
        if not spoke:
            continue

        # Path location
        if spoke.get("resources") and len(spoke["resources"]) >= 2:
            plant, fish = spoke["resources"][0], spoke["resources"][1]
            log(f"  [{direction.upper()}] Path: {spoke['name']}  ({plant} / {fish})", C)
            move(pid, spoke["id"])

            r = req("post", f"/action/harvest/{pid}")
            if r and r.status_code == 200:
                d = r.json()
                item = d.get("item") or {}
                name = item.get("name") if item else None
                if name:
                    log(f"    🌿 {name}", G)
                elif not d.get("success"):
                    log(f"    🌿 {d.get('message', 'harvest blocked')}", DIM)
                else:
                    warn(f"harvest 200 but no item name: {d}")
            elif r and r.status_code == 429:
                log(f"    🌿 Harvest on cooldown", DIM)
            else:
                warn(f"harvest failed ({r.status_code if r else '?'})")

            r = req("post", f"/action/fish/{pid}")
            if r and r.status_code == 200:
                d = r.json()
                item = d.get("item") or {}
                name = item.get("name") if item else None
                if name:
                    log(f"    🎣 {name}", G)
                elif not d.get("success"):
                    log(f"    🎣 {d.get('message', 'fish blocked')}", DIM)
                else:
                    warn(f"fish 200 but no item name: {d}")
            elif r and r.status_code == 429:
                log(f"    🎣 Fish on cooldown", DIM)
            else:
                warn(f"fish failed ({r.status_code if r else '?'})")

            # Forward to POI
            poi_id = next((v for k, v in spoke.get("exits", {}).items() if v != hub_loc_id), None)
            if poi_id:
                poi = loc_map.get(poi_id, {})
                log(f"    → POI: {poi.get('name','?')}", C)
                move(pid, poi_id)
                kills += _clear_location(pid, poi_id, zone_id)
                move(pid, spoke["id"])

            move(pid, hub_loc_id)

        # Direct POI (old zone without paths)
        else:
            log(f"  [{direction.upper()}] POI: {spoke['name']}", C)
            move(pid, spoke["id"])
            kills += _clear_location(pid, spoke["id"], zone_id)
            move(pid, hub_loc_id)

    return kills


# ── Hub routine (turn in, sell, buy) ──────────────────────────────────────────

def do_hub_routine(pid: str, zone_id: str, vendor_name: str | None) -> None:
    """Turn in completed quests, sell junk, rebuy potions."""
    turned = turn_in_all_quests(pid)
    if turned:
        zone = fresh_zone(zone_id)
        accept_all_quests(pid, zone)
    if vendor_name:
        sell_junk(pid)
        buy_potions(pid, vendor_name)


# ── Dungeon run ───────────────────────────────────────────────────────────────

def do_dungeon_run(pid: str, is_raid: bool = False) -> bool:
    """
    Run a full dungeon or raid. Returns True if cleared, False if wiped/failed.
    """
    kind = "RAID" if is_raid else "DUNGEON"
    r = req("post", f"/dungeon/enter/{pid}", params={"is_raid": str(is_raid).lower()})
    if not r or r.status_code != 200:
        try:
            detail = r.json().get("detail", r.text[:80]) if r else "no response"
        except Exception:
            detail = r.text[:80] if r else "no response"
        warn(f"{kind} entry failed: {detail}")
        return False

    run    = r.json()
    run_id = run["id"]
    total  = 7 if run.get("is_raid") else 4
    log(f"  Entered: {run['dungeon_name']}  lv{run['dungeon_level']}  "
        f"party: {len(run['party'])}", G)
    log(f"  Party: " + ", ".join(f"{m['name']} [{m['role']}]" for m in run["party"]), DIM)

    while run.get("status") == "active":
        idx      = run["room_index"]
        room     = run["rooms"][idx]
        alive_ct = sum(1 for m in room.get("mobs", []) if m.get("hp", 0) > 0)
        log(f"  Room {idx + 1}/{total}: {room['name']}  ({alive_ct} alive)", Y)

        advanced = False
        for _ in range(80):
            r2 = req("post", f"/dungeon/attack/{run_id}", params={"player_id": pid})
            if not r2 or r2.status_code != 200:
                warn(f"{kind} attack failed")
                return False
            rd  = r2.json()
            run = rd["run"]

            for line in rd.get("round_log", []):
                log(f"    {line}", DIM)

            if rd.get("wiped"):
                log(f"  ✗ Party wiped!", R)
                return False

            if rd.get("run_cleared"):
                log(f"  ★ {kind} cleared!", G)
                loot = rd.get("loot", [])
                for item in loot:
                    log(f"    [{item.get('rarity')}] {item.get('name')} ({item.get('slot')})", M)
                if not loot:
                    warn(f"{kind} cleared but no loot returned")
                return True

            if rd.get("room_cleared"):
                log(f"  Room {idx + 1} cleared!", G)
                r3 = req("post", f"/dungeon/advance/{run_id}", params={"player_id": pid})
                if r3 and r3.status_code == 200:
                    run = r3.json()  # advance returns the run directly, not wrapped in {"run": ...}
                advanced = True
                break

            time.sleep(0.05)

        if not advanced and run.get("status") == "active":
            warn(f"Room {run['room_index'] + 1} didn't clear after 80 rounds")
            return False

    return run.get("status") == "cleared"


# ── Zone travel ───────────────────────────────────────────────────────────────

def try_zone_travel(pid: str) -> bool:
    r = req("post", f"/zone/travel/{pid}")
    if r and r.status_code == 200:
        new_zone = r.json().get("zone", {})
        log(f"★ Zone travel → {new_zone.get('name','?')}", G)
        return True
    try:
        detail = r.json().get("detail", r.text[:100]) if r else "no response"
    except Exception:
        detail = r.text[:100] if r else "no response"
    log(f"  Zone travel blocked: {detail}", Y)
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

print(f"\n{M}{'═' * 64}{RST}")
print(f"{M}  SINGLE PLAYER AI MUD — Full Meta Simulation{RST}")
_mode = ("QUICK" if args.quick
         else "SKIP-TO-RAID"    if args.skip_to_raid
         else "SKIP-TO-DUNGEON" if args.skip_to_dungeon
         else "FULL META")
print(f"{M}  Mode: {_mode}  |  Backend: {BASE}{RST}")
print(f"{M}{'═' * 64}{RST}")


# ── Create character ──────────────────────────────────────────────────────────
section("CREATE CHARACTER")
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
hub_npcs   = hub_loc.get("npcs", [])
hub_vendor = next((n for n in hub_npcs if n["role"] == "vendor"), None)
vendor_name = hub_vendor["name"] if hub_vendor else None

req("post", f"/action/login/{pid}")
log(f"Created {player['name']} (Orc Warrior)  id: {pid[:8]}…", G)
log(f"Zone: {zone['name']}  |  Hub: {hub_loc.get('name','?')}", C)
log(f"Locations: {len(zone['locations'])}  |  Quests: {len(zone['quests'])}", DIM)


# ── Zone topology ─────────────────────────────────────────────────────────────
section("ZONE TOPOLOGY")
path_locs = [l for l in zone["locations"] if len(l.get("resources", [])) >= 2]
poi_locs  = [l for l in zone["locations"]
             if l["id"] != hub_loc_id and not l.get("resources") and not l.get("npcs")]
log(f"Hub:   {hub_loc.get('name','?')}", W)
log(f"Paths: {len(path_locs)}  — " + ", ".join(l["name"] for l in path_locs), C)
log(f"POIs:  {len(poi_locs)}  — "  + ", ".join(l["name"] for l in poi_locs), Y)
if not path_locs:
    warn("No path locations — world_generator path insertion may be broken")


# ── Talk to NPCs, accept quests, buy first potion ────────────────────────────
section("SETUP — NPCS / QUESTS / VENDOR")
for npc in hub_npcs:
    r = req("post", f"/action/talk/{pid}", params={"npc_name": npc["name"]})
    if r and r.status_code == 200:
        td = r.json()
        log(f"Talked to {npc['name']} ({npc['role']})", G)
        if td.get("dialogue"):
            log(f"  \"{td['dialogue'][:80]}\"", DIM)
    else:
        warn(f"Talk to {npc['name']} failed")

zone = fresh_zone(zone_id)
n = accept_all_quests(pid, zone)
log(f"Accepted {n} quest(s)", G if n else Y)

if vendor_name:
    sell_junk(pid)
    buy_potions(pid, vendor_name)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — OPEN WORLD: grind until level 10 (dungeon gate)
# ═══════════════════════════════════════════════════════════════════════════════

if args.skip_to_raid:
    section(f"PHASE 1+2 — SKIPPED (--skip-to-raid)")
    r = req("post", f"/admin/boost/{pid}",
            params={"level": RAID_LEVEL_GATE, "preset": "raid"})
    if r and r.status_code == 200:
        bd = r.json()
        log(f"Boosted to Lv{bd['level']}  HP {bd['hp']}  DMG {bd['damage']}  "
            f"GS {bd['gear_score']}  Gold {bd['gold']}", G)
        milestone("SKIPPED TO RAID — entering Phase 3", pid)
    else:
        die(f"Boost failed: {r.status_code if r else 'no response'}")
elif args.skip_to_dungeon:
    section(f"PHASE 1 — SKIPPED (--skip-to-dungeon)")
    r = req("post", f"/admin/boost/{pid}",
            params={"level": DUNGEON_LEVEL_GATE, "preset": "dungeon"})
    if r and r.status_code == 200:
        bd = r.json()
        log(f"Boosted to Lv{bd['level']}  HP {bd['hp']}  DMG {bd['damage']}  "
            f"GS {bd['gear_score']}  Gold {bd['gold']}", G)
    else:
        die(f"Boost failed: {r.status_code if r else 'no response'}")
else:
    section(f"PHASE 1 — OPEN WORLD (target: level {DUNGEON_LEVEL_GATE})")

    sweep_count   = 0
    respawn_waits = 0

    while True:
        p, gs = fresh_player(pid)
        level = p.get("level", 1)
        xp    = p.get("xp", 0)
        nxp   = p.get("next_level_xp", 100)
        log(f"── Sweep {sweep_count + 1}  Lv{level}  XP {xp}/{nxp}  GS {gs}  "
            f"Gold {p.get('gold',0)}", C)

        if level >= DUNGEON_LEVEL_GATE:
            log(f"Reached level {DUNGEON_LEVEL_GATE} — dungeon unlocked!", G)
            milestone("PHASE 1 → 2: Open World Complete", pid)
            break

        kills = do_zone_sweep(pid, zone_id, hub_loc_id, vendor_name)
        sweep_count += 1
        move(pid, hub_loc_id)
        do_hub_routine(pid, zone_id, vendor_name)

        if kills == 0:
            respawn_waits += 1
            log(f"No kills — waiting 15s for respawns ({respawn_waits}/6)…", DIM)
            time.sleep(15)
            if respawn_waits >= 6:
                warn("Too many empty sweeps — mobs may not be respawning")
                break
        else:
            respawn_waits = 0

        if sweep_count >= MAX_SWEEPS:
            warn(f"Sweep limit ({MAX_SWEEPS}) hit at level {level}")
            break

        if args.quick:
            log("--quick: stopping open world phase after 1 sweep", DIM)
            break


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — DUNGEON LOOP: run dungeons + open world until GS 100 + level 20
# ═══════════════════════════════════════════════════════════════════════════════
if args.skip_to_raid:
    section(f"PHASE 2 — SKIPPED (--skip-to-raid)")
else:
    section(f"PHASE 2 — DUNGEON LOOP (target: GS {RAID_GS_GATE} + level {RAID_LEVEL_GATE})")

dungeon_count = 0
respawn_waits = 0

while dungeon_count < MAX_DUNGEONS and not args.skip_to_raid:
    p, gs = fresh_player(pid)
    level = p.get("level", 1)
    log(f"── Dungeon {dungeon_count + 1}  Lv{level}  GS {gs}", C)

    if level >= RAID_LEVEL_GATE and gs >= RAID_GS_GATE:
        log(f"GS {gs} ≥ {RAID_GS_GATE} and level {level} ≥ {RAID_LEVEL_GATE} — raid unlocked!", G)
        milestone("PHASE 2 → 3: Dungeon Phase Complete", pid)
        break

    cleared = do_dungeon_run(pid, is_raid=False)
    dungeon_count += 1
    move(pid, hub_loc_id)
    do_hub_routine(pid, zone_id, vendor_name)

    if args.quick:
        log("--quick: stopping after first dungeon run", DIM)
        break

    # Re-queue dungeon immediately — open world is done, dungeons are the progression loop

if dungeon_count >= MAX_DUNGEONS:
    warn(f"Hit dungeon cap ({MAX_DUNGEONS}) — GS may not be scaling correctly")


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — RAID LOOP: run raids until zone travel gate met
# ═══════════════════════════════════════════════════════════════════════════════
p, gs = fresh_player(pid)
if not args.quick and p.get("level", 1) >= RAID_LEVEL_GATE and gs >= RAID_GS_GATE:
    section(f"PHASE 3 — RAID LOOP (until zone travel gate)")

    raid_count = 0
    while raid_count < MAX_RAIDS:
        p, gs = fresh_player(pid)
        log(f"── Raid {raid_count + 1}  Lv{p.get('level',1)}  GS {gs}", C)

        cleared = do_dungeon_run(pid, is_raid=True)
        raid_count += 1
        move(pid, hub_loc_id)
        do_hub_routine(pid, zone_id, vendor_name)

        # Try zone travel after each raid clear
        if cleared:
            p, gs = fresh_player(pid)
            log(f"  Checking zone travel…  GS {gs}  (need 1000)", DIM)
            if try_zone_travel(pid):
                milestone("ZONE TRAVEL SUCCESS — Phase 3 Complete", pid)
                # Update zone state for the new zone
                p, gs = fresh_player(pid)
                zone_id    = p.get("current_zone_id", zone_id)
                zone       = fresh_zone(zone_id)
                hub_loc_id = p.get("current_location_id", hub_loc_id)
                loc_map    = {l["id"]: l for l in zone.get("locations", [])}
                hub_loc    = loc_map.get(hub_loc_id, {})
                hub_npcs   = hub_loc.get("npcs", [])
                hub_vendor = next((n for n in hub_npcs if n["role"] == "vendor"), None)
                vendor_name = hub_vendor["name"] if hub_vendor else None
                log(f"  New zone: {zone.get('name','?')}", G)
                accept_all_quests(pid, zone)
                break

    if raid_count >= MAX_RAIDS:
        warn(f"Hit raid cap ({MAX_RAIDS}) without zone travel — GS gate may be too high")
else:
    if not args.quick:
        p, gs = fresh_player(pid)
        log(f"Skipping raid phase — Lv{p.get('level',1)} GS {gs} "
            f"(need Lv{RAID_LEVEL_GATE} + GS {RAID_GS_GATE})", Y)


# ═══════════════════════════════════════════════════════════════════════════════
# FINAL STATE
# ═══════════════════════════════════════════════════════════════════════════════
section("FINAL CHARACTER STATE")
p, gs = fresh_player(pid)
log(f"Name:     {p['name']}", W)
log(f"Level:    {p['level']}", W)
log(f"HP:       {p['hp']}/{p['max_hp']}", W)
log(f"XP:       {p['xp']}/{p['next_level_xp']}", W)
log(f"Gold:     {p['gold']}", W)
log(f"GS:       {gs}", W)
log(f"Kills:    {p['kills']}", W)
log(f"Deaths:   {p['deaths']}", W)
log(f"Dungeons: {p.get('dungeons_cleared', 0)}", W)
log(f"Raids:    {p.get('raids_cleared', 0)}", W)
log(f"Quests completed: {len(p.get('completed_quest_ids', []))}", W)

log("Equipment:", W)
for slot, item in p.get("equipment", {}).items():
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
        warn(f"Delete failed: {r.status_code if r else '?'}")
else:
    section("KEEPING CHARACTER")
    log(f"'{args.name}'  player_id: {pid}", Y)
    log("Run 'python scripts/reset_data.py' to wipe when done.", DIM)


# ── Summary ───────────────────────────────────────────────────────────────────
total = time.time() - _sim_start
print(f"\n{M}{'═' * 64}{RST}")
print(f"{M}  Total time: {total:.1f}s ({total / 60:.1f} min){RST}")
if errors:
    print(f"{R}  {len(errors)} issue(s):{RST}")
    for e in errors:
        print(f"{R}    - {e}{RST}")
    print(f"{M}{'═' * 64}{RST}\n")
    sys.exit(1)
else:
    print(f"{G}  Simulation completed without errors.{RST}")
    print(f"{M}{'═' * 64}{RST}\n")
    sys.exit(0)
