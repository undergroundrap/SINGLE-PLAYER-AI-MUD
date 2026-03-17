from app.core.ai_client import ai_client
from app.models.schemas import Zone, Mob, Item, Quest, NPC, Location, SimulatedPlayer
from app.core.scaling_math import ScalingMath, RARITY
import random
import time

_ELITE_PREFIXES = ["Veteran", "Rabid", "Ancient", "Corrupted", "Savage", "Cursed", "Frenzied"]

def _plural(word: str) -> str:
    """Simple English pluralizer for quest objectives."""
    w = word.strip()
    if not w: return w
    last = w.split()[-1].lower()
    if last.endswith(('s', 'x', 'z', 'ch', 'sh')): suffix = 'es'
    elif last.endswith('y') and len(last) > 1 and last[-2] not in 'aeiou': suffix = 'ies'; w = ' '.join(w.split()[:-1] + [w.split()[-1][:-1]])
    else: suffix = 's'
    return w + suffix

# Mob-specific collectible nouns for gather quests
_MOB_COLLECTIBLES: dict[str, str] = {
    "boar":    "Tusk",    "wolf":    "Pelt",    "spider":  "Fang",
    "bat":     "Wing",    "rat":     "Tail",    "hound":   "Pelt",
    "snake":   "Scale",   "scorpion":"Stinger", "goblin":  "Ear",
    "orc":     "Tusk",    "troll":   "Hide",    "bandit":  "Badge",
    "skeleton":"Bone",    "zombie":  "Finger",  "ghoul":   "Claw",
    "imp":     "Horn",    "drake":   "Scale",   "golem":   "Core",
    "wraith":  "Essence", "demon":   "Shard",   "elemental":"Crystal",
}

def _collectible_for(mob_name: str) -> str:
    """Return a specific collectible noun for a mob, falling back to 'Hide'."""
    lower = mob_name.lower()
    for key, noun in _MOB_COLLECTIBLES.items():
        if key in lower:
            return noun
    return "Hide"

_FANTASY_NAMES = [
    "Theron", "Kael", "Sylvara", "Dorin", "Mira", "Torvald", "Elyndra", "Grim",
    "Vex", "Seraphine", "Brock", "Isolde", "Roran", "Lysa", "Fenris", "Zara",
    "Aldric", "Corvus", "Tessla", "Drake", "Wren", "Malrik", "Cinder", "Oryn",
    "Sable", "Jax", "Elowen", "Rook", "Petra", "Vael", "Sorin", "Kira",
    "Braxton", "Ashe", "Finley", "Nyx", "Calder", "Ozric", "Varyn", "Maeve",
    "Dusk", "Thornwood", "Grimshaw", "Rael", "Zinnia", "Lyric", "Torment", "Celestia",
    "Dawnstar", "Strix",
]

_SIM_RACES = ["Human", "Orc", "Elf", "Dwarf", "Gnome", "Troll", "Undead", "Goblin"]
_SIM_CLASSES = ["Warrior", "Mage", "Rogue", "Paladin", "Hunter", "Priest", "Shaman", "Warlock", "Druid"]

# ── Level-tiered mob name pools ───────────────────────────────────────────────
_MOB_POOLS: dict[tuple, list[str]] = {
    (1,  10): ["Boar", "Goblin Scout", "Forest Spider", "Cave Bat", "Rabid Wolf",
               "Swamp Rat", "Feral Hound", "Tunnel Crawler", "Plague Rat", "River Serpent"],
    (11, 20): ["Orc Grunt", "Troll Shaman", "Corrupted Hound", "Bandit Raider",
               "Swamp Lurker", "Grave Rat", "Dark Imp", "Bone Gnasher", "Marsh Stalker", "Rot Crawler"],
    (21, 35): ["Undead Soldier", "Plague Hound", "Flesh Golem", "Shadow Drake",
               "Dark Revenant", "Void Imp", "Cursed Knight", "Bile Wraith", "Hollow Brute", "Putrid Aberration"],
    (36, 50): ["Demon Thrall", "Blood Wyrm", "Cursed Colossus", "Soul Reaper",
               "Abyss Stalker", "Bone Titan", "Voidborn Husk", "Fel Ravager", "Death Herald", "Wretched Titan"],
    (51, 75): ["Infernal Brute", "Ancient Lich", "Nightmare Wraith", "Chaos Fiend",
               "Elder Demon", "Void Drifter", "Soulflayer", "Abyssal Tyrant", "Ruinbringer", "Doom Herald"],
    (76, 100): ["Void Titan", "Eternal Revenant", "Chaos Lord", "Abyssal Ancient",
                "World-Eater Spawn", "Elder God Fragment", "Annihilator", "Oblivion Wraith",
                "Primordial Horror", "Cataclysm Spawn"],
}

# ── Level-tier thematic prompts for AI zone generation ────────────────────────
_TIER_THEMES: dict[tuple, str] = {
    (1,  10): "beginner territory — lush forests, simple wildlife, new recruits finding their footing. Light, hopeful, and dangerous just enough to feel real.",
    (11, 20): "apprentice territory — haunted ruins, orc encampments, necromancer outposts bleeding into the wilderness. The safety of starter towns is a distant memory.",
    (21, 35): "journeyman territory — shadow-tainted badlands, demon-touched wilds, shattered fortresses. Survivors are scarce. Everything hunts.",
    (36, 50): "veteran territory — demon wastelands, cursed fortresses of the old empire, ancient evils stirring in blighted earth. Most adventurers die here.",
    (51, 75): "elite territory — abyssal rifts splitting the landscape, eternal wars between primordial powers, nightmare landscapes. Even veterans hesitate.",
    (76, 100): "endgame territory — the void made manifest, elder gods bleeding through reality, civilisation is a rumour. Every step could be the last.",
}


def _get_mob_name(level: int) -> str:
    for (lo, hi), pool in _MOB_POOLS.items():
        if lo <= level <= hi:
            return random.choice(pool)
    return random.choice(_MOB_POOLS[(76, 100)])


def _get_tier_theme(level: int) -> str:
    for (lo, hi), theme in _TIER_THEMES.items():
        if lo <= level <= hi:
            return theme
    return _TIER_THEMES[(76, 100)]


_VENDOR_NAMES = ["Gregor the Merchant", "Mira's Goods", "Dusty Packs", "The Iron Cart", "Roving Trader", "Old Fen's Wares"]

_VENDOR_ITEM_NAMES = {
    "head":      ["Hood", "Helm", "Coif"],
    "chest":     ["Tunic", "Chestplate", "Vest"],
    "hands":     ["Gloves", "Wraps", "Gauntlets"],
    "legs":      ["Leggings", "Greaves", "Trousers"],
    "feet":      ["Boots", "Sabatons", "Treads"],
    "main_hand": ["Sword", "Axe", "Staff", "Dagger"],
    "off_hand":  ["Shield", "Buckler", "Tome"],
}

def _make_vendor(hub_id: str, zone_id: str, level: int) -> NPC:
    slots = list(_VENDOR_ITEM_NAMES.keys())
    stock_slots = random.sample(slots, min(5, len(slots)))
    vendor_items = []
    for slot in stock_slots:
        stat    = "damage" if slot in ("main_hand", "off_hand") else "armor"
        value   = max(1, int(level * RARITY["UNCOMMON"]))
        name    = f"Trader's {random.choice(_VENDOR_ITEM_NAMES[slot])}"
        price   = value * level * 2
        vendor_items.append({
            "id":          f"v_item_{zone_id}_{slot}_{random.randint(100,999)}",
            "name":        name,
            "description": f"Sold by the local merchant. Level {level} gear.",
            "level":       level,
            "rarity":      "Uncommon",
            "stats":       {stat: value},
            "slot":        slot,
            "price":       price,
        })
    return NPC(
        id=f"vendor_{hub_id}",
        name=random.choice(_VENDOR_NAMES),
        role="vendor",
        description="A merchant with wares for adventurers.",
        dialogue=["Browse my wares — better equipment means longer survival.", "Selling? I'll take anything worth coin."],
        vendor_items=vendor_items,
    )


_NAMED_TEMPLATES = [
    ("{name} the Defiler", "An infamous creature, feared across the realm."),
    ("Scar-Hide {name}", "Battle-worn and brutal, this beast has survived a hundred fights."),
    ("Elder {name}", "Ancient and vast, its eyes hold centuries of hunger."),
    ("Plague-Born {name}", "Touched by dark magic, its wounds fester and spread."),
]


def _make_loot_table(mob_level: int, is_elite: bool = False, is_named: bool = False) -> list:
    # The loot loop checks entries in order and returns the first rarity that passes its
    # chance roll. Entries MUST be ordered best-to-worst so that rare items are checked
    # first — if Common were checked first at 100% it would block all higher rarities.
    if is_named:
        # Named bosses: guaranteed Rare minimum, real shot at Legendary
        return [
            {"chance": 0.10, "rarity": "Legendary", "stat_mult": RARITY["LEGENDARY"]},
            {"chance": 0.40, "rarity": "Epic",       "stat_mult": RARITY["EPIC"]},
            {"chance": 1.00, "rarity": "Rare",       "stat_mult": RARITY["RARE"]},
        ]
    if is_elite:
        # Elites: usually Uncommon, real shot at Rare, small Epic chance
        return [
            {"chance": 0.08, "rarity": "Epic",     "stat_mult": RARITY["EPIC"]},
            {"chance": 0.35, "rarity": "Rare",      "stat_mult": RARITY["RARE"]},
            {"chance": 0.80, "rarity": "Uncommon",  "stat_mult": RARITY["UNCOMMON"]},
        ]
    # Normal mobs: best rarity checked first so tier boosts (dungeon/raid) improve
    # quality instead of inflating Common to 100% and blocking everything else.
    return [
        {"chance": 0.02, "rarity": "Epic",     "stat_mult": RARITY["EPIC"]},
        {"chance": 0.08, "rarity": "Rare",      "stat_mult": RARITY["RARE"]},
        {"chance": 0.20, "rarity": "Uncommon",  "stat_mult": RARITY["UNCOMMON"]},
        {"chance": 0.40, "rarity": "Common",    "stat_mult": RARITY["COMMON"]},
    ]


def _make_mobs(mob_name: str, mob_level: int, zone_id: str, loc_index: int, count: int = 3, force_boss: bool = False) -> list:
    mobs = []
    named_spawned = False
    for j in range(count):
        roll = random.random()
        is_named  = (force_boss and j == 0) or (not named_spawned and roll < 0.05)
        is_elite  = not is_named and (force_boss or roll < 0.20)
        named_spawned = named_spawned or is_named

        if is_named:
            tpl = random.choice(_NAMED_TEMPLATES)
            name = tpl[0].format(name=mob_name)
            desc = tpl[1]
            hp_mult, dmg_mult = 3.0, 1.5
        elif is_elite:
            prefix = random.choice(_ELITE_PREFIXES)
            name = f"{prefix} {mob_name}"
            desc = f"A fearsome elite {mob_name}, stronger than its kin."
            hp_mult, dmg_mult = 2.0, 1.3
        else:
            name = mob_name
            desc = f"A menacing {mob_name}."
            hp_mult, dmg_mult = 1.0, 1.0

        base_hp  = ScalingMath.get_max_hp(mob_level)
        base_dmg = ScalingMath.get_damage(mob_level)
        mobs.append(Mob(
            id=f"mob_{zone_id}_{loc_index}_{j}",
            name=name,
            level=mob_level,
            hp=int(base_hp * hp_mult),
            max_hp=int(base_hp * hp_mult),
            damage=int(base_dmg * dmg_mult),
            description=desc,
            loot_table=_make_loot_table(mob_level, is_elite=is_elite, is_named=is_named),
            is_elite=is_elite,
            is_named=is_named,
        ))
    return mobs


# ── Starter zone templates (levels 1-5) ──────────────────────────────────────
# Quest tuple: (title, type, mob_name_or_None, count, collect_name_or_None)
# type "explore" has mob_name=None; type "gather" has collect_name set
_STARTER_TEMPLATES = [
    {
        "name": "Whispering Glade",
        "desc": "A lush, emerald forest teeming with life and ancient secrets.",
        "hub": ("Oakhaven Abbey", "A majestic stone abbey serving as a bastion of the Light."),
        "pois": [
            ("Deep Mines", "An abandoned mine overrun by pests."),
            ("Silver Lake", "A serene lake sparkling with magical residue."),
            ("Old Menhir Field", "A ring of ancient standing stones where the air hums with forgotten power."),
        ],
        "npc": ("Sergeant Thorne", "Greetings, recruit. The realm has need of you!"),
        "quests": [
            ("Boar Hunting",    "kill",    "Boar", 6, None),
            ("Tusk Collection", "gather",  "Boar", 4, "Boar Tusk"),
            ("Ancient Stones",  "explore", None,   1, None),
        ]
    },
    {
        "name": "Moonshaded Glade",
        "desc": "A mystical nocturnal woodland bathed in the glow of the World Tree.",
        "hub": ("Ancient World Tree", "A massive, hollowed out tree serving as a home for the Elves."),
        "pois": [
            ("Shadowed Hollow", "A dark den of spiders and shadows."),
            ("Moonlit Lake", "A tranquil pool reflecting the starry sky."),
            ("Spirit Glade", "A clearing where the veil between worlds grows thin. Something ancient watches here."),
        ],
        "npc": ("Warden Thalric", "Patience, traveler. Nature's balance is delicate."),
        "quests": [
            ("Spider Menace", "kill",    "Forest Spider", 8, None),
            ("Venom Fangs",   "gather",  "Forest Spider", 5, "Forest Spider Fang"),
            ("Spirit Glade",  "explore", None,            1, None),
        ]
    },
    {
        "name": "Saltcliff Reach",
        "desc": "A rugged coastline of jagged rocks and salt-sprayed ruins, watched over by circling sea birds.",
        "hub": ("Saltcliff Outpost", "A battered watchtower clinging to the cliff's edge, manned by desperate scouts."),
        "pois": [
            ("Smuggler's Cove", "A sea cave riddled with contraband and feral hounds."),
            ("Wreckers' Shoal", "Shallow reefs littered with the remains of a dozen ships."),
            ("Clifftop Overlook", "A windswept vantage point above the sea where old signal fires once burned."),
        ],
        "npc": ("Captain Vael", "The sea gives and the sea takes. Best we take first."),
        "quests": [
            ("Clear the Cove",   "kill",    "Feral Hound", 6, None),
            ("Salvage Run",      "gather",  "Feral Hound", 4, "Feral Hound Pelt"),
            ("Clifftop Survey",  "explore", None,          1, None),
        ]
    },
    {
        "name": "The Ashen Fields",
        "desc": "Rolling plains of scorched earth and withered grass, still warm from fires no one alive remembers.",
        "hub": ("Ember Crossing", "A fortified crossroads built on the ashes of an older settlement."),
        "pois": [
            ("Charred Hollow", "A depression in the fields where swamp rats breed by the hundreds."),
            ("Blackthorn Thicket", "Twisted, leafless trees bristling with plague rats."),
            ("Scorched Monument", "A crumbling obelisk carved with warnings in a language no one reads anymore."),
        ],
        "npc": ("Warden Kess", "Nothing grows here but trouble. Keep your blade sharp."),
        "quests": [
            ("Rat Cull",           "kill",    "Swamp Rat", 8, None),
            ("Blight Samples",     "gather",  "Swamp Rat", 5, "Swamp Rat Tail"),
            ("Scorched Monument",  "explore", None,        1, None),
        ]
    },
    {
        "name": "Barrowmoor",
        "desc": "Fog-drenched wetlands where old burial mounds push up through the peat like sleeping giants.",
        "hub": ("Mourner's Rest", "A grim inn built beside the oldest mound, where grave-wardens drink and wait."),
        "pois": [
            ("The Sunken Graves", "Half-flooded burial pits where cave bats roost in the dark."),
            ("Peat Bog", "Deep black water that swallows sound — and those who wade into it."),
            ("The Ancient Mound", "The oldest barrow in the moor. Whatever is buried here has not rested easy for centuries."),
        ],
        "npc": ("Elder Brynn", "The dead here don't rest easy. Neither should you."),
        "quests": [
            ("Bat Culling",      "kill",    "Cave Bat", 7, None),
            ("Bone Collection",  "gather",  "Cave Bat", 4, "Cave Bat Wing"),
            ("The Ancient Mound","explore", None,       1, None),
        ]
    },
]


class WorldGenerator:
    @staticmethod
    async def generate_zone(level: int, is_dungeon: bool = False, is_raid: bool = False) -> Zone:

        # 0. Starter Templates (Levels 1-5)
        if level <= 5 and not is_dungeon and not is_raid:
            tpl = random.choice(_STARTER_TEMPLATES)
            zone_id = f"zone_start_{level}_{random.randint(100, 999)}"
            hub_id = f"hub_{zone_id}"
            poi_ids = [f"poi_{i}_{zone_id}" for i in range(3)]
            directions = ["north", "south", "east", "west"]

            all_quest_ids = [f"q_{i}_{zone_id}" for i in range(len(tpl["quests"]))]
            hub_loc = Location(
                id=hub_id,
                name=tpl["hub"][0],
                description=tpl["hub"][1],
                npcs=[
                    NPC(
                        id=f"npc_{hub_id}",
                        name=tpl["npc"][0],
                        description="A local authority figure.",
                        role="quest_giver",
                        dialogue=[tpl["npc"][1]],
                        quests=all_quest_ids,
                        quests_offered=all_quest_ids,
                    ),
                    _make_vendor(hub_id, zone_id, level),
                ],
                exits={directions[i]: poi_ids[i] for i in range(len(poi_ids))}
            )

            locations = [hub_loc]
            for i, poi_id in enumerate(poi_ids):
                q = tpl["quests"][i] if i < len(tpl["quests"]) else tpl["quests"][0]
                quest_type = q[1]
                if quest_type == "explore":
                    locations.append(Location(
                        id=poi_id,
                        name=tpl["pois"][i][0],
                        description=tpl["pois"][i][1],
                        exits={ScalingMath.get_opposite_direction(directions[i]): hub_id},
                        mobs=[]
                    ))
                else:
                    mob_name = q[2]
                    locations.append(Location(
                        id=poi_id,
                        name=tpl["pois"][i][0],
                        description=tpl["pois"][i][1],
                        exits={ScalingMath.get_opposite_direction(directions[i]): hub_id},
                        mobs=_make_mobs(mob_name, level, zone_id, i, count=4)
                    ))

            quests = []
            for i, q in enumerate(tpl["quests"]):
                quest_type = q[1]
                mob = q[2]
                count = q[3]
                collect = q[4] if len(q) > 4 else None

                if quest_type == "explore":
                    target_id = poi_ids[2]
                    objective = f"Explore {tpl['pois'][2][0]}"
                    description = f"Venture out to discover {tpl['pois'][2][0]}."
                    collect_name = None
                elif quest_type == "gather":
                    target_id = mob
                    collect_name = collect or _collectible_for(mob)
                    objective = f"Kill {count} {_plural(mob)} — collect their {collect_name}"
                    description = f"Gather {collect_name}s from the {_plural(mob).lower()} in the area."
                else:  # kill
                    target_id = mob
                    objective = f"Kill {count} {_plural(mob)}"
                    description = f"The realm needs your assistance with the {_plural(mob).lower()}."
                    collect_name = None

                quests.append(Quest(
                    id=f"q_{i}_{zone_id}",
                    title=q[0],
                    description=description,
                    objective=objective,
                    quest_type=quest_type,
                    target_id=target_id,
                    target_count=count,
                    collect_name=collect_name,
                    xp_reward=ScalingMath.get_xp_required(level) // 3,
                ))

            _used = []
            sim_players = []
            for _ in range(random.randint(2, 4)):
                sname = random.choice([n for n in _FANTASY_NAMES if n not in _used] or _FANTASY_NAMES)
                _used.append(sname)
                sim_players.append(SimulatedPlayer(
                    id=f"sim_{random.randint(100, 999)}",
                    name=sname,
                    level=level,
                    hp=ScalingMath.get_max_hp(level),
                    max_hp=ScalingMath.get_max_hp(level),
                    damage=ScalingMath.get_damage(level),
                    race=random.choice(_SIM_RACES),
                    char_class=random.choice(_SIM_CLASSES),
                    current_location_id=hub_id,
                    status=random.choice(["exploring", "resting", "battling"])
                ))

            return Zone(
                id=zone_id, name=tpl["name"], description=tpl["desc"],
                level_range=[level, level+5], locations=locations,
                quests=quests, simulated_players=sim_players
            )

        # 1. Procedural Skeleton (level 6+)
        zone_id = f"zone_{level}_{random.randint(1000, 9999)}"
        hub_id  = f"hub_{zone_id}"
        poi_ids = [f"poi_{i}_{zone_id}" for i in range(4)]  # 4 POIs
        directions = ["north", "south", "east", "west"]

        # 3 distinct mob names — mob_name for POI 0, mob_name_2 for POI 1, mob_name_3 for POI 3
        # POI 2 is an exploration landmark (no primary mob)
        mob_names: list[str] = []
        while len(mob_names) < 3:
            candidate = _get_mob_name(level)
            if candidate not in mob_names:
                mob_names.append(candidate)
        mob_name, mob_name_2, mob_name_3 = mob_names
        collectible_2 = _collectible_for(mob_name_2)

        # 5 quest skeletons — all used, no shuffle
        quest_skeleton = [
            {"type": "kill",    "target": mob_name,   "collect": None,          "count": random.randint(6, 12), "explore_poi": None},
            {"type": "gather",  "target": mob_name_2, "collect": collectible_2, "count": random.randint(4, 8),  "explore_poi": None},
            {"type": "explore", "target": poi_ids[2], "collect": None,          "count": 1,                     "explore_poi": 2},
            {"type": "hunt",    "target": mob_name,   "collect": None,          "count": 1,                     "explore_poi": None},
            {"type": "kill",    "target": mob_name_3, "collect": None,          "count": random.randint(4, 8),  "explore_poi": None},
        ]

        # 2. AI Narrative Layer
        type_str   = "Dungeon" if is_dungeon else ("Raid" if is_raid else "Zone")
        tier_theme = _get_tier_theme(level)
        system_prompt = (
            "You are a World Builder for a gritty single-player MMORPG. "
            "Return ONLY valid JSON with keys: 'zone_name', 'zone_description', 'hub_name', 'hub_description', "
            "'locations' (list of exactly 4 {name, description}), "
            "'npcs' (list of exactly 2 {name, dialogue} — distinct personalities), "
            "'quest_flavors' (list of exactly 5 {title, description}). "
            "No markdown, no commentary, no thought blocks. JSON only."
        )
        prompt = (
            f"Level {level} {type_str}. Tier: {tier_theme}. "
            f"Creatures: {mob_name}, {mob_name_2}, {mob_name_3}. "
            f"4 satellite POIs (3rd is an exploration landmark with no enemies). 5 quests. "
            f"2 named NPCs with distinct personalities. "
            "Theme: Gritty High Fantasy. Be specific and evocative — no generic placeholders."
        )

        # Offline fallbacks
        _FALLBACK_ZONES = [
            {
                "zone_name": "Gloomhaven Thicket",
                "zone_description": "A twisted woodland where the canopy blocks all light.",
                "hub_name": "Ranger's Watch", "hub_description": "A crude watchtower manned by desperate scouts.",
                "locations": [
                    {"name": "Rotwood Den",      "description": f"A fetid hollow where {mob_name}s nest in the dark."},
                    {"name": "Ashen Clearing",   "description": f"Scorched earth still warm from the {mob_name_2}s that razed it."},
                    {"name": "The Sunken Altar", "description": "A moss-covered altar half-buried in the roots. No enemies — only silence and old stone."},
                    {"name": "Skull Hollow",     "description": f"A bone-strewn pit deep in the thicket. The {mob_name_3}s claim it as their own."},
                ],
                "npcs": [
                    {"name": "Scout Varek",  "dialogue": "Don't stray from the path. Nothing that does comes back whole."},
                    {"name": "Tracker Mira", "dialogue": "I've mapped every shadow in these woods. None of them are safe."},
                ],
                "quest_flavors": [
                    {"title": "Thin the Pack",    "description": f"The {mob_name}s multiply without check."},
                    {"title": "Iron Harvest",     "description": f"Collect trophies from the {mob_name_2}s before they overrun us."},
                    {"title": "The Sunken Altar", "description": "An old shrine lies buried in the thicket. Find it."},
                    {"title": "Named Terror",     "description": f"A massive, ancient {mob_name} has been spotted. Put it down."},
                    {"title": "Into the Dark",    "description": f"Venture deep enough to face the {mob_name_3}s in their hollow."},
                ],
            },
            {
                "zone_name": "The Ashfields",
                "zone_description": "Endless grey plains of volcanic dust and shattered bone.",
                "hub_name": "Ember Bastion", "hub_description": "A fortress half-buried in ash, its fires still burning.",
                "locations": [
                    {"name": "Cinder Wastes",   "description": f"{mob_name}s pick through the remains of the old world."},
                    {"name": "Boneyard Trench", "description": f"Mass graves where {mob_name_2}s drag the dead."},
                    {"name": "The Ashen Spire", "description": "A crumbling tower of fused glass and bone. No creatures nest here — the air itself is wrong."},
                    {"name": "The Slagpit",     "description": f"A collapsed forge district. {mob_name_3}s roost among the cooling metal."},
                ],
                "npcs": [
                    {"name": "Warlord Dren",        "dialogue": "This land was taken from us by blood. We'll take it back the same way."},
                    {"name": "Quartermaster Hael",  "dialogue": "Supplies are thin. Bring me trophies and I'll see you equipped."},
                ],
                "quest_flavors": [
                    {"title": "Scorched Earth",   "description": f"Drive back the {mob_name}s encroaching on the bastion."},
                    {"title": "The Dead Walk",    "description": f"End the {mob_name_2} threat before it spreads."},
                    {"title": "The Ashen Spire",  "description": "Something was sealed in that tower. Find out what."},
                    {"title": "Blood Hunt",       "description": f"A veteran {mob_name} stalks the wastes. Track it down."},
                    {"title": "Slagpit Clearance","description": f"Root out the {mob_name_3}s from the Slagpit before they fortify."},
                ],
            },
            {
                "zone_name": "Void's Edge",
                "zone_description": "Reality tears open here. The sky pulses with wrongness.",
                "hub_name": "The Last Threshold", "hub_description": "A crumbling outpost at the boundary of the known world.",
                "locations": [
                    {"name": "Rift Scar",        "description": f"A wound in reality where {mob_name}s bleed through."},
                    {"name": "Unmade Wastes",    "description": f"{mob_name_2}s patrol the ruins of a civilisation that defied the void."},
                    {"name": "The Null Archive", "description": "A library of the old order, preserved perfectly by the void. No creatures — just silence and forbidden knowledge."},
                    {"name": "The Null Point",   "description": f"The furthest surveyed coordinate. {mob_name_3}s gather here as if drawn by something beneath."},
                ],
                "npcs": [
                    {"name": "Archivist Soln", "dialogue": "We mapped the void. The void mapped us back."},
                    {"name": "Warden Tyss",    "dialogue": "Cross the Null Point and you're on your own. No one comes back unchanged."},
                ],
                "quest_flavors": [
                    {"title": "Seal the Breach",   "description": f"Destroy the {mob_name}s pouring from the rift."},
                    {"title": "Reclamation",       "description": f"Recover relics from the {mob_name_2}-held ruins."},
                    {"title": "The Null Archive",  "description": "Reach the old archive and return — report what you find."},
                    {"title": "Void-Touched",      "description": f"A named {mob_name} has been warped by the rift. Destroy it before it spreads the corruption."},
                    {"title": "The Null Point",    "description": f"Reach the Null Point and eliminate the {mob_name_3}s gathering there."},
                ],
            },
        ]

        try:
            data = await ai_client.generate_json(prompt, system_prompt)
        except Exception as e:
            print(f"DEBUG: AI Generation failed, using local fallback. Error: {e}")
            data = random.choice(_FALLBACK_ZONES)

        # 3. Assemble Zone
        # NPC 1 gets quests 0-2, NPC 2 gets quests 3-4
        npc_data = data.get("npcs", [])
        npc1_name     = npc_data[0].get("name", "Commander") if len(npc_data) > 0 else "Commander"
        npc1_dialogue = npc_data[0].get("dialogue", "For the realm!") if len(npc_data) > 0 else "For the realm!"
        npc2_name     = npc_data[1].get("name", "Sergeant")  if len(npc_data) > 1 else "Sergeant"
        npc2_dialogue = npc_data[1].get("dialogue", "I have work for you.") if len(npc_data) > 1 else "I have work for you."

        npc1_quest_ids = [f"q_{i}_{zone_id}" for i in range(3)]   # quests 0, 1, 2
        npc2_quest_ids = [f"q_{i}_{zone_id}" for i in range(3, 5)] # quests 3, 4

        hub_loc = Location(
            id=hub_id,
            name=data.get("hub_name", "Settlement"),
            description=data.get("hub_description", "A safe haven."),
            npcs=[
                NPC(
                    id=f"npc1_{hub_id}",
                    name=npc1_name,
                    description="A local authority figure.",
                    role="quest_giver",
                    dialogue=[npc1_dialogue],
                    quests=npc1_quest_ids,
                    quests_offered=npc1_quest_ids,
                ),
                NPC(
                    id=f"npc2_{hub_id}",
                    name=npc2_name,
                    description="A secondary quest giver.",
                    role="quest_giver",
                    dialogue=[npc2_dialogue],
                    quests=npc2_quest_ids,
                    quests_offered=npc2_quest_ids,
                ),
                _make_vendor(hub_id, zone_id, level),
            ],
            exits={directions[i]: poi_ids[i] for i in range(len(poi_ids))}
        )

        # POI mob assignment:
        # POI 0 → mob_name  (kill quest)
        # POI 1 → mob_name_2 (gather quest)
        # POI 2 → no mobs   (exploration landmark)
        # POI 3 → mob_name_3 (kill/boss quest)
        poi_mob_names = [mob_name, mob_name_2, None, mob_name_3]
        locations_data = data.get("locations", [])
        locations = [hub_loc]
        last_poi_idx = len(poi_ids) - 1  # index 3
        for i, poi_id in enumerate(poi_ids):
            loc_flavor = locations_data[i] if i < len(locations_data) else {"name": f"Point {i+1}", "description": "An uncharted area."}
            loc_name = loc_flavor.get("name", f"Point {i+1}")
            loc_desc = loc_flavor.get("description", "A remote area.")
            mob_for_poi = poi_mob_names[i]
            is_boss_chamber = is_dungeon and i == last_poi_idx

            if mob_for_poi is None:
                # Pure exploration — no mobs
                mobs = []
            else:
                mob_count = 3 if is_boss_chamber else random.randint(3, 5)
                if is_boss_chamber:
                    loc_name = f"{loc_name} [BOSS]"
                    loc_desc = f"{loc_desc} A powerful guardian waits here."
                mobs = _make_mobs(mob_for_poi, level, zone_id, i, count=mob_count, force_boss=is_boss_chamber)

            locations.append(Location(
                id=poi_id,
                name=loc_name,
                description=loc_desc,
                exits={ScalingMath.get_opposite_direction(directions[i]): hub_id},
                mobs=mobs,
            ))

        # Build quests
        quests = []
        quest_flavors = data.get("quest_flavors", [])
        for i, q_skel in enumerate(quest_skeleton):
            q_flavor = quest_flavors[i] if i < len(quest_flavors) else {"title": "Duty Calls", "description": "Help the settlement."}

            if q_skel["type"] == "explore":
                poi_loc = locations[q_skel["explore_poi"] + 1]  # +1 because hub is locations[0]
                target_id = poi_loc.id
                objective = f"Explore {poi_loc.name}"
                description = q_flavor.get("description", f"Venture out to discover {poi_loc.name}.")
                collect_name = None
            elif q_skel["type"] == "gather":
                target_id = q_skel["target"]  # mob name — NOT "Boar Tusk"
                collect_name = q_skel["collect"]
                objective = f"Kill {q_skel['count']} {_plural(q_skel['target'])} — collect their {collect_name}"
                description = q_flavor.get("description", f"Gather {collect_name}s from the {_plural(q_skel['target']).lower()}.")
            elif q_skel["type"] == "hunt":
                target_id = q_skel["target"]
                objective = f"Slay any named or elite creature in the zone"
                description = q_flavor.get("description", f"Hunt down the most dangerous creature you can find.")
                collect_name = None
            else:  # kill
                target_id = q_skel["target"]
                objective = f"Kill {q_skel['count']} {_plural(q_skel['target'])}"
                description = q_flavor.get("description", f"Clear out the {_plural(q_skel['target']).lower()}.")
                collect_name = None

            quests.append(Quest(
                id=f"q_{i}_{zone_id}",
                title=q_flavor.get("title", "Duty Calls"),
                description=description,
                objective=objective,
                quest_type=q_skel["type"],
                target_id=target_id,
                target_count=q_skel["count"],
                collect_name=collect_name,
                xp_reward=ScalingMath.get_xp_required(level) // 4,
            ))

        _used_names: list[str] = []
        sim_players = []
        for _ in range(random.randint(2, 4)):
            name = random.choice([n for n in _FANTASY_NAMES if n not in _used_names] or _FANTASY_NAMES)
            _used_names.append(name)
            sim_players.append(SimulatedPlayer(
                id=f"sim_{random.randint(100, 999)}",
                name=name,
                level=level + random.randint(-1, 2),
                hp=ScalingMath.get_max_hp(level),
                max_hp=ScalingMath.get_max_hp(level),
                damage=ScalingMath.get_damage(level),
                race=random.choice(_SIM_RACES),
                char_class=random.choice(_SIM_CLASSES),
                current_location_id=hub_id,
                status=random.choice(["exploring", "resting", "battling"])
            ))

        return Zone(
            id=zone_id,
            name=data.get("zone_name", "Unknown Zone"),
            description=data.get("zone_description", "An uncharted territory."),
            level_range=[level, level + 5],
            locations=locations,
            quests=quests,
            simulated_players=sim_players,
            is_dungeon=is_dungeon,
            is_raid=is_raid,
        )


world_gen = WorldGenerator()
