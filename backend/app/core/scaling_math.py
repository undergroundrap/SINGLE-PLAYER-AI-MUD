import math

class ScalingMath:
    @staticmethod
    def get_max_hp(level: int) -> int:
        # Base HP 100, scaling exponentially
        return int(100 * math.pow(1.15, level - 1) + (level * 10))

    @staticmethod
    def get_damage(level: int) -> int:
        # Base Damage 10, scaling exponentially
        return int(10 * math.pow(1.15, level - 1) + (level * 2))

    @staticmethod
    def get_xp_required(level: int) -> int:
        # Polynomial curve: stays human-readable at all levels.
        # Level 1→200, Level 10→11k, Level 20→42k, Level 50→255k, Level 100→1M
        # Mob XP = get_xp_required(mob.level) // 8  →  always ~8 kills per level
        # regardless of how high the player goes.
        return int(100 * level * (level + 1))

    @staticmethod
    def get_opposite_direction(direction: str) -> str:
        opposites = {
            "north": "south",
            "south": "north",
            "east": "west",
            "west": "east"
        }
        return opposites.get(direction.lower(), "here")

# Rarity Multipliers
RARITY = {
    "POOR": 0.5,
    "COMMON": 1.0,
    "UNCOMMON": 1.5,
    "RARE": 2.5,
    "EPIC": 4.0,
    "LEGENDARY": 7.0,
    "ARTIFACT": 12.0
}
