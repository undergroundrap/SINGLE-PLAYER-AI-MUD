# SINGLE PLAYER AI MUD

An infinite, AI-powered text-based MMORPG. Explore a procedurally generated open world, fight enemies, complete quests, trade with vendors, and chat with AI-simulated players — all rendered in a terminal-style browser UI.

---

## Table of Contents

1. [Concept](#concept)
2. [Tech Stack](#tech-stack)
3. [Architecture Overview](#architecture-overview)
4. [Quick Reference — What Lives Where](#quick-reference--what-lives-where)
5. [Directory Structure & What Lives Where](#directory-structure--what-lives-where)
6. [Key Systems — How They Work](#key-systems--how-they-work)
7. [Data Models](#data-models)
8. [API Reference](#api-reference)
9. [Getting Started](#getting-started)
10. [Environment Variables](#environment-variables)
11. [Simulation-Driven Balance Methodology](#simulation-driven-balance-methodology)
12. [Extending the Game](#extending-the-game)
13. [Design Decisions](#design-decisions)
14. [Known Constraints & Gotchas](#known-constraints--gotchas)

---

## Concept

The game follows a classic MMO loop — **open world zones → dungeons (level 10+) → raids (level 20+)** — repeated infinitely with no level cap. Each zone is either drawn from a curated starter template (levels 1–5) or procedurally generated using an AI narrative layer on top of deterministic math scaffolding.

Each zone's topology is **hub → path → POI** for every spoke. Path locations are safe rest stops between the hub and each point of interest — no combat mobs spawn on paths, and patrol encounters never fire there. Every path location has a harvestable plant and a fishing hole, giving players a low-pressure gold source between fights.

Players are single-player but exist in a world populated by simulated entities (SimulatedPlayers) that move, rest, and respond to the environment — each with a generated fantasy name (Theron, Sylvara, Corvus, etc.) and a stable personality archetype. World chat responses come from these zone-specific players, grounded in the actual location, mobs, and weather the player is experiencing right now.

Every class has a unique **auto-firing passive proc** that triggers mid-combat without any input — Rogues evade, Warlocks drain life, Paladins self-heal. Combat is intentionally hands-off so players can focus on questing, chatting, and exploring while loot and levels accumulate. Dungeon and raid portals are always visible in the sidebar from level 1 so players always know what they're working toward.

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | Next.js 16 (App Router) | React SSR + client state |
| Frontend | TypeScript | Type safety across all UI logic |
| Frontend | Tailwind CSS + globals.css | Dark terminal aesthetic, component styles |
| Backend | FastAPI + Uvicorn | Async Python HTTP API |
| Backend | Pydantic v2 | Schema validation and serialization (`model_dump(mode='json')`) |
| Persistence | SQLite (stdlib) | Single `mud.db` file — stores player + zone rows as JSON blobs |
| Persistence | In-memory LRU cache (200 entries) | Wraps SQLite reads — cache is checked first on every get |
| AI | LM Studio (local) | OpenAI-compatible local LLM server at `http://localhost:1234/v1` |
| AI | openai Python SDK | Used to talk to LM Studio via its OpenAI-compatible REST endpoint |

> **Note:** This project does NOT use the OpenAI cloud API. All LLM calls go to a locally running LM Studio instance. The `openai` pip package is used purely as the HTTP client because LM Studio exposes an OpenAI-compatible interface.

---

## Architecture Overview

```
Browser (Next.js)
    │
    │  HTTP (fetch, POST/GET)
    ▼
FastAPI  ─── main.py  (all endpoints, combat logic, loot rolling, quest management)
    │
    ├── app/core/world_generator.py   (zone/mob/NPC/vendor generation)
    ├── app/core/combat_engine.py     (hit/miss/damage resolution)
    ├── app/core/scaling_math.py      (HP/damage/XP formulas)
    ├── app/core/ai_client.py         (LM Studio wrapper)
    ├── app/core/simulation.py        (background tick loop)
    ├── app/core/vector_db.py         (SQLite DBManager + LRU cache)
    └── app/models/schemas.py         (Pydantic models — shared truth for all data)
```

**Request lifecycle (example: player attacks a mob):**

1. `POST /action/attack/{player_id}?mob_name=boar` → `main.py`
2. Rate-limit check (`_attack_times` dict, 1.5s cooldown per player)
3. Load player from `vec_db` (LRU cache → SQLite fallback)
4. Load zone from `vec_db` (LRU cache → SQLite fallback)
5. Find target mob in current location, verify it's alive (`respawn_at is None`)
6. `combat_engine.resolve_tick(player, mob)` → hit roll → damage roll
7. Counter-attack if mob survived
8. On mob death: XP + gold + respawn timer + class-biased loot roll → auto-equip if upgrade
9. `vec_db.save_zone(...)` — **always called**, even if mob survived, to persist HP damage
10. `vec_db.save_player(...)` — persist new HP/XP/inventory/equipment
11. Return JSON response with all state deltas

**State ownership:**
- All authoritative game state lives in **SQLite + cache** on the backend
- The frontend maintains a **local mirror** of `player` and `zone` state for instant UI updates
- After every mutating action the frontend syncs from the response (XP, HP, gold, kills)
- The zone ticker (`/zone/{zone_id}` polled every 10s) keeps the local zone mirror fresh

---

## Quick Reference — What Lives Where

| I want to… | Go here |
|---|---|
| Add or change an API endpoint | `backend/main.py` |
| Change combat hit/damage math | `backend/app/core/combat_engine.py` |
| Tune HP/XP/damage scaling curves | `backend/app/core/scaling_math.py` |
| Change loot drop rates or slot weights | `backend/app/core/world_generator.py → _roll_loot, _CLASS_SLOT_WEIGHTS` |
| Add a dungeon or raid mechanic | `backend/app/core/dungeon_engine.py` |
| Change zone/mob/NPC/quest generation | `backend/app/core/world_generator.py` |
| Add a new Pydantic field to any model | `backend/app/models/schemas.py` |
| Change the LLM provider or prompts | `backend/app/core/ai_client.py` |
| Change the background simulation tick | `backend/app/core/simulation.py` |
| Change any UI, command, or frontend state | `frontend/app/page.tsx` |
| Change any visual style or animation | `frontend/app/globals.css` |
| Run the full progression sim | `scripts/sim_run.py` |
| Run the fast smoke test | `scripts/smoke_test.py` |
| Wipe all game data | `scripts/reset_data.py` |

---

## Directory Structure & What Lives Where

```
SINGLE-PLAYER-AI-MUD/
├── README.md
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx              ← ENTIRE frontend. One large file — all state, UI, commands
│   │   └── globals.css           ← All styles. Sections marked with comment headers
│   └── public/assets/            ← Class portraits, UI images
│
└── backend/
    ├── main.py                   ← ALL endpoints + constants + loot system + level-up logic
    │                               If you're adding a new endpoint, this is the file.
    │
    ├── requirements.txt
    │
    └── app/
        ├── models/
        │   └── schemas.py        ← Pydantic data models. Single source of truth for all
        │                           game objects: Player, Zone, Location, Mob, NPC, Quest,
        │                           Item, SimulatedPlayer. Edit here when adding new fields.
        │
        └── core/
            ├── ai_client.py      ← LM Studio HTTP wrapper. generate_content(), stream_content(),
            │                       generate_json(). Swap the LLM provider here.
            │
            ├── combat_engine.py  ← CombatEngine class. Hit rolls, damage rolls, defense
            │                       calculation. RuneScape-style accuracy formula.
            │                       resolve_tick(attacker, target) → (messages, is_dead)
            │
            ├── scaling_math.py   ← Pure math. get_max_hp(level), get_damage(level),
            │                       get_xp_required(level). Tune numbers here.
            │                       Also: CLASS_STATS (hp/dmg multipliers per class),
            │                       RARITY dict (stat multipliers per rarity tier),
            │                       apply_levelups(player, messages) — shared level-up
            │                       loop used by both main.py and dungeon_engine.py.
            │
            ├── simulation.py     ← Background asyncio loop (10s tick). Handles:
            │                       - Mob respawn (respawn_at timer expiry)
            │                       - SimulatedPlayer movement and status changes
            │                         (battling status: actually kills a mob at their
            │                          location and posts a world_message)
            │                       - Weather shifts (5% chance per tick)
            │                       - Time-of-day progression
            │                       - AI-generated zone ambiance messages (10% chance)
            │
            ├── vector_db.py      ← SQLite wrapper + in-memory LRU cache (200 entries).
            │                       save_player / get_player / save_zone / get_zone /
            │                       delete_player / get_all_players / reset_all.
            │                       Uses INSERT OR REPLACE — no pandas, no numpy, no
            │                       pyarrow. Cache checked before every DB read. Zone is
            │                       ALWAYS written after combat (even on non-fatal hits).
            │
            └── world_generator.py← Zone factory. Two paths:
                                    1. Starter (level ≤5): picks from 5 curated templates
                                    2. Procedural (level >5): math scaffold + AI narrative layer
                                    Also owns: elite/named mob generation, loot tables,
                                    vendor NPC generation (_make_vendor).
```

---

## Key Systems — How They Work

### World Generation
`world_generator.py → WorldGenerator.generate_zone(level, is_dungeon, is_raid)`

Two-phase approach:
- **Phase 1 (Math):** Deterministic skeleton — zone ID, hub + 4 POI locations, 3–4 distinct mob names, 5 quest skeletons covering all 4 archetypes, XP values from `ScalingMath`
- **Phase 2 (AI):** Calls LM Studio for names, descriptions, NPC dialogue, quest flavor text. Falls back to a hardcoded gritty-fantasy dictionary if AI is unavailable
- Each hub gets **2 quest giver NPCs** (quests split between them) + a vendor NPC
- Mobs spawn with a 20% elite chance and 5% named chance per slot (`_make_mobs`). Multipliers **ramp by level** so low-level content stays fair: elites are 1.3× HP / 1.1× dmg at level 1, scaling to the full 2.0× / 1.3× by level 10; named mobs start at 1.6× / 1.15× and reach the full 3.0× / 1.5× by level 10.
- **Path topology:** Between every hub and POI a path location is inserted — `hub → path_0 → poi_0`, `hub → path_1 → poi_1`, etc. Paths are wired bidirectionally. Path locations have no mobs, no NPCs, and a `resources` field: `[plant_name, fish_species]` drawn from level-appropriate tables (e.g. `["Ironweed", "Silverscale"]`). Patrol spawns skip path locations entirely.
- **Dungeons:** the final POI is always a boss chamber (`force_boss=True`) — guaranteed named boss + elite guards, location labeled `[BOSS]`
- **Starter zones (level ≤5):** 5 distinct hand-crafted templates (Whispering Glade, Moonshaded Glade, Saltcliff Reach, The Ashen Fields, Barrowmoor) — picked randomly so players rarely see the same start twice

**Quest archetypes** (6 quests per zone, all 5 types used):

| Type | Mechanic | Completion |
|---|---|---|
| `kill` | Slay N of a named mob | Client-side on mob death, synced to backend |
| `hunt` | Kill the zone's named/boss mob (1 target) | Triggers on `target_is_named == true` in attack response |
| `gather` | Collect N items from a mob type | Tracks on kill — strips mob-specific collectible suffix (Tusk, Fang, Pelt, Wing, Tail, Hide, Scale, etc.) to match base mob name. Each mob type has a specific collectible noun — Boars drop Tusks, Spiders drop Fangs, Bats drop Wings, etc. |
| `explore` | Travel to a specific POI location | Auto-completes server-side in `POST /action/move` when player reaches target. Not re-offered once visited. |
| `forage` | Collect N resources using the `gather` command at a specific location (no combat) | Backend endpoint `/action/gather` — requires standing in `quest.target_id` location. 8 s cooldown per gather. Zone-themed resources: Bog Moss, Wild Herb, Sea Kelp, Ember Root, Glowbloom, etc. |

### Progression Loop

The intended loop mirrors classic MMO tier structure. Each tier requires you to gear through the previous one:

```
Open World (level 1–9)   → kill quests, gather, hunt, explore, forage
                           Quests are repeatable — grind until level 10
Dungeon    (level 10+)   → 5-player instanced, Rare/Epic loot (1.6× stats)
                           4 rooms: trash → corridor → trash+elite → boss
                           Gear Score gates the Raid — farm dungeons first
Raid       (level 20+,   → 10-player instanced, Epic/Legendary loot (2.8× stats)
            GS ≥ 100)      7 rooms: trash → corridor → trash+elite → mini-boss
                                    → corridor → deep trash → final boss (enrage at 30%)
                           Clearing a raid pushes open-world zone level +3
Zone Travel              → Requires GS ≥ 1000 (fixed gate, not level-scaled)
                           ~3 raid clears with Rare/Epic drops at level 20
                           Cannot travel on open-world drops alone — must do dungeons + raids
                           "★ ZONE CLEARED!" fires only when travel succeeds (real milestone)
```

This creates an infinite compounding loop: Open World → Dungeon → Raid → meet GS threshold → travel → harder Open World → harder Dungeon → harder Raid → …

**Gear Score** — shown live in the HUD stats panel. Calculated as the sum of all equipped item stat values × rarity multiplier (Common 1×, Rare 2.5×, Epic 4×, Legendary 7×). Raid entry is blocked until GS ≥ 100 with a clear message: *"Gear score too low (74/100). Farm dungeons first."* Once GS ≥ 100 the HUD shows `✓ RAID READY` in purple.

**Zone travel GS gate** — fixed at **1000 GS**. Dungeon grinding alone tops out around 500–600 GS — raids are required. ~2-3 raid clears with Epic/Legendary drops at level 20 will hit 1000. The gate is intentionally fixed (not level-scaled) so it can't become an infinite treadmill as the player levels through raids. The scrolling ticker always shows current GS vs required so the player knows exactly what to farm.

**Raid tier escalation:** Each raid cleared increments `player.raids_cleared`. The zone travel endpoint adds `raids_cleared × 3` to the generated zone level, so open-world content, dungeon mobs, and raid bosses all scale harder with every tier you complete.

**Death penalty:** 15% of current XP lost on death. No gear durability — the XP sting is enough to create tension without frustrating casual players.

**Level-up scaling:** On every level-up, `max_hp` and `damage` are recalculated from `ScalingMath` **and** the class-specific multiplier from `CLASS_STATS` is re-applied. Class advantages persist through every level, not just at character creation.

| Class | HP Mult | Dmg Mult | Identity |
|---|---|---|---|
| Warrior | 1.20 | 1.10 | Tanky all-rounder |
| Paladin | 1.15 | 0.95 | Sustain tank, proc heals |
| Hunter | 1.00 | 1.10 | Glass cannon, spiky proc |
| Rogue | 0.90 | 1.20 | Highest damage, dodge survivability |
| Priest | 0.85 | 0.85 | Squishiest — relies on heal procs |
| Shaman | 1.10 | 1.05 | Tankier damage dealer, sturdy grinder |
| Mage | 0.80 | 1.30 | Burst glass cannon |
| Warlock | 0.85 | 1.20 | High damage, self-sustain via lifesteal |
| Druid | 1.00 | 1.00 | Generalist, frequent rejuvenation procs |

**Out-of-combat HP regen:** 2% of max HP per second kicks in after 6 seconds without taking damage. The frontend regen timer syncs the new HP to the backend (`POST /action/rest/{player_id}`) every ~10 seconds — reconnecting or refreshing restores the regened HP rather than snapping back to the last combat value.

**Rested XP — the daily login hook:** When you log out cleanly (`POST /action/logout/{player_id}` via `sendBeacon`), the server stamps your logout time. On the next login (`POST /action/login/{player_id}`), rest accumulated at a rate of `next_level_xp / 8` per real hour is added to your pool, capped at 1.5× the current level's XP requirement. While you have rested XP, every kill grants 2× XP and drains the pool by the base XP amount — the transition back to 1× is seamless. The XP bar shows a faint teal overlay representing the rested pool, and kill log lines show `💤(+N rested)` so the bonus is always visible. The message `💤 You are Rested!` greets you on login when the pool is non-zero.

**Consumables — closing the gold loop:** Every vendor stocks two potions that scale in price with zone level, giving gold a permanent purpose:

| Item | Effect | Cooldown | Price |
|---|---|---|---|
| Healing Potion | Restores 40% max HP instantly | 60 s | ~8 × level gold |
| Elixir of Insight | Next 5 kills grant +75% XP | 5 min | ~22 × level gold |

Potions appear in a dedicated **POTIONS panel** in the sidebar with USE buttons, cooldown countdowns, and active buff charge tracking. They can also be used via `use healing` / `use elixir` in the command line. **Auto-use:** the frontend automatically drinks a Healing Potion when HP drops to ≤25% of max, if one is available and off cooldown — keeping fragile classes like Mage and Priest alive without interrupting combat flow.

### Class Passive Procs
`main.py → _apply_class_proc(player, target_mob, messages)`

Every class has a unique passive ability that **fires automatically** between the player's attack and the mob's counter-attack — no button presses required. This keeps combat frictionless (ideal for chatting while grinding) while creating unpredictable dopamine moments. Proc messages appear in **gold** in the combat log.

| Class | Proc | Chance | Effect |
|---|---|---|---|
| Warrior | ⚔ BATTLE FURY | 20% | 2× bonus damage |
| Paladin | ✦ DIVINE GRACE | 20% | Heal 15% max HP |
| Hunter | ⚡ POWER SHOT | 20% | 2.5× bonus damage |
| Rogue | ☽ EVASION | 25% | Skip mob counter-attack |
| Priest | ✦ HOLY MEND | 25% | Heal 20% max HP |
| Shaman | ⚡ CHAIN LIGHTNING | 20% | 1.8× bonus damage |
| Mage | ✦ ARCANE SURGE | 25% | 1.8× bonus damage |
| Warlock | ✧ SOUL DRAIN | 20% | 1.5× damage + lifesteal (half as healing) |
| Druid | ✦ REJUVENATION | 25% | Heal 15% max HP |

Proc fires after the player's hit resolves. If a proc kills the mob, the mob's counter-attack is skipped. If a dodge/barkskin proc fires, the counter-attack is also skipped regardless.

**Proc damage scaling:** Damage and drain procs use `combat_engine.get_effective_max_hit(player)` — the same value used for normal attacks — so proc damage includes all equipped weapon bonuses. Upgrading from a grey dagger to a Legendary Staff increases both your normal hits and your proc hits.

### Combat System
`combat_engine.py → CombatEngine`

RuneScape-style accuracy formula:
```
attacker_roll = random(1, attacker.level × 10)
defender_roll = random(1, target.level × 8 + armor × 3)
hit = attacker_roll > defender_roll
damage = random(1, base_damage + weapon_stat_bonus)
```
- One tick = player attacks mob → class proc fires → (if mob alive and no dodge) mob counter-attacks → (if mob still alive) check telegraph queue
- **Open-world telegraphs:** after the mob counter-attacks, named mobs have a 20% chance and elite mobs a 15% chance to queue a telegraph for the next round — see the Telegraph section in Dungeon & Raid System for full details
- Equipment stats are summed via `_equipment_bonus(character, stat)`
- Minimum 1 damage on any hit (no frustrating 0-damage swings)
- **1.5s server-side rate limit** per player enforced via `_attack_times` dict in `main.py`

### Dungeon & Raid System
`dungeon_engine.py → generate_run(), resolve_round()`

Dungeons and raids are **instanced** — completely separate from the Zone system. Each run is a `DungeonRun` stored in-memory (`_dungeon_runs` dict) for the duration of the session. No persistence overhead; server restart abandons any active run, which is acceptable for single-player.

**Structure:**

| Type | Rooms | Party | Loot tier | Gate |
|---|---|---|---|---|
| Dungeon | 4 (trash → corridor → trash+elite → boss) | Player + 4 AI | `dungeon` (1.6×) | Level 10 |
| Raid | 7 (trash → corridor → trash+elite → mini-boss → corridor → deep trash → final boss) | Player + 9 AI | `raid` (2.8×) | Level 20 + GS ≥ 100 |

**Party composition** is role-aware and auto-assigned:
- Tank player (Warrior, Paladin) → 1 Healer + 3 DPS
- Healer player (Priest) → 1 Tank + 3 DPS
- DPS player (everyone else) → 1 Tank + 1 Healer + 2 DPS
- Raid → 2 Tanks + 2 Healers + 6 DPS (player + 9 NPCs)

**Round resolution** — one `POST /dungeon/attack` resolves the entire round simultaneously:
1. Player attacks the primary mob (`combat_engine.resolve_tick`)
2. Each living AI party member acts based on role:
   - **Healer**: heals the most injured combatant (player or party) if anyone is below 40% HP; else attacks
   - **Tank**: 75% attack, 25% taunt (reduces mob damage 20% for the round)
   - **DPS**: attacks, with 20% proc chance using the same `_CLASS_PROCS` table as open-world
3. All surviving mobs counter-attack a random living combatant (redirected to tank if taunt is active)
4. Room cleared / run cleared / wipe checks

**Raid boss phase 2 (enrage):** When the final boss drops to ≤30% HP, it enrages once — `boss.damage × 1.4`, flag stored on the run, pulsing red banner shown in the UI. The enrage persists until the boss dies.

**Telegraph (Dodge) Mechanic** — named and elite mobs telegraph powerful attacks that the player must actively dodge. This mechanic exists at every content tier, starting in the open world so players learn it before dungeons.

The telegraph fires after a mob's counter-attack: the `⚠ X winds up Y! DODGE!` message appears and a **DODGE button** with a 3-second countdown replaces (or overlays) the normal attack button. The player must click before the timer expires. Missing the window deals the full telegraphed hit automatically on the next attack call.

| Source | Trigger | Damage if missed | UI | Location |
|---|---|---|---|---|
| Named mob (open world) | 20% per round | 2× mob base damage | Yellow DODGE in target frame | `_pending_telegraphs` dict (in-memory) |
| Elite mob (open world) | 15% per round | 1.5× mob base damage | Yellow DODGE in target frame | `_pending_telegraphs` dict |
| Named boss (dungeon/raid) | 30% per round | 3× boss base damage | Yellow DODGE replaces ATTACK | `DungeonRun.pending_telegraph` |
| Elite mob (dungeon) | 20% per round | 2× mob base damage | Yellow DODGE replaces ATTACK | `DungeonRun.pending_telegraph` |
| Raid final boss (enraged) | 100% every round | **Instant kill** | Red pulsing DODGE replaces ATTACK | `DungeonRun.pending_telegraph` |

**State per tier:**
- **Open world** — stored in `_pending_telegraphs[player_id]` (in-memory dict in `main.py`). Cleared on mob death and player death. `/action/attack` accepts `dodged=bool`; dodge attacks bypass the 1.5s rate limit since they resolve a prior telegraphed hit, not a new offensive action.
- **Dungeon/raid** — stored on `DungeonRun.pending_telegraph`. Cleared on room clear. `/dungeon/attack` accepts `dodged=bool`.

**Teaching progression** — players encounter the mechanic first on named mobs in the open world (2× damage, survivable, low pressure), then on dungeon elites and bosses (2–3× damage, higher stakes), then on raid bosses with enrage one-shots. Each tier uses the same 3-second DODGE button with a draining countdown bar.

The sim always dodges optimally at every tier — open world `kill_mob` tracks `pending_telegraph` in the attack response and passes `dodged=True` on the next call; dungeon `do_dungeon_run` does the same from `run.pending_telegraph`.

**Loot:** On run cleared, `_roll_loot()` is called with `zone_tier="dungeon"` or `"raid"`. Dungeon: 1–2 drops (Epic base rate 15%, boosted by ×1.6 tier = 24% effective). Raid: 3 guaranteed drops. Loot is auto-equipped on drop if the stat total beats the currently equipped piece — old piece goes to inventory. All items are class-biased toward the player's class using the same slot-weight system as open world.

**Combat theater UI:** Dungeon/raid content replaces the scrolling chat log with a persistent layout — boss HP bar at top, one row per party member that updates in place each round, 3-line rolling log for dramatic moments only. No scroll, no noise.

### Loot System
`main.py → _roll_loot(mob_level, loot_table, char_class, zone_tier)`

- Rolls against the mob's loot table (chance per rarity tier)
- **Loot table order is best-to-worst** — the loop checks entries in order and returns the first rarity that passes. Legendary is checked before Epic, Epic before Rare, Rare before Common. This means the zone tier boost raises the probability of *better* rarities, not just Common. Named bosses are guaranteed Rare minimum (100% fallback), with real 40% Epic and 10% Legendary chances. If Common were checked first at a boosted 100%, it would block all higher rarities entirely.
- **Zone tier multiplier** multiplies each rarity's chance based on content type:
  - Open world: ×1.0 (baseline)
  - Dungeon: ×1.6 — meaningfully better quality distribution
  - Raid: ×2.8 — best loot in the game
- Slot selection is **class-biased** using `_CLASS_SLOT_WEIGHTS` — Mages get more off-hand/staff drops, Warriors get more armor/melee drops
- Weapon names are class-appropriate via `_CLASS_WEAPONS` — Mages get Staff/Wand/Tome, Rogues get Dagger/Blade/Shiv
- Adjectives are class-themed via `_CLASS_ADJECTIVES` — Warlocks get "Cursed/Fel/Void", Paladins get "Holy/Blessed/Sacred"
- **Auto-itemization:** if dropped item's stat total > currently equipped item's stat total in the same slot, it's automatically equipped. Old item goes to inventory. Both `auto_equipped` and `displaced_item` are returned in the attack response.
- **Bag drop comparison:** when an item goes to the bag instead of auto-equipping, the message includes a stat comparison vs what's currently equipped: `+5 damage (Uncommon) (equipped: +8 damage)`
- **Rare drop announcement:** named boss kills and Epic+ drops trigger a `★★★ RARE DROP ★★★` message in the combat log
- **Inventory UI:** bag slots are clickable — clicking a slot equips the item immediately. The hover tooltip shows the stat delta vs the currently equipped piece (`▲ +3 damage upgrade`, `▼ -1 downgrade`, or `▲ Empty slot — instant upgrade`). Items glow by rarity: green (Uncommon), blue (Rare), purple (Epic), orange (Legendary).

### Persistence Pattern
`vector_db.py → DBManager`

SQLite (`stdlib sqlite3`) stores two tables — `players` and `zones` — each with `id TEXT PRIMARY KEY` and `data TEXT` (JSON blob). Game objects are serialized via Pydantic `model_dump(mode='json')` before writing. `INSERT OR REPLACE` handles upserts atomically.

WAL journal mode means reads never block writes and vice versa — important because the simulation loop writes zones concurrently with player requests. On every server startup, `DBManager.__init__` runs `PRAGMA wal_checkpoint(TRUNCATE)` to flush any leftover WAL file from the previous session — no manual cleanup ever needed.

**Critical rule:** Zone state must be saved after **every** attack tick, not just on mob death. Without this, each new attack request would reload the mob at full HP from the last saved state — the mob appears to "heal" between hits.

Cache is a simple dict: `{id: (data, timestamp)}`. LRU eviction kicks in at 200 entries.

> **Why not LanceDB?** LanceDB is a vector database built for semantic similarity search. This game never uses vector search — players are identified by UUID, zones by ID. LanceDB added `lancedb`, `pandas`, `pyarrow`, `numpy`, and `tantivy` as heavy dependencies for zero benefit. SQLite is built into Python, orders of magnitude faster for key-value access, and trivially inspectable with any SQLite browser.

### Simulation Loop
`simulation.py → SimulationEngine`

Runs as an `asyncio.create_task` started at FastAPI startup (`@app.on_event("startup")`). Ticks every 10 seconds over all zones currently in the zone cache:
- Respawns dead mobs whose `respawn_at` Unix timestamp has passed
- **Regens alive mob HP to full** when no real player is present — prevents mobs from staying at low HP indefinitely after an incomplete fight
- Moves SimulatedPlayers to adjacent locations (20% chance per tick)
- Shifts weather (5% chance)
- Advances `time_of_day` (0.0–1.0, full cycle ~17 minutes)
- Has a 10% chance to call AI for an ambient zone atmosphere message — **only for zones with a real player currently present** (idle cached zones are skipped to avoid wasteful AI calls)

### Patrol Encounters
Every 45 seconds the frontend fires `POST /action/patrol_check/{player_id}` when the player is idle in a non-hub location with no live mobs. The backend has a 25% chance to spawn a wandering mob from the zone's existing mob pool (thematically consistent — no generic enemy types). The mob is added to the live location and the client shows `⚠ A [mob] crosses your path!`, then immediately starts auto-attacking — the player cannot ignore a patrol encounter.

Patrol spawns are skipped when:
- The current location is the hub (has NPCs)
- There are already live mobs at the location
- The location is a **path location** (`loc.resources` is non-empty) — paths are safe zones

### Harvesting & Fishing
Path locations between the hub and each POI have two passive gold sources available at all times — no quest required.

| Action | Commands | Cooldown | Item | Sell value |
|---|---|---|---|---|
| Harvest | `harvest` / `pick` / `herb` | 8 s | Named plant (`slot="material"`) | ~4 × level gold |
| Fish | `fish` / `angle` / `cast` | 12 s | Named fish (`slot="material"`) | ~4 × level gold |

- Backend checks `loc.resources[0]` (plant) / `loc.resources[1]` (fish) — no harvest on empty locations
- Blocked while any mobs are alive at the location (endpoint returns an error)
- Per-action cooldowns tracked server-side in `_harvest_times` / `_fish_times` dicts (separate from attack cooldown)
- Material items use `slot="material"` — not equippable, included in **Sell Junk**, sellable at any vendor
- The action bar shows **🌿 [PlantName]** and **🎣 [FishName]** buttons only on path locations, showing the actual resource name from the zone
- A gold-border pulse animates the terminal frame during both harvest and fishing (same style as forage gather)

### AI Client
`app/core/ai_client.py → LMStudioClient`

Wraps the `openai` SDK pointed at LM Studio's local server. Three methods:
- `generate_content(prompt, system_prompt, max_tokens)` → `str` — for NPC dialogue, world chat, ambiance
- `stream_content(prompt, system_prompt, max_tokens)` → async generator — for narrative streaming (thought-block stripping built in, 15s timeout)
- `generate_json(prompt, system_prompt, max_tokens)` → `dict` — for zone/mob generation; strips markdown fences before JSON parse

**`max_tokens` budget per call site:**
| Call | Limit | Reason |
|------|-------|--------|
| World chat reply | 45 | Casual 1-liner responses |
| Ambiance message | 40 | Single server notification |
| Location description | 60 | One atmospheric sentence |
| Mob / NPC description | 80 | Two vivid sentences |
| Death scene | 80 | Two dramatic sentences |
| NPC dialogue | 120 | 1–2 sentences + hint |
| Narrative stream | 150 | Short outcome description |
| Zone generation JSON | 700 | Full JSON structure needed |

Ambiance generation only runs for zones with a real player currently present — idle zones in cache are skipped.

All callers wrap in try/except and provide contextual fallbacks so the game works fully offline.

### World Chat
`main.py → /narrative/world_chat` + `_CHAT_PERSONALITIES`

World chat responses come from the zone's actual simulated players — not a static pool of names. The frontend sends `sim_player_names` (comma-separated names from `zone.simulated_players`) and the backend picks one to respond. Sim players sound like **real people at a keyboard playing the same game you are** — not fantasy NPCs.

Each sim player has a **stable personality** derived deterministically from their name hash:

| Personality | Behavior |
|---|---|
| Veteran | Seasoned, tired confidence. Dry humor. Drops useful tips occasionally. Never hyped. |
| Try-hard | Grinding hard, focused, slightly impatient. Talks about kills and progress. |
| Reckless | Dies a lot and finds it funny. Self-deprecating, chaotic, always doing something dumb. |
| Quiet | Few words, chill. Responds briefly when spoken to. Never volunteers information. |
| Complainer | Talks normally but complains about the game — mobs, loot, zone, whatever. Keeps playing anyway. |
| Helper | Laid back, helpful when it comes up naturally. Talks like a friend, not support staff. |

**Name addressing** — if your message contains a sim player's name, that player responds. Matching supports:
- Full name (`"thornwood"`)
- CamelCase first token (`"iron"` → IronGrog)
- Any unique prefix ≥ 3 chars at a word boundary (`"oz"` → Ozric, `"mist"` → MistRunner)

**Group responses** — if you say "you guys", "everyone", "anyone", etc., or address two names in one message, two sim players respond independently with a staggered delay.

**Sim players initiate chat unprompted** — a frontend interval fires every 30–60 seconds with a 60% fire chance, sending an ambient prompt to the backend. This makes the world feel alive without requiring player input.

**Session memory** — after every 10 player messages, the backend generates a 1-sentence summary of the conversation and prepends it to the system prompt as context for future replies. Cleared on zone travel.

**Inter-player references** — 25% of responses include a nudge to reference another sim player by name, creating natural banter.

**Ghost player prevention** — the endpoint only picks from the `sim_player_names` list passed by the frontend. If no sim players exist in the zone, no response is generated.

**Hallucination guards** — the system prompt explicitly constrains the model to: only name creatures that actually exist in the zone, never invent prices/spawn rates/lore/game mechanics, and never speak in-character as a fantasy NPC. Hard rules appear at the top of the system prompt so small local models read them before persona context.

History context keeps the last 10 lines, prioritising the last 3 lines from the responding player for continuity. Fallbacks cover contextual responses by mob / zone — they only fire when the player's message is actually about that topic.

**`/who` output** separates players at your current location (`[HERE]`) from those elsewhere in the zone, so you can see who's nearby at a glance:
```
- Thornwood (Lvl 4 Elf Rogue) [Sunken Graves] - BATTLING
- Ozric (Lvl 3 Human Mage) [Barrowmoor Hub] - EXPLORING
```

### Entity & Location Descriptions
`main.py → /describe/entity` + `/describe/location`

Every encounter and location transition triggers a short AI-generated description — one sentence to two sentences, plain prose, no stats or markdown.

- **Mob description:** fires the first time you engage a creature in combat. Describes appearance, movement, and threat. Elite and named rank modifiers are passed to the prompt so legendary bosses feel distinct from common mobs. Cached in-memory by name — each creature type is described once per session.
- **NPC description:** fires when you talk to an NPC. Covers appearance and one personality trait. Also cached by name.
- **Death scene:** fires when you are killed in combat or die while fleeing. A 2-sentence dramatic account of the fatal moment — always unique, never cached.
- **Location description:** fires when you move to a new node within a zone, or arrive at the hub location of a new zone. One atmospheric sentence grounded in the location name and static description. Cached by location name.

All four description types fall back silently if the AI is unavailable — no error is shown, the static game text is simply not supplemented.

### Scrolling Ticker (Loop Guidance)

The top-of-screen ticker scrolls 6 information slots continuously. The last two are dynamically driven by the player's exact loop stage:

| Stage | Progress slot | Next Step slot |
|---|---|---|
| Level 1–9 | `GS: 12 — LEVEL 4 / 10 NEEDED FOR DUNGEONS` | `GRIND QUESTS → REACH LEVEL 10 → ENTER DUNGEONS` |
| Level 10–19 | `GS: 85 — LEVEL 14 / 20 NEEDED FOR RAIDS` | `RUN DUNGEONS → BUILD GEAR SCORE → UNLOCK RAIDS AT LEVEL 20` |
| Level 20+, GS below threshold | `GS: 650 / 1000 REQUIRED TO ADVANCE` | `FARM RAIDS FOR EPIC GEAR → HIT 1000 GS → TYPE 'TRAVEL'` |
| GS threshold met | `✓ GS: 1009 / 1000 — ZONE COMPLETE` | `ZONE CLEARED — TYPE 'TRAVEL' TO ADVANCE` |

This means a brand-new player always knows what to do next without reading a guide. The ticker is the tutorial.

### Dynamic Action Bar & Number Hotkeys

The bottom toolbar is a **real-time contextual action bar** — its buttons and their assigned numbers rebuild every time the world state changes. Button order is always deterministic:

```
1       → Look
2…N     → Exits (one per available direction)
N+1…   → Attack buttons (one per unique alive mob type at current location)
…       → Turn In (only when quest giver is present + quests completed)
…       → Talk (one per quest-giver NPC at location)
…       → Shop / Sell (when vendor is present; Sell only if inventory non-empty)
…       → Gather (only when an active forage quest targets the current location)
…       → 🌿 Harvest (only on path locations — shows actual plant name)
…       → 🎣 Fish (only on path locations — shows actual fish species)
…       → Quests, Bags, Who
?       → Help (always last, always ?)
```

**Number hotkeys work two ways:**

| Method | How it works |
|---|---|
| Press digit with empty input | Fires the action immediately — no Enter needed |
| Type digit + Enter | Resolves the same map and executes the command |

**Context-awareness examples:**
- At a hub with a quest giver and vendor: Talk might be `4`, Shop `5`, Quests `6`
- In a combat area with two mob types: `attack Boar` = `3`, `attack Spider` = `4`, Quests shifts to `5`
- When a forage quest is active at your location: Gather appears before Quests, shifting everything after it
- While gathering / harvesting / fishing is in progress: the relevant button is disabled — pressing its number does nothing
- Typing a number into the command box mid-sentence is safe — hotkeys only fire when the input is blank

The hotbar action map is maintained in a `hotbarActionsRef` (a `useRef<Map<number, () => void>>`) that is rebuilt via `useEffect` whenever zone, player, combat target, or gathering/harvesting/fishing state changes. This keeps the keydown handler stateless and free from stale closure bugs.

**Visual feedback:**
- The terminal border pulses **red** while in combat (`autoAttackTarget` is set)
- The terminal border pulses **gold** while gathering, harvesting, or fishing
- Attack buttons show a draining red cooldown overlay during auto-attack
- Gather button shows a draining green overlay during the 8s gather cooldown
- The target frame (top-right) shows a colour-coded progress bar with a live countdown timer during resource actions:
  - Forage gather → yellow bar, 8s
  - Harvest → green bar, 8s, shows plant name
  - Fish → blue bar, 12s, shows fish species

### Minimap

The minimap radar (top of the right panel) shows live entity state for your current location:

| Blip | Meaning |
|---|---|
| Gold center dot | You |
| Blue inner ring | NPCs |
| Red mid ring | **Alive** mobs |
| Red mid ring (faded) | Dead mobs — respawning |
| Green-tinted outer ring | Sim players currently at your location |

Blips are arranged in deterministic rings so position doesn't change between ticks. Hovering a blip shows a tooltip with name and level. The time-of-day icon (🔆 / 🌙) reflects the current in-game time.

### Markdown Rendering

The terminal log renders inline markdown from AI-generated text:
- `**bold**` → gold/accent bold
- `*italic*` → soft italic
- `` `code` `` → monospace accent

Applied to all log lines including NPC dialogue, narrative stream output, and combat messages. Implemented in `renderLogText → parseMarkdown` in `page.tsx`.

### Quest System
Quests live on the Zone (`zone.quests`) and are accepted into `player.active_quests`. Progress tracking varies by type:
- **kill / gather:** client-side on mob death, synced to backend via `POST /quests/progress/{player_id}`. `gather` and `kill` are distinct quest types — `gather` requires a specific mob collectible and tracks via mob-name matching; `forage` uses the `gather` command and is completely separate.
- **hunt:** completes when any `target_is_named == true` kill is recorded (uses the backend flag, not mob name matching — immune to named mob rename variants)
- **explore:** auto-completes server-side in `POST /action/move` when `location_id == quest.target_id`; backend returns `explore_completed` array in the move response. **Once visited, explore quests for that location are never re-offered.**
- **forage:** completed by using the `gather` command (or clicking GATHER) while standing in `quest.target_id` location. Backend endpoint `/action/gather` with 8 s cooldown. Progress increments once per gather action. Completely separate from mob-kill gather quests — no crossover.

**Quests are repeatable.** All quest types can be re-accepted after completion — quests are grind content, not one-time story beats. NPCs always re-offer completed quests as long as they aren't currently active.

Turn-in happens at any hub quest giver NPC via `POST /quests/complete/{player_id}`, which awards XP and optionally an item reward. Zone travel is **not** unlocked by quest completion alone — it requires GS ≥ 1000. A player who has cleared dungeons and raids to hit that threshold will have naturally engaged with the zone's content. `"★ ZONE CLEARED!"` fires only when travel actually succeeds.

---

## Data Models
`backend/app/models/schemas.py` — authoritative source, all fields documented below.

| Model | Key Fields | Notes |
|---|---|---|
| `Player` | `level`, `hp/max_hp`, `xp/next_level_xp`, `gold`, `kills`, `deaths`, `inventory: List[Item]`, `equipment: Dict[str, Item]`, `active_quests`, `current_zone_id`, `current_location_id`, `visited_zone_ids`, `rested_xp`, `last_logout_time`, `dungeons_cleared`, `raids_cleared` | Equipment slots: `head chest hands legs feet main_hand off_hand`. `raids_cleared` drives open-world zone tier escalation (+3 levels per raid). `active_dungeon_run_id` tracks an in-progress run. |
| `Zone` | `id`, `name`, `locations: List[Location]`, `quests`, `simulated_players`, `time_of_day` (0–1), `weather`, `is_dungeon`, `is_raid` | Zone is the top-level open-world unit. Instanced dungeons use `DungeonRun`, not `Zone`. |
| `Location` | `id`, `name`, `description`, `npcs: List[NPC]`, `mobs: List[Mob]`, `exits: Dict[str, str]`, `resources: List[str]` | Exits map direction → location_id. `resources` is `[plant_name, fish_species]` for path locations, `[]` everywhere else. |
| `Mob` | `id`, `name`, `level`, `hp/max_hp`, `damage`, `loot_table`, `respawn_at` (Unix ts or None), `is_elite`, `is_named` | `respawn_at = None` means alive. Reset to `max_hp` and `respawn_at = None` when timer fires. |
| `NPC` | `id`, `name`, `role` (`quest_giver/vendor/trainer`), `dialogue`, `quests_offered`, `vendor_items` | Vendors have `vendor_items: List[Dict]` with `price` key |
| `Item` | `id`, `name`, `description`, `level`, `rarity`, `stats: Dict[str, int]`, `slot` | Equipment stats: `armor` or `damage`. Consumables use `slot = "consumable"` with effect encoded in stats: `{"heal_pct": 40}` or `{"xp_bonus_pct": 75, "xp_charges": 5}`. Harvest/fish drops use `slot = "material"` with `stats: {"value": 5}` — not equippable, included in Sell Junk. |
| `Quest` | `id`, `title`, `objective`, `quest_type` (`kill/gather/hunt/explore/forage`), `target_id`, `collect_name` (gather/forage quests), `target_count`, `current_progress`, `xp_reward`, `is_completed` | `forage` quests use `target_id` as a location ID (same as `explore`); progress via `/action/gather` not mob kills. |
| `SimulatedPlayer` | `id`, `name`, `race`, `char_class`, `current_location_id`, `status` | Background actors — not real players. `current_location_id` resolves to a location name in the `/who` output. |
| `DungeonRun` | `id`, `player_id`, `dungeon_name`, `dungeon_level`, `is_raid`, `room_index`, `rooms: List[DungeonRoom]`, `party: List[DungeonMember]`, `combat_log`, `status` (`active/cleared/wiped`), `boss_enraged`, `pending_telegraph` | Stored in-memory only (`_dungeon_runs` dict). Lost on server restart. `pending_telegraph` is a `PendingTelegraph` object (`name`, `damage_mult`, `is_oneshot`, `window_ms`) when a boss wind-up is active; `null` otherwise. |
| `DungeonRoom` | `index`, `name`, `mobs: List[Mob]`, `cleared` | Rooms 0–3 for dungeons (room 3 = boss), 0–6 for raids (room 6 = final boss). Corridor rooms have 1–2 light mobs. |
| `DungeonMember` | `id`, `name`, `char_class`, `role` (`tank/healer/dps`), `hp/max_hp`, `damage`, `last_action`, `is_alive` | AI party member. Stats derived from `ScalingMath` × role multiplier. Uses same `_CLASS_PROCS` table as players. |

---

## API Reference

All endpoints are in `backend/main.py`. Backend runs on `http://localhost:8000`.

### Player / Save-Load
| Method | Path | Description |
|---|---|---|
| `GET` | `/players` | List all saved characters as summary cards (name, level, race, class, kills, gold, etc.). Used by the load-game screen. Returns `{players: [...]}` sorted by level desc. |
| `GET` | `/player/{player_id}` | Load a specific character + their current zone. Returns `{player_id, player, zone, gear_score}`. `gear_score` is computed fresh each load for the HUD indicator. |
| `DELETE` | `/player/{player_id}` | Delete a single character and all zones in their `visited_zone_ids`. Clears their attack cooldown. Irreversible. |
| `POST` | `/player/create` | Create character. Params: `name`, `race`, `char_class`, `pronouns`. Returns `{player_id, player, zone}` |

### Zone
| Method | Path | Description |
|---|---|---|
| `GET` | `/zone/{zone_id}` | Fetch full zone state |
| `POST` | `/zone/travel/{player_id}` | Generate + travel to new **open-world** zone. Params: `is_dungeon` (deprecated — use `/dungeon/enter`), `is_raid`. Zone level = `player.level + (raids_cleared × 3)` — escalates with each raid tier. Requires: GS ≥ 1000 (fixed gate — not level-scaled). A player with 1000 GS has necessarily cleared dungeons and raids and engaged deeply with the zone. |

### Actions
| Method | Path | Description |
|---|---|---|
| `POST` | `/action/move/{player_id}` | Move to location. Param: `location_id` |
| `POST` | `/action/attack/{player_id}` | Attack mob. Params: `mob_name`, `dodged` (bool, default false — set true when player dodges a pending open-world telegraph; bypasses rate limit). Returns full combat delta + `pending_telegraph` (dict or null). |
| `POST` | `/action/flee/{player_id}` | Flee combat. 60% escape chance, counter-hit on failure. Param: `mob_name` |
| `POST` | `/action/equip/{player_id}` | Equip item from inventory. Param: `item_id` |
| `POST` | `/action/unequip/{player_id}` | Move equipped item back to bag. Param: `slot` (`head`, `chest`, `hands`, `legs`, `feet`, `main_hand`, `off_hand`) |
| `POST` | `/action/talk/{player_id}` | Talk to NPC. Param: `npc_name`. Returns `dialogue`, `offered_quests`, vendor fields |
| `POST` | `/action/use/{player_id}` | Use a consumable from inventory. Param: `item_id`. Enforces per-type cooldowns (`heal` 60 s, `xp` 5 min). Returns `player_hp`, `active_xp_buff`, `heal_cd`, `xp_cd`. |
| `POST` | `/action/rest/{player_id}` | Persist out-of-combat HP regen. Param: `hp` (clamped to `[1, max_hp]` server-side). Called by frontend timer every ~10 s while regenerating. |
| `POST` | `/action/gather/{player_id}` | Progress active forage quests targeting current location. 8 s cooldown. Returns `messages`, `quest_updates`. |
| `POST` | `/action/harvest/{player_id}` | Harvest a plant from a path location (`loc.resources[0]`). 8 s cooldown. Blocked if alive mobs present. Returns `item`, `messages`. |
| `POST` | `/action/fish/{player_id}` | Fish at a path location fishing hole (`loc.resources[1]`). 12 s cooldown. Blocked if alive mobs present. Returns `item`, `messages`. |
| `POST` | `/action/patrol_check/{player_id}` | 25% chance to spawn a wandering zone-mob in current location (non-hub, no live mobs, non-path only). Returns `{ patrol, mob_name, mob_level }`. |
| `POST` | `/action/login/{player_id}` | Compute and credit rested XP accumulated since last logout. Called on character load. Returns `rested_xp`, `rested_xp_cap`. |
| `POST` | `/action/logout/{player_id}` | Stamp logout time for rested XP calculation. Called via `sendBeacon` on `beforeunload`. |

### Quests
| Method | Path | Description |
|---|---|---|
| `POST` | `/quests/accept/{player_id}` | Accept quest. Param: `quest_id` |
| `POST` | `/quests/progress/{player_id}` | Sync kill/gather progress. Params: `quest_id`, `progress` |
| `POST` | `/quests/complete/{player_id}` | Turn in completed quest. Param: `quest_id`. Returns XP + item reward |

### Vendor
| Method | Path | Description |
|---|---|---|
| `GET` | `/vendor/{player_id}` | Get vendor stock + player gold. Param: `npc_name` |
| `POST` | `/vendor/buy/{player_id}` | Purchase item. Params: `npc_name`, `item_id` |
| `POST` | `/vendor/sell/{player_id}` | Sell inventory item. Price = `item.level × stat_total × 2`. Param: `item_id` |
| `POST` | `/vendor/sell_junk/{player_id}` | Sell all Common-rarity non-consumable items at once. Returns `gold_gained`, `sold_count`, `player_gold`. |

### Dungeon / Raid
| Method | Path | Description |
|---|---|---|
| `POST` | `/dungeon/enter/{player_id}` | Create an instanced dungeon or raid run. Param: `is_raid` (bool). Gates: lv10/lv20 + GS≥100 for raids. Returns full `DungeonRun`. |
| `POST` | `/dungeon/attack/{run_id}` | Resolve one full combat round (player + all AI party members + mob counter-attacks). Params: `player_id`, `dodged` (bool, default false — set true when player successfully dodges a telegraph). Returns `run`, `round_log`, `room_cleared`, `run_cleared`, `wiped`, `xp_gained`, `gold_gained`, `loot`. |
| `POST` | `/dungeon/advance/{run_id}` | Move to the next room after the current one is cleared. Param: `player_id`. |
| `POST` | `/dungeon/flee/{run_id}` | Abandon the run. Clears `player.active_dungeon_run_id`. Param: `player_id`. |

### Admin / Dev Tools
| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/reset` | Wipe all persisted game data (players + zones). Full clean slate — no server restart needed. Dev/testing only. |
| `POST` | `/admin/boost/{player_id}` | **Dev/sim only.** Instantly set the player to `level` with class-appropriate stats and preset gear. Params: `level` (1–100, default 10), `preset` (`dungeon` or `raid`, default `dungeon`). `dungeon` → lv10, ~94 GS (Legendary weapon + Epic/Rare/Uncommon armor). `raid` → lv20, ~280 GS (Rare weapon + Uncommon armor, mirrors late-dungeon phase). Returns `{level, hp, damage, gear_score, gold}`. |

### Narrative
| Method | Path | Description |
|---|---|---|
| `GET` | `/narrative/stream/{player_id}` | Streamed AI narrative for any action. Param: `action` |
| `POST` | `/narrative/world_chat` | AI world chat response. Params: `message`, `player_name`, `player_bio`, `zone_name`, `location_name`, `weather`, `mobs_nearby`, `time_of_day`, `active_quests`, `sim_player_names` (comma-separated names of zone's sim players — used to pick the responding character) |
| `GET` | `/describe/entity` | AI description for a mob or NPC. Params: `name`, `entity_type` (`creature`/`npc`/`death`), `is_elite`, `is_named`, `zone`. Cached by name except death scenes. |
| `GET` | `/describe/location` | AI atmospheric sentence for a location. Params: `name`, `loc_description`, `zone`. Cached by location name. |

---

## Save / Load System

All persisted state lives in `backend/data/mud.db` (a single SQLite file). Multiple characters can be saved simultaneously — each with their own zones, quests, and inventory.

### How character data is organized

Every character owns their world data via `visited_zone_ids: List[str]` on the `Player` model. This field is populated at creation (`[initial_zone.id]`) and appended each time the player travels to a new zone. It is the source of truth for "which zones belong to this character" and drives per-character cleanup on delete.

```
Player record  ──── visited_zone_ids ────► Zone records (N zones per character)
                                            (starter zone, all traveled zones)
```

The SQLite tables are:
| Table | Row key | Contents |
|---|---|---|
| `players` | `id` (player_id UUID) | Full player state — stats, inventory, equipment, quests, zone IDs |
| `zones` | `id` (zone_id UUID) | Full zone state — locations, mobs (with respawn timers), NPCs, quests |

### Load-game screen

When the player presses Enter at the title screen, the frontend calls `GET /players`. If saved characters exist, it shows a structured card for each one (name, race/class, level, HP, gold, kills, deaths, quests completed) and waits for the player to type a number to continue that character, or `new` to create a fresh one. Selecting a character calls `GET /player/{player_id}` which returns the full player + their current zone, and the game resumes exactly where they left off.

### Deleting game data

**In-app (while server is running):** A **⚠ Reset** button lives below the character biography in the left side panel during gameplay. Clicking it opens a 3-step confirmation flow:

1. **⚠ Reset** — opens the choice screen
2. **Choose what to delete:**
   - *Character name* — deletes only this character and all their zones (`DELETE /player/{player_id}`)
   - *All Characters* — wipes everything (`POST /admin/reset`)
3. **Final confirmation** — per-choice warning before executing ("Delete [Name] forever?" or "Wipe every character?"), with a cancel option at every step

**CLI script (server stopped):**
```powershell
# From the repo root:
python scripts/reset_data.py
```

### Smoke Test

`scripts/smoke_test.py` runs a fast happy-path integration test (under 60 seconds) against a live backend. It covers every major system in order, creates a throwaway character, and deletes it when done.

**What it checks (17 sections):**
character creation → zone topology (hub/path/POI structure) → movement → harvest & fish (cooldowns + material slot) → combat (attack, cooldown 429, kill, XP) → patrol check → login/logout rested XP → player list/load → NPC talk → quest accept → vendor → sell junk → dungeon gate (blocked at level 1) → zone travel gate (blocked at low GS) → describe endpoints

```powershell
# Terminal 1 — start the backend
cd backend
.\venv\Scripts\activate
uvicorn main:app --reload --port 8000

# Terminal 2 — run the test
cd backend
.\venv\Scripts\activate
pip install requests  # first time only — not in requirements.txt
python ..\scripts\smoke_test.py
# or against a different port:
python ..\scripts\smoke_test.py --base http://localhost:8001
```

Exits 0 on all checks passing, 1 on any failure. Run it after any backend change — if something regresses, the failing section name tells you exactly where to look.

---

### Headless Simulation (`sim_run.py`)

`scripts/sim_run.py` plays the **full progression meta** automatically — no browser, no clicking. It follows the same optimal loop a knowledgeable player would: talk to NPCs → accept all quests → harvest/fish every path → kill all mobs at each POI → forage when a quest targets the location → turn in at hub → sell junk → rebuy potions → repeat. It drives through all three content tiers before stopping.

Because the sim calls the exact same backend endpoints as the browser, it **is** the real game — the backend doesn't know whether the caller is Next.js or a Python script. Combat math, XP gains, loot rolls, quest tracking, dungeon party AI, and level-up logic are all identical. The only thing the sim skips is frontend rendering.

**Three-phase meta loop:**

| Phase | Goal | Stops when |
|---|---|---|
| Open world | Kill quests, harvest/fish, forage, level up | Level 10 reached |
| Dungeon loop | Dungeon runs back-to-back (no open world sweeps) | GS ≥ 100 AND level 20 |
| Raid loop | Run raids, attempt zone travel after each clear | Zone travel succeeds (GS ≥ 1000) |

**Use the sim for:**
- Verifying backend changes without touching the browser
- Checking balance — XP curve, kill counts per level-up, loot drop rates, GS progression
- Catching regressions after any change to `main.py`, `dungeon_engine.py`, or `scaling_math.py`
- Watching the loop play out and checking that numbers feel right

```powershell
# Terminal 1 — start the backend
cd backend
.\venv\Scripts\activate
uvicorn main:app --reload --port 8000

# Terminal 2 — run the sim
cd backend
.\venv\Scripts\activate
pip install requests  # first time only — not in requirements.txt (backend uses httpx)

# Full meta run (open world → dungeons → raids → zone travel)
python ..\scripts\sim_run.py

# Quick smoke check — one sweep + one dungeon, then stop
python ..\scripts\sim_run.py --quick

# Skip Phase 1 — boost to lv10 ~94 GS, jump straight to dungeon loop
# Saves ~35-50 min of open-world grind
python ..\scripts\sim_run.py --skip-to-dungeon

# Skip Phases 1+2 — boost to lv20 ~280 GS, jump straight to raid loop
# Saves ~60-90 min — use this to test raids and zone travel directly
python ..\scripts\sim_run.py --skip-to-raid

# Keep the character after the run for manual inspection in-browser
python ..\scripts\sim_run.py --no-cleanup

# Custom name + different port
python ..\scripts\sim_run.py --name BotWarrior --base http://localhost:8001
```

Every log line is timestamped with seconds elapsed since sim start. Each section header shows how long the previous section took.

**Milestone timeline** — the final summary always reprints every phase transition with its timestamp, regardless of how much the terminal scrolled. Example:

```
══════════════════════════════════════════════════════════════════
  Total time: 923.4s (15.4 min)
  ── Milestone Timeline ──────────────────────────────────
  [00:00]  SKIPPED TO RAID — entering Phase 3              Lv20  GS   280  D=0  R=0
  [02:31]  ZONE TRAVEL SUCCESS — Phase 3 Complete          Lv22  GS  1084  D=0  R=2
══════════════════════════════════════════════════════════════════
```

Full-run example (no skip flags):
```
  [00:00]  PHASE 1 → 2: Open World Complete                Lv10  GS    94  D=0  R=0
  [18:44]  PHASE 2 → 3: Dungeon Phase Complete             Lv20  GS   134  D=9  R=0
  [31:07]  ZONE TRAVEL SUCCESS — Phase 3 Complete          Lv21  GS  1102  D=9  R=3
```

Columns: `[MM:SS]  event  Lv=player level  GS=gear score  D=dungeons cleared  R=raids cleared`

**Per-run analytics box** — printed after every dungeon and raid clear (or wipe):

```
  ┌─ RAID 2 analytics ─────────────────────────────────
  │  CLEARED  ·  34 rounds  ·  ~87 dmg/round  ·  +4200 XP  ·  +340g
  │  Telegraphs 3  ·  Dodges 3  ·  Party deaths 1
  │  Procs: 4×FURY  3×SHOT  2×MEND  1×DRAIN
  │  Loot:  1×Epic  2×Rare
  └──────────────────────────────────────────────────────
```

**Aggregate analytics section** — printed before FINAL CHARACTER STATE, totals across all runs of each type:

```
  ── DUNGEON aggregate (9 runs) ────────────────────────────────
  Rounds 218  ·  ~62 dmg/round  ·  +38400 XP  ·  +2870g
  Telegraphs 14  ·  Dodges 14  ·  Party deaths 6
  Procs: 31×FURY  18×SHOT  12×MEND  9×GRACE  6×DRAIN
  Loot:  2×Epic  15×Rare  9×Uncommon

  ── RAID aggregate (3 runs) ────────────────────────────────────
  Rounds 97  ·  ~118 dmg/round  ·  +21600 XP  ·  +1640g
  Telegraphs 11  ·  Dodges 11  ·  Party deaths 4
  Procs: 14×FURY  9×SHOT  7×MEND  4×DRAIN
  Loot:  3×Epic  6×Rare
```

**Reading the output — things to watch for:**

| Signal | What it means |
|---|---|
| Red `✗` lines | Hard error — endpoint returned unexpected status or request failed |
| `Party wiped!` | Dungeon party undertuned for zone level, or damage scaling off |
| Level-ups very fast or very slow | XP curve drifted — check `ScalingMath.get_xp_required` |
| `Sold 0 junk` after harvest+fish | Material items not reaching inventory, or `sell_junk` slot filter broken |
| `Dungeon entry failed` unexpectedly | Level gate in `/dungeon/enter` too strict, or player level not persisting |
| `Loot: []` on dungeon/raid clear | `_roll_loot` not firing — check `dungeon_engine.py` |
| No path locations | World generator path insertion broke for this zone type |
| `Too many empty sweeps` | Mob respawn timer too long or respawn logic broken |
| `Hit dungeon cap` without reaching GS 100 | Dungeon loot not scaling GS fast enough — check loot tier multipliers |
| `Hit raid cap` without zone travel | Raid loot not pushing GS over zone travel threshold |
| `Telegraphs N  ·  Dodges 0` | Telegraph mechanic broken — sim should always dodge, check `pending_telegraph` in response |
| `Party deaths` very high | Mob damage overtuned for party HP pool at that level |
| `~dmg/round` much lower than expected | Party members not contributing damage — check `_member_as_mob` or role logic |

If something looks off, paste the full terminal output — the timestamps make it easy to spot where time is being spent unexpectedly.

### What gets deleted per operation
| Operation | Deletes |
|---|---|
| `DELETE /player/{id}` | That player's row + all zone rows in their `visited_zone_ids` |
| `POST /admin/reset` | All rows in `players` and `zones` tables — full wipe |
| `scripts/reset_data.py` | Deletes `backend/data/mud.db` entirely — full wipe |

The `backend/data/` directory is listed in `.gitignore` — it is never committed.

---

## Getting Started

### Prerequisites
- Node.js 18+
- Python 3.10+
- [LM Studio](https://lmstudio.ai/) with a model loaded and local server started on port 1234

> **✨ Recommended Model: Qwen3.5** — Qwen3.5 (9B recommended) is the best fit for this game. It handles JSON generation, NPC dialogue, world chat, and narrative summaries well at low token budgets, runs fast on consumer hardware, and follows system prompt constraints reliably. Load it in LM Studio and set: `$env:LM_STUDIO_MODEL="qwen3.5-9b"` (use the exact model ID shown in LM Studio).

> **⚡ LM Studio Performance Tip:** Set **Thinking Mode → Off** in your loaded model's settings before starting the local server. Thinking/reasoning mode causes the model to emit large internal monologue blocks before every response, dramatically increasing latency. With thinking off, responses arrive 3–5× faster. The game already strips thought blocks from streams as a safety net, but disabling it at the model level is the correct fix.

### Backend
```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend
```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LM_STUDIO_MODEL` | `local-model` | Model identifier passed to LM Studio API. LM Studio accepts any string and routes to the currently loaded model. Set to the exact model name if using multiple models. |

Set via PowerShell before starting the backend:
```powershell
$env:LM_STUDIO_MODEL="llama-3.2-3b-instruct"
uvicorn main:app --reload
```

The game runs fully without LM Studio — AI calls fail gracefully and fall back to contextual template responses that reference real quest/mob/zone data.

---

## Simulation-Driven Balance Methodology

This project uses `sim_run.py` not just as a test harness but as a **balance validation tool** — a methodology that applies to any game system, not just this one.

### The core idea

Most games are balanced through playtesting: humans play it, notice when something feels wrong, and adjust. This works but has a ceiling. Human testers have limited time, can't exhaustively cover every level range, and can't hold a spreadsheet in their head while playing. The result is that most indie games ship with progression curves that feel fine in the 10-hour window that was tested, and break apart at hour 30.

The sim solves this by automating the playtesting loop. One `--skip-to-raid` run completes three full raids, measures exact GS gain per raid, dodge success rates, DPS scaling across level ranges, and telegraph frequency — in under 10 minutes. The same run would take a human 60–90 minutes with worse data quality.

### What the sim proved during development

Running the sim against this game revealed specific, quantifiable balance findings:

| Finding | Measurement | Fix |
|---|---|---|
| Zone travel GS gate was a treadmill | Player leveled through raids → gate scaled up → gate never reachable | Replaced `level × 50` with flat 1000 GS |
| GS curve from raids | Raid 1: +216 GS · Raid 2: +231 GS · Raid 3: +276 GS | Confirmed 3 raids to zone travel — correct pacing |
| Boss telegraph frequency | Room 7 boss fired 3–4 normal telegraphs + 2–4 ANNIHILATEs per run | Identified potential repetition — cap normal telegraphs before enrage |
| DPS scaling | Raid 1: 648 dmg/round → Raid 2: 944 → Raid 3: 1830 | Level scaling confirmed working (party stats compound with player level) |
| Party deaths | 0 across 3 full raids | Healer output correctly calibrated against mob damage for this level range |
| Dodge mechanics | 100% dodge rate at every tier (open world, dungeon, raid) | Sim always dodges optimally — validates telegraph system end-to-end |

### Why this approach generalizes

The same methodology applies to any game with quantifiable systems:

- **Any MMORPG** — run the progression sim 100 times to find what % of players would hit a wall at each tier, before launch, not after
- **Card games / tactics** — simulate thousands of matches to find which decks/factions dominate, before the community discovers the broken combo
- **Idle games** — simulate 1000 hours of idle progress in 5 minutes to verify the late-game prestige curve doesn't collapse
- **Roguelikes** — automated runs per class to verify class power parity without bias from skilled/unskilled testers

The key property that makes it work: **the sim calls the same endpoints as the real client**. There's no separate "sim mode" in the backend. The sim is just a faster player. This means sim results are guaranteed to reflect what real players will experience — not what a mocked/simplified model predicts.

### Signals worth tracking in any sim

Based on what this sim revealed as most useful:

| Metric | Why it matters |
|---|---|
| GS per run (or equivalent progression unit) | Tells you how many runs before the next gate — the core time-to-progression number |
| DPS / damage output per round | Catches content that's too fast (boring) or too slow (frustrating) |
| Telegraph → dodge ratio | Any divergence means the mechanic is broken or un-learnable |
| Party deaths per run | Calibrates healer/tank output against mob damage |
| Rounds per room | Rooms with very different counts indicate mob HP outliers |
| Loot by rarity over N runs | Tells you the actual drop distribution, not the intended one |

### The design insight

Simulation isn't just for AAA studios with dedicated tools teams. A 1000-line Python script calling your own API can catch weeks of post-launch balance complaints before a single real player touches the game. The investment is front-loaded but it pays back every time you touch a number — instead of "this feels about right", you have "DPS grew 2.8× from raid 1 to raid 3, which matches the level scaling formula."

---

## Extending the Game

### Adding a new stat or equipment slot
1. Add the slot key to `Player.equipment` default dict in `schemas.py`
2. Add the slot name to `_ITEM_NAMES` in `main.py`
3. Add weights for it in `_CLASS_SLOT_WEIGHTS` in `main.py`
4. Frontend paperdoll renders equipment slots dynamically from `player.equipment` — it will appear automatically

### Adding a new character class
1. Add to `CLASS_STATS` in `main.py` (hp_mult, damage_mult)
2. Add to `_CLASS_SLOT_WEIGHTS`, `_CLASS_WEAPONS`, `_CLASS_ADJECTIVES` in `main.py`
3. Add flavor text to `CLASS_FLAVOR` in `frontend/app/page.tsx`
4. Add a portrait image to `frontend/public/assets/portraits/{classname}.png`

### Adding a new NPC role
1. Add the role string to `NPC.role` type hint comment in `schemas.py`
2. Handle the role in `main.py → talk_to_npc` (currently handles `quest_giver` and `vendor`)
3. Add a button style for the new role in the side panel NPC section in `page.tsx`

### Adding a new zone template (starter content)
Edit the `templates` list in `world_generator.py → generate_zone()`. Each template needs: `name`, `desc`, `hub` (name, description tuple), `pois` (3 locations), `npc` (name, greeting tuple), `quests` (list of `(title, type, mob_or_None, count, collect_name_or_None)` tuples).

### Changing the combat formula
All hit/damage math is in `combat_engine.py`. `scaling_math.py` controls the HP/damage/XP curves per level. These two files are the only places to touch for balance changes.

### Swapping the LLM provider
Replace `ai_client.py` with any provider that supports the same three method signatures (`generate_content`, `stream_content`, `generate_json`). The `openai` SDK client can be pointed at any OpenAI-compatible endpoint by changing `base_url`.

---

## Design Decisions

Answers to questions a senior reviewer would ask when reading the codebase.

### Why one `main.py` instead of split routers?

Every system here is intentionally coupled — loot depends on player class, level-up logic depends on combat result, combat depends on equipment stats. Splitting into separate modules creates import chains between tightly-coupled systems without any real isolation boundary. The benefit of router separation (team onboarding, independent deployment) doesn't apply to a solo project.

`dungeon_engine.py` was extracted because it's genuinely separate — it owns a full lifecycle (enter → attack → advance → flee) and never needs to reach back into `main.py`. The loot roller and level-up helpers inside `main.py` are 30-line functions that only make sense in the context of the endpoint calling them. Moving them to `app/core/systems/loot.py` saves zero cognitive overhead and costs an import chain.

The rule applied: split when a module boundary creates real isolation, not just file separation.

### Why SQLite instead of Postgres?

No concurrent writes from multiple servers, no relational queries — players are fetched by UUID, zones by UUID. SQLite is built into Python, requires no installation, ships as a single inspectable file, and handles the write volume of a single-player game trivially. The LRU cache in front of it means most reads never touch disk. Postgres adds a process, a connection pool, and a migration story for zero gameplay benefit.

### Why in-memory dungeon runs instead of persisted?

Dungeon runs are session-scoped by design. If the server restarts mid-run the player loses progress and starts over — acceptable for single-player. Persisting runs would require a DB write every attack round (to handle crashes mid-run), which adds latency to the tightest loop in the game and complicates the data model. The `_dungeon_runs` dict is fast, simple, and fits the ephemeral nature of instanced content.

### Why a flat GS 1000 gate instead of level-scaled?

The original gate was `player.level × 50`. Because players level up by clearing raids (not just open world), the gate kept rising with each clear — a treadmill where the requirement outpaced the reward. Caught and fixed by simulation: the sim validated that a flat 1000 GS gate requires exactly 3–5 raid clears at level 20, is predictable, and can be communicated clearly to players via the HUD ticker. A level-scaled gate is impossible to explain in one line of UI text.

### Why local LLM instead of a cloud API?

Zero latency variance, zero cost per token, works fully offline, no rate limits, no API key to manage or rotate. The content generated (zone names, mob descriptions, NPC dialogue) doesn't need frontier model capability — a 9B parameter model running locally produces output indistinguishable from GPT-4 for this use case. LM Studio's OpenAI-compatible endpoint means switching to a cloud provider is one `base_url` change in `ai_client.py`.

### Why save zone state after every attack tick, not just on mob death?

If zone state is only saved on mob death, the next attack request loads the mob from the last saved state — at full HP. Every hit except the kill appears to do nothing, making combat feel broken. This is the single most important rule in the persistence layer and the reason `vec_db.save_zone(...)` is called unconditionally at the end of every attack handler, not inside the `if mob.hp <= 0` branch.

### Why does the loot table check rarities best-to-worst?

If Common were checked first with a raid-tier multiplier, it would pass at 100% chance on every roll — blocking all higher rarities entirely. By checking Legendary → Epic → Rare → Common in order, the tier multiplier raises the floor of *quality* rather than just increasing volume. Named bosses with a 100% Common fallback never return Common because Rare is checked first and always passes.

### Why are `requests.Response` objects checked with `is not None` instead of `if r`?

Python's `requests` library makes `Response` objects falsy for 4xx/5xx status codes — `bool(response)` returns `False` when `status_code >= 400`. Using `if r` on a 400 response silently discards the error body and falls through to the `else "no response"` branch. This was a real bug: `try_zone_travel()` was logging `"Zone travel blocked: no response"` instead of the actual backend error message. The fix is always `if r is not None` when checking for response presence vs. `if r` when checking for HTTP success.

### Why does the sim always dodge optimally?

The sim is a balance tool, not a difficulty test. Dodging every telegraph removes player skill from the equation and isolates the underlying math — party DPS, healer throughput, mob damage, GS curve. A sim that occasionally fails to dodge would add variance that makes balance signals harder to read. The 100% dodge rate across all tiers confirmed the telegraph system is wired correctly end-to-end; difficulty tuning (what happens to real players who miss) is a separate concern validated in the browser.

### Why does loot deduplication retry instead of skip?

Raid bosses guarantee 3 drops. With 7 equipment slots and random slot selection, the probability of rolling 3 unique slots in one batch is only ~61% — about 4 in 10 raids would deliver 2 items instead of 3 if a collision just skips. The loot roller retries up to 5× per drop to find an unoccupied slot, which makes the guarantee meaningful. Five retries is enough: the probability of failing all 5 across 7 slots approaches zero.

---

## Known Constraints & Gotchas

**Zone must be saved after every attack hit, not just on mob death.**
The backend loads fresh zone state on each request. If you only save on mob death, every subsequent attack sees the mob at full HP again (the healing bug). This is why `vec_db.save_zone(...)` is called unconditionally at the end of the attack handler.

**`model_dump(mode='json')` is required for all Pydantic v2 serialization.**
Standard `dict()` or `.model_dump()` without `mode='json'` will leave Python `Enum` objects in the output that SQLite's JSON serializer cannot handle cleanly.

**Schema changes require clearing `backend/data/mud.db`.**
If you add a required field to a Pydantic model, existing JSON blobs in the DB won't have it. Pydantic will raise a `ValidationError` when loading old records. Clear the DB after significant model changes (`python scripts/reset_data.py` or delete the file).

**Frontend state is a local mirror, not the source of truth.**
The backend DB is authoritative. The frontend applies optimistic updates (local HP/XP changes) from attack response deltas. For full sync, the zone is polled every 10s via the ticker. If you notice desync, check that the backend is saving state and the ticker is running.

**Simulation loop only ticks zones in the in-memory cache.**
`simulation.py` iterates `vec_db._zone_cache.keys()`. A zone is only cached after it's first loaded in a request. Zones that have never been loaded won't be simulated. This is intentional — there's no need to simulate zones no one is in.

**Attack cooldown is in-memory only (`_attack_times` dict).**
Restarting the server resets all attack cooldowns. This is fine for a single-player game but would need Redis or similar for multi-player.

## Future Potential Updates

Ideas that fit the design philosophy (frictionless, solo-friendly, endlessly progressive) but are large enough to be their own milestone.

### Cooking System

Raw fish (from fishing holes) and harvested plants (from path locations) would become ingredients for cooked food. A `cook [item]` command at any campfire/hub would convert them into consumables: *Cooked Silverscale* grants a 30-minute out-of-combat HP regen buff (+4% per second instead of +2%). Cooked food would not stack with Healing Potions but would free up potion charges for combat use. This creates a natural gold/resource trade-off — sell materials directly, or spend 10s cooking for a quality-of-life regen buff.

### AI Party Dialogue & Loot Reactions

Party members already act intelligently in combat (role-aware healing, taunts, procs). The next layer is making them *feel* like real companions: contextual one-liners during fights (*"Watch the boss's enrage!"*), celebrating crits, reacting to rare drops (*"Finally, a chest piece upgrade!"* or *"All yours — can't use that."*). This would use a single combined LLM call per round (one line for the most interesting party action) rather than per-member, keeping token usage comparable to the current open-world chat.

### Achievement System

Persistent milestone tracking — first boss kill, 100 kills in a zone, first Legendary drop, first raid clear — shown as a pop-up banner and stored on the player record. Achievements give small permanent stat bonuses (e.g. +5 max HP for "First Blood") to reward completionist play without gating progression behind them.

### Session Stats Screen

A score-screen shown on zone exit / tab close: kills this session, gold earned, best drop, XP gained, damage dealt. Creates the "just one more run" feeling and gives a natural stopping point. Zero backend changes needed — all data is already tracked in player state.

---

## Spin-off Concept: Terminal Idle Game

The headless simulation (`sim_run.py`) already plays the full meta automatically — open world sweeps, dungeon runs, raids, zone travel — and prints a live colourised feed of everything that happens. It turns out this is a genuinely enjoyable thing to watch while doing something else, like reading or watching YouTube.

The natural extension of this is a **standalone terminal idle game**: a separate project that takes `sim_run.py` as its foundation and turns it into the actual product. The player's role shifts from playing to **directing and watching** — you pick your class, set some preferences (aggressive/cautious, gold-focused/XP-focused), and then watch a rich terminal feed narrate your character's adventure while you idle. World chat would be the primary interaction point — you can message your sim party, react to drops, or just lurk while the game plays out.

What makes it potentially unique: most idle games are number dashboards. This would be a **narrative idle game** — every kill has a description, every dungeon room tells a story, every rare drop gets called out. The AI layer that makes this MUD feel alive is exactly what would make an idle version feel different from Progress Quest or any clicker.

Since the backend is already completely decoupled from the frontend, this would be a **separate repo** that reuses the same backend as-is and replaces the Next.js frontend with an enhanced terminal renderer — likely a Python `rich` or `textual` UI that displays party HP bars, a scrolling combat log, and a world chat input, all in the terminal.

The sim as it exists today is already ~80% of the way there technically. The gap is just the UI layer and the shift in design intent from "testing tool" to "product."

---

## Steam / Electron Distribution (Future)

The intended distribution path is an **Electron wrapper on Steam** — the game ships as a standalone desktop app with no external server dependency. The AI world chat gimmick requires a local LLM, so the bundle needs to include a model and a way to run it.

### Architecture

```
Electron shell
  ├── Next.js frontend     (bundled as static files, served by Electron)
  ├── FastAPI backend       (spawned as a child process on app launch)
  ├── Python runtime        (bundled via PyInstaller — no Python install required)
  └── LM Studio / llama.cpp (bundled inference engine + Qwen3.5 9B model weights)
```

The Electron main process becomes the orchestrator: on launch it starts the FastAPI backend subprocess and the inference engine subprocess, waits for both to be healthy (poll `http://localhost:8000/docs` and `http://localhost:1234/v1/models`), then opens the game window pointing at the local Next.js build.

### Bundling the Python backend

Use **PyInstaller** to produce a single-folder executable from the FastAPI app:
```bash
pip install pyinstaller
pyinstaller --onedir backend/main.py --name mud-server \
    --add-data "backend/app:app" \
    --hidden-import uvicorn.lifespan.on
```
The resulting `dist/mud-server/` folder (or `.exe` on Windows) gets included in the Electron `resources/` directory. Electron spawns it on startup and kills it on quit via `app.on('before-quit')`.

### Bundling the LLM

Two options for the inference engine:

| Option | Pros | Cons |
|---|---|---|
| **Bundle LM Studio** | Familiar, has a GUI for settings, supports many backends | Large binary (~200 MB), not headless-friendly |
| **Bundle llama.cpp server** | Tiny binary (~10 MB), fully headless, OpenAI-compatible API on port 1234, same interface the game already uses | No GUI — thinking mode must be disabled via a launch flag |

**Recommended: llama.cpp server** (`llama-server` binary). It exposes the same OpenAI-compatible REST API at `http://localhost:1234/v1` that the game already targets, so zero backend changes needed. Thinking mode is disabled at launch via `--no-context-shift` or a sampler flag — not a user setting.

**Qwen3.5 9B** is the target model. At Q4_K_M quantisation it is ~5.5 GB — acceptable for a Steam game download. Include the `.gguf` file in `resources/models/`.

Launch command Electron would run:
```bash
llama-server \
  --model resources/models/qwen3.5-9b-q4_k_m.gguf \
  --port 1234 \
  --ctx-size 4096 \
  --n-predict 256 \
  --no-mmap \
  --thinking false        # disables <think> blocks — Qwen3.5 specific flag
```

### First-run onboarding

On first launch (detected by absence of `mud.db`), show an onboarding screen before the title:

1. **Hardware check** — detect VRAM via `nvidia-smi` or Metal API and recommend quality level:
   - ≥ 8 GB VRAM → full Q4_K_M (best quality)
   - 4–8 GB VRAM → Q3_K_M (slightly lower quality, same feel)
   - CPU only → Q2_K or redirect to a smaller model (Qwen3.5 3B)
2. **Model download** — if not bundled, offer to download the `.gguf` from HuggingFace with a progress bar. (Alternatively, bundle it in the Steam depot so it downloads during installation — preferred for a smooth experience.)
3. **Quick test** — fire a single `/describe/entity` call with a test prompt. Show the response in the onboarding screen so the player sees AI output before the game starts. If it fails, show a clear fallback message: *"AI unavailable — the game works fully without it, but world chat and NPC descriptions will use template responses."*

### Steam-specific notes

- Ship as a **Steam Play** title (Windows + Linux via Proton). macOS is a separate build due to Metal/MPS differences with llama.cpp.
- The `backend/data/mud.db` save file should live in `%APPDATA%/SinglePlayerAIMUD/` (Windows) or `~/.local/share/SinglePlayerAIMUD/` (Linux) — not inside the install directory, which Steam may overwrite on update.
- Admin endpoints (`/admin/boost`, `/admin/reset`) are localhost-only and not exposed externally — fine for a bundled app. No auth needed.
- The **Reset** button in-game already handles save wipes cleanly (`POST /admin/reset`) — no separate uninstaller logic needed for save data.

### Key files to create when starting this work

| File | Purpose |
|---|---|
| `electron/main.js` | Electron entry — spawns backend + llama-server, opens window |
| `electron/preload.js` | Context bridge if any native APIs needed |
| `scripts/build_backend.sh` | PyInstaller build step |
| `scripts/build_electron.sh` | Full packaging pipeline |
| `electron-builder.yml` | Electron Builder config — platform targets, Steam appid, resource paths |

---

*Built by Ocean Bennett*
