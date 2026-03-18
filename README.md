# SINGLE PLAYER AI MUD

An infinite, AI-powered text-based MMORPG. Explore a procedurally generated open world, fight enemies, complete quests, trade with vendors, and chat with AI-simulated players — all rendered in a terminal-style browser UI.

---

## Table of Contents

1. [Concept](#concept)
2. [Tech Stack](#tech-stack)
3. [Architecture Overview](#architecture-overview)
4. [Directory Structure & What Lives Where](#directory-structure--what-lives-where)
5. [Key Systems — How They Work](#key-systems--how-they-work)
6. [Data Models](#data-models)
7. [API Reference](#api-reference)
8. [Getting Started](#getting-started)
9. [Environment Variables](#environment-variables)
10. [Extending the Game](#extending-the-game)
11. [Known Constraints & Gotchas](#known-constraints--gotchas)

---

## Concept

The game follows a classic MMO loop — **open world zones → dungeons (level 10+) → raids (level 20+)** — repeated infinitely with no level cap. Each zone is either drawn from a curated starter template (levels 1–5) or procedurally generated using an AI narrative layer on top of deterministic math scaffolding.

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
- The zone ticker (`/zone/{zone_id}` polled every 5s) keeps the local zone mirror fresh

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
- Mobs spawn with a 20% elite chance and 5% named chance per slot (`_make_mobs`)
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
                           Gear Score gates the Raid — farm dungeons first
Raid       (level 20+,   → 10-player instanced, Epic/Legendary loot (2.8× stats)
            GS ≥ 100)      5 rooms, mini-boss + final boss with phase 2 enrage
                           Clearing a raid pushes open-world zone level +3
Zone Travel              → Requires 2 completed quests AND GS ≥ zone_max_level × 25
                           Cannot travel on open-world drops alone — must do dungeons + raids
                           "★ ZONE CLEARED!" fires only when travel succeeds (real milestone)
```

This creates an infinite compounding loop: Open World → Dungeon → Raid → meet GS threshold → travel → harder Open World → harder Dungeon → harder Raid → …

**Gear Score** — shown live in the HUD stats panel. Calculated as the sum of all equipped item stat values × rarity multiplier (Common 1×, Rare 2.5×, Epic 4×, Legendary 7×). Raid entry is blocked until GS ≥ 100 with a clear message: *"Gear score too low (74/100). Farm dungeons first."* Once GS ≥ 100 the HUD shows `✓ RAID READY` in purple.

**Zone travel GS gate** — `zone_max_level × 25` GS required to advance. For a level [1–5] zone: 125 GS required. Common-only drops top out around 35 GS total; reaching the threshold requires Rare/Epic gear from dungeons and raids. The scrolling ticker always shows current GS vs required so the player knows exactly what to farm.

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
- One tick = player attacks mob → class proc fires → (if mob alive and no dodge) mob counter-attacks
- Equipment stats are summed via `_equipment_bonus(character, stat)`
- Minimum 1 damage on any hit (no frustrating 0-damage swings)
- **1.5s server-side rate limit** per player enforced via `_attack_times` dict in `main.py`

### Dungeon & Raid System
`dungeon_engine.py → generate_run(), resolve_round()`

Dungeons and raids are **instanced** — completely separate from the Zone system. Each run is a `DungeonRun` stored in-memory (`_dungeon_runs` dict) for the duration of the session. No persistence overhead; server restart abandons any active run, which is acceptable for single-player.

**Structure:**

| Type | Rooms | Party | Loot tier | Gate |
|---|---|---|---|---|
| Dungeon | 3 (trash → trash+elite → boss) | Player + 4 AI | `dungeon` (1.6×) | Level 10 |
| Raid | 5 (trash → trash+elite → mini-boss → deeper trash → final boss) | Player + 9 AI | `raid` (2.8×) | Level 20 + GS ≥ 100 |

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

**Loot:** On run cleared, `_roll_loot()` is called with `zone_tier="dungeon"` or `"raid"`. Dungeon: 1–2 drops. Raid: 3 guaranteed drops. All items are class-biased toward the player's class using the same slot-weight system as open world.

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
Every 45 seconds the frontend fires `POST /action/patrol_check/{player_id}` when the player is idle in a non-hub location with no live mobs. The backend has a 25% chance to spawn a wandering mob from the zone's existing mob pool (thematically consistent — no generic enemy types). The mob is added to the live location and the client shows `⚠ A [mob] crosses your path!`. The encounter is then treated identically to a normal mob fight.

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
| Level 10–19 | `GS: 85 / 125 REQUIRED — LEVEL 14 / 20 NEEDED FOR RAIDS` | `RUN DUNGEONS → BUILD GEAR SCORE → UNLOCK RAIDS AT LEVEL 20` |
| Level 20+, GS below threshold | `GS: 110 / 125 REQUIRED TO ADVANCE` | `FARM RAIDS FOR EPIC GEAR → HIT 125 GS → TYPE 'TRAVEL'` |
| GS threshold met | `✓ GS: 130 / 125 — ZONE COMPLETE` | `ZONE CLEARED — TYPE 'TRAVEL' TO ADVANCE` |

This means a brand-new player always knows what to do next without reading a guide. The ticker is the tutorial.

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

Turn-in happens at any hub quest giver NPC via `POST /quests/complete/{player_id}`, which awards XP and optionally an item reward. Zone travel is **not** unlocked by quest completion — it requires both 2 completed quests (engagement gate) and the gear score threshold (see Progression Loop above). `"★ ZONE CLEARED!"` fires only when travel actually succeeds.

---

## Data Models
`backend/app/models/schemas.py` — authoritative source, all fields documented below.

| Model | Key Fields | Notes |
|---|---|---|
| `Player` | `level`, `hp/max_hp`, `xp/next_level_xp`, `gold`, `kills`, `deaths`, `inventory: List[Item]`, `equipment: Dict[str, Item]`, `active_quests`, `current_zone_id`, `current_location_id`, `visited_zone_ids`, `rested_xp`, `last_logout_time`, `dungeons_cleared`, `raids_cleared` | Equipment slots: `head chest hands legs feet main_hand off_hand`. `raids_cleared` drives open-world zone tier escalation (+3 levels per raid). `active_dungeon_run_id` tracks an in-progress run. |
| `Zone` | `id`, `name`, `locations: List[Location]`, `quests`, `simulated_players`, `time_of_day` (0–1), `weather`, `is_dungeon`, `is_raid` | Zone is the top-level open-world unit. Instanced dungeons use `DungeonRun`, not `Zone`. |
| `Location` | `id`, `name`, `description`, `npcs: List[NPC]`, `mobs: List[Mob]`, `exits: Dict[str, str]` | Exits map direction → location_id |
| `Mob` | `id`, `name`, `level`, `hp/max_hp`, `damage`, `loot_table`, `respawn_at` (Unix ts or None), `is_elite`, `is_named` | `respawn_at = None` means alive. Reset to `max_hp` and `respawn_at = None` when timer fires. |
| `NPC` | `id`, `name`, `role` (`quest_giver/vendor/trainer`), `dialogue`, `quests_offered`, `vendor_items` | Vendors have `vendor_items: List[Dict]` with `price` key |
| `Item` | `id`, `name`, `description`, `level`, `rarity`, `stats: Dict[str, int]`, `slot` | Equipment stats: `armor` or `damage`. Consumables use `slot = "consumable"` with effect encoded in stats: `{"heal_pct": 40}` or `{"xp_bonus_pct": 75, "xp_charges": 5}` |
| `Quest` | `id`, `title`, `objective`, `quest_type` (`kill/gather/hunt/explore/forage`), `target_id`, `collect_name` (gather/forage quests), `target_count`, `current_progress`, `xp_reward`, `is_completed` | `forage` quests use `target_id` as a location ID (same as `explore`); progress via `/action/gather` not mob kills. |
| `SimulatedPlayer` | `id`, `name`, `race`, `char_class`, `current_location_id`, `status` | Background actors — not real players. `current_location_id` resolves to a location name in the `/who` output. |
| `DungeonRun` | `id`, `player_id`, `dungeon_name`, `dungeon_level`, `is_raid`, `room_index`, `rooms: List[DungeonRoom]`, `party: List[DungeonMember]`, `combat_log`, `status` (`active/cleared/wiped`), `boss_enraged` | Stored in-memory only (`_dungeon_runs` dict). Lost on server restart. |
| `DungeonRoom` | `index`, `name`, `mobs: List[Mob]`, `cleared` | Rooms 0–2 for dungeons, 0–4 for raids. Room 2 (dungeon) / room 4 (raid) always has a named boss. |
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
| `POST` | `/zone/travel/{player_id}` | Generate + travel to new **open-world** zone. Params: `is_dungeon` (deprecated — use `/dungeon/enter`), `is_raid`. Zone level = `player.level + (raids_cleared × 3)` — escalates with each raid tier. Requires: (1) 2 completed quests in current zone, (2) GS ≥ `zone_max_level × 25`. |

### Actions
| Method | Path | Description |
|---|---|---|
| `POST` | `/action/move/{player_id}` | Move to location. Param: `location_id` |
| `POST` | `/action/attack/{player_id}` | Attack mob. Param: `mob_name`. Returns full combat delta |
| `POST` | `/action/flee/{player_id}` | Flee combat. 60% escape chance, counter-hit on failure. Param: `mob_name` |
| `POST` | `/action/equip/{player_id}` | Equip item from inventory. Param: `item_id` |
| `POST` | `/action/unequip/{player_id}` | Move equipped item back to bag. Param: `slot` (`head`, `chest`, `hands`, `legs`, `feet`, `main_hand`, `off_hand`) |
| `POST` | `/action/talk/{player_id}` | Talk to NPC. Param: `npc_name`. Returns `dialogue`, `offered_quests`, vendor fields |
| `POST` | `/action/use/{player_id}` | Use a consumable from inventory. Param: `item_id`. Enforces per-type cooldowns (`heal` 60 s, `xp` 5 min). Returns `player_hp`, `active_xp_buff`, `heal_cd`, `xp_cd`. |
| `POST` | `/action/rest/{player_id}` | Persist out-of-combat HP regen. Param: `hp` (clamped to `[1, max_hp]` server-side). Called by frontend timer every ~10 s while regenerating. |
| `POST` | `/action/gather/{player_id}` | Progress active forage quests targeting current location. 8 s cooldown. Returns `messages`, `quest_updates`. |
| `POST` | `/action/patrol_check/{player_id}` | 25% chance to spawn a wandering zone-mob in current location (non-hub, no live mobs only). Returns `{ patrol, mob_name, mob_level }`. |
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
| `POST` | `/dungeon/attack/{run_id}` | Resolve one full combat round (player + all AI party members + mob counter-attacks). Param: `player_id`. Returns `run`, `round_log`, `room_cleared`, `run_cleared`, `wiped`, `xp_gained`, `gold_gained`, `loot`. |
| `POST` | `/dungeon/advance/{run_id}` | Move to the next room after the current one is cleared. Param: `player_id`. |
| `POST` | `/dungeon/flee/{run_id}` | Abandon the run. Clears `player.active_dungeon_run_id`. Param: `player_id`. |

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

`scripts/smoke_test.py` runs a full happy-path integration test against a live backend — creates a character, moves, attacks, accepts a quest, talks to an NPC, checks the vendor, and cleans up after itself. Run it against a running server:

```powershell
cd backend
.\venv\Scripts\activate
# In a separate terminal: uvicorn main:app --reload --port 8000
python ..\scripts\smoke_test.py
# or against a different port:
python ..\scripts\smoke_test.py --base http://localhost:8001
```

Exits 0 on all checks passing, 1 on any failure. Useful to run after backend changes to catch regressions before they reach the frontend.
Stop the backend first — SQLite may have a write lock open while the server is running. The script shows the path and size before asking for confirmation.

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

## Known Constraints & Gotchas

**Zone must be saved after every attack hit, not just on mob death.**
The backend loads fresh zone state on each request. If you only save on mob death, every subsequent attack sees the mob at full HP again (the healing bug). This is why `vec_db.save_zone(...)` is called unconditionally at the end of the attack handler.

**`model_dump(mode='json')` is required for all Pydantic v2 serialization.**
Standard `dict()` or `.model_dump()` without `mode='json'` will leave Python `Enum` objects in the output that SQLite's JSON serializer cannot handle cleanly.

**Schema changes require clearing `backend/data/mud.db`.**
If you add a required field to a Pydantic model, existing JSON blobs in the DB won't have it. Pydantic will raise a `ValidationError` when loading old records. Clear the DB after significant model changes (`python scripts/reset_data.py` or delete the file).

**Frontend state is a local mirror, not the source of truth.**
The backend DB is authoritative. The frontend applies optimistic updates (local HP/XP changes) from attack response deltas. For full sync, the zone is polled every 5s via the ticker. If you notice desync, check that the backend is saving state and the ticker is running.

**Simulation loop only ticks zones in the in-memory cache.**
`simulation.py` iterates `vec_db._zone_cache.keys()`. A zone is only cached after it's first loaded in a request. Zones that have never been loaded won't be simulated. This is intentional — there's no need to simulate zones no one is in.

**Attack cooldown is in-memory only (`_attack_times` dict).**
Restarting the server resets all attack cooldowns. This is fine for a single-player game but would need Redis or similar for multi-player.

## Future Potential Updates

Ideas that fit the design philosophy (frictionless, solo-friendly, endlessly progressive) but are large enough to be their own milestone.

### AI Party Dialogue & Loot Reactions

Party members already act intelligently in combat (role-aware healing, taunts, procs). The next layer is making them *feel* like real companions: contextual one-liners during fights (*"Watch the boss's enrage!"*), celebrating crits, reacting to rare drops (*"Finally, a chest piece upgrade!"* or *"All yours — can't use that."*). This would use a single combined LLM call per round (one line for the most interesting party action) rather than per-member, keeping token usage comparable to the current open-world chat.

### Achievement System

Persistent milestone tracking — first boss kill, 100 kills in a zone, first Legendary drop, first raid clear — shown as a pop-up banner and stored on the player record. Achievements give small permanent stat bonuses (e.g. +5 max HP for "First Blood") to reward completionist play without gating progression behind them.

### Session Stats Screen

A score-screen shown on zone exit / tab close: kills this session, gold earned, best drop, XP gained, damage dealt. Creates the "just one more run" feeling and gives a natural stopping point. Zero backend changes needed — all data is already tracked in player state.

---

*Built by Ocean Bennett*
