"""
boost_char.py — Create a boosted character ready for frontend testing.

Creates a fresh character and instantly sets them to dungeon or raid tier.
Load the character in the browser via the Load Game screen.

Usage:
    python scripts/boost_char.py                  # dungeon-ready (default)
    python scripts/boost_char.py --target raid    # raid-ready
    python scripts/boost_char.py --name Tester    # custom name
    python scripts/boost_char.py --base http://localhost:8001
"""

import argparse
import sys
import requests
import random

parser = argparse.ArgumentParser()
parser.add_argument("--target", choices=["dungeon", "raid"], default="dungeon")
parser.add_argument("--name",   default="")
parser.add_argument("--base",   default="http://localhost:8000")
args = parser.parse_args()

BASE   = args.base.rstrip("/")
TARGET = args.target

NAMES   = ["Aldric", "Sylvara", "Corvus", "Theron", "Elowen", "Drake", "Ashe", "Vex"]
RACES   = ["Human", "Elf", "Dwarf", "Orc"]
CLASSES = ["Warrior", "Paladin", "Hunter", "Rogue", "Mage", "Shaman"]

name      = args.name or random.choice(NAMES) + str(random.randint(10, 99))
race      = random.choice(RACES)
char_class = random.choice(CLASSES)
level     = 10 if TARGET == "dungeon" else 20

print(f"\n  Creating {race} {char_class} — '{name}' (target: {TARGET})")

# ── Create character ────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/player/create", params={
    "name":       name,
    "race":       race,
    "char_class": char_class,
    "pronouns":   "They/Them",
})
if not r.ok:
    print(f"  ERROR: Could not create character — {r.text}")
    sys.exit(1)

player_id = r.json().get("player_id")
if not player_id:
    print(f"  ERROR: No player_id in response — {r.json()}")
    sys.exit(1)

print(f"  Created  — ID: {player_id}")

# ── Boost ───────────────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/admin/boost/{player_id}", params={
    "level":  level,
    "preset": TARGET,
})
if not r.ok:
    print(f"  ERROR: Boost failed — {r.text}")
    sys.exit(1)

d = r.json()
print(f"  Boosted  — Lv{d['level']}  HP {d['hp']}  DMG {d['damage']}  GS {d['gear_score']}  Gold {d['gold']}")

gate = "Enter dungeon with 'travel dungeon'" if TARGET == "dungeon" else "Enter raid with 'travel raid'"
print(f"\n  Ready. Load '{name}' in the browser, then: {gate}")
print(f"  Player ID: {player_id}\n")
