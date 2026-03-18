from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

class Item(BaseModel):
    id: str
    name: str
    description: str
    level: int = 1
    rarity: str = "Common"
    stats: Dict[str, int] = {}
    slot: Optional[str] = None

class CharacterBase(BaseModel):
    name: str
    level: int
    hp: int
    max_hp: int
    damage: int
    pronouns: Optional[str] = "They/Them"

class Mob(CharacterBase):
    id: str
    description: str
    loot_table: List[Dict[str, Any]] = []
    respawn_at: Optional[float] = None  # Unix timestamp; None = alive
    is_elite: bool = False   # 2× HP, better loot, gold nameplate
    is_named: bool = False   # Unique boss-style named creature, epic loot

class NPC(BaseModel):
    id: str
    name: str
    role: str  # "quest_giver" | "vendor" | "trainer"
    description: Optional[str] = None
    dialogue: List[str] = []
    quests: List[str] = []
    quests_offered: List[str] = []
    vendor_items: List[Dict[str, Any]] = []  # Each entry is Item fields + "price"

class Location(BaseModel):
    id: str
    name: str
    description: str
    npcs: List[NPC] = []
    mobs: List[Mob] = []
    exits: Dict[str, Optional[str]] = {}
    resources: List[str] = []  # [plant_name, fish_species] for path locations; [] elsewhere

class QuestType(str, Enum):
    KILL = "kill"
    GATHER = "gather"
    HUNT = "hunt"
    SPEAK = "speak"
    EXPLORE = "explore"
    FORAGE = "forage"   # gather resources via the gather command at a specific location

class Quest(BaseModel):
    id: str
    title: str
    description: str
    objective: str
    quest_type: Optional[str] = "kill"
    target_id: str
    target_count: int = 1
    current_progress: int = 0
    xp_reward: int = 100
    item_reward: Optional[Any] = None
    is_completed: bool = False
    collect_name: Optional[str] = None  # gather quests: the item dropped, target_id is the mob

class SimulatedPlayer(CharacterBase):
    id: str
    race: str
    char_class: str
    current_action: Optional[str] = "exploring"
    status: Optional[str] = "resting"
    dialogue: Optional[str] = None
    current_location_id: Optional[str] = None

class Player(CharacterBase):
    xp: int
    next_level_xp: int
    race: str
    char_class: str
    active_quests: List[Quest] = []
    completed_quest_ids: List[str] = []
    inventory: List[Item] = []
    # Using Item objects instead of strings for rich tooltips/inspection
    equipment: Dict[str, Item] = {
        "head": Item(id="start_head", name="None", description="Empty slot.", stats={}, slot="head"),
        "chest": Item(id="start_chest", name="Ragged Tunic", description="A worn tunic for new adventurers.", stats={"armor": 2}, slot="chest"),
        "hands": Item(id="start_hands", name="None", description="Empty slot.", stats={}, slot="hands"),
        "legs": Item(id="start_legs", name="Worn Trousers", description="Sturdy but old trousers.", stats={"armor": 1}, slot="legs"),
        "feet": Item(id="start_feet", name="Old Boots", description="Comfortable but thin-soled boots.", stats={"armor": 1}, slot="feet"),
        "main_hand": Item(id="start_weapon", name="Rusty Shortsword", description="A trustworthy if slightly oxidized blade.", stats={"damage": 3}, slot="main_hand"),
        "off_hand": Item(id="start_offhand", name="None", description="Empty slot.", stats={}, slot="off_hand")
    }
    current_zone_id: str
    current_location_id: Optional[str] = None
    gold: int = 0
    deaths: int = 0
    kills: int = 0
    explored_location_ids: List[str] = []
    visited_zone_ids: List[str] = []  # All zone IDs ever generated for this character
    rested_xp: int = 0               # Bonus XP pool accumulated while logged out
    last_logout_time: float = 0.0    # Unix timestamp recorded on clean logout
    active_dungeon_run_id: Optional[str] = None
    dungeons_cleared: int = 0
    raids_cleared: int = 0

class DungeonMember(BaseModel):
    id: str
    name: str
    char_class: str
    role: str           # "tank" | "healer" | "dps"
    hp: int
    max_hp: int
    damage: int
    last_action: str = ""
    is_alive: bool = True

class DungeonRoom(BaseModel):
    index: int
    name: str
    mobs: List[Mob] = []
    cleared: bool = False

class DungeonRun(BaseModel):
    id: str
    player_id: str
    dungeon_name: str
    dungeon_level: int
    is_raid: bool = False
    room_index: int = 0         # current room (0–4 for raids, 0–2 for dungeons)
    rooms: List[DungeonRoom] = []
    party: List[DungeonMember] = []
    combat_log: List[str] = []  # rolling 5 lines
    status: str = "active"      # active | cleared | wiped
    boss_enraged: bool = False   # raid phase 2: triggers at 30% boss HP
    loot: List[dict] = []

class Zone(BaseModel):
    id: str
    name: str
    description: str
    level_range: List[int] = [1, 5]
    locations: List[Location] = []
    quests: List[Quest] = []
    simulated_players: List[SimulatedPlayer] = []
    world_messages: List[str] = []
    time_of_day: float = 0.5  # 0.0 to 1.0 (midnight to midnight)
    weather: str = "cloudy"  # sunny, cloudy, rainy, foggy, stormy, clear — simulation constrains by time_of_day
    is_dungeon: bool = False
    is_raid: bool = False
