import math
from typing import Any

# Class stat multipliers (hp_mult, damage_mult)
CLASS_STATS: dict[str, tuple[float, float]] = {
    "Warrior":  (1.20, 1.00),
    "Paladin":  (1.15, 0.95),
    "Hunter":   (1.00, 1.10),
    "Rogue":    (0.90, 1.20),
    "Priest":   (0.85, 0.85),
    "Shaman":   (1.10, 1.05),
    "Mage":     (0.80, 1.30),
    "Warlock":  (0.85, 1.20),
    "Druid":    (1.00, 1.00),
}


def apply_levelups(player: Any, messages: list) -> bool:
    """Loop level-ups until XP is below threshold. Appends level-up messages. Returns True if leveled."""
    leveled = False
    hp_mult, dmg_mult = CLASS_STATS.get(getattr(player, 'char_class', 'Warrior'), (1.0, 1.0))
    while player.xp >= player.next_level_xp:
        player.xp -= player.next_level_xp
        player.level += 1
        player.next_level_xp = ScalingMath.get_xp_required(player.level)
        player.max_hp = int(ScalingMath.get_max_hp(player.level) * hp_mult)
        player.hp = player.max_hp
        player.damage = int(ScalingMath.get_damage(player.level) * dmg_mult)
        messages.append(f"⬆ LEVEL UP! You are now level {player.level}!")
        leveled = True
    return leveled


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
