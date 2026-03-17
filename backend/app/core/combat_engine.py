import random
from app.models.schemas import Player, Mob, CharacterBase
from app.core.scaling_math import ScalingMath


class CombatEngine:
    @staticmethod
    def _equipment_bonus(character: CharacterBase, stat: str) -> int:
        """Sum a specific stat across all equipped items."""
        if not hasattr(character, 'equipment'):
            return 0
        total = 0
        for item in character.equipment.values():
            if isinstance(item, dict):
                total += item.get('stats', {}).get(stat, 0)
            elif hasattr(item, 'stats'):
                total += item.stats.get(stat, 0)
        return total

    @staticmethod
    def get_effective_max_hit(attacker: CharacterBase) -> int:
        base = attacker.damage
        bonus = CombatEngine._equipment_bonus(attacker, 'damage')
        return max(1, base + bonus)

    @staticmethod
    def get_effective_defense(target: CharacterBase) -> int:
        base = target.level * 8
        # Each point of armor = 3 defense rating (meaningful but not OP)
        armor = CombatEngine._equipment_bonus(target, 'armor')
        return base + (armor * 3)

    @staticmethod
    def calculate_hit(attacker: CharacterBase, target: CharacterBase) -> bool:
        # RuneScape-style accuracy roll vs defense roll
        attacker_accuracy = attacker.level * 10
        target_defense = CombatEngine.get_effective_defense(target)

        att_roll = random.randint(1, max(1, attacker_accuracy))
        def_roll = random.randint(1, max(1, target_defense))
        return att_roll > def_roll

    @staticmethod
    def calculate_damage(attacker: CharacterBase) -> int:
        max_hit = CombatEngine.get_effective_max_hit(attacker)
        # Floor at 1 on a hit to remove the frustrating 0-damage swings
        return random.randint(1, max(1, max_hit))

    @staticmethod
    def resolve_tick(attacker: CharacterBase, target: CharacterBase):
        """Resolves one combat tick (one round of attacks)."""
        messages = []

        if CombatEngine.calculate_hit(attacker, target):
            damage = CombatEngine.calculate_damage(attacker)
            target.hp = max(0, target.hp - damage)
            messages.append(f"{attacker.name} hits {target.name} for {damage} damage!")
        else:
            messages.append(f"{attacker.name} misses {target.name}!")

        return messages, target.hp <= 0


combat_engine = CombatEngine()
