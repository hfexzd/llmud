import random
from engine.models import (
    Player, Encounter, CombatResult, BreakthroughResult, LevelTier, LEVEL_TABLE,
    SCENE_MAP,
)


def get_current_tier(player: Player) -> LevelTier:
    """Find the tier matching the player's current level."""
    for tier in LEVEL_TABLE:
        if tier.name == player.level:
            return tier
    return LEVEL_TABLE[0]  # Default to first tier if level not found


def get_multiplier(player: Player) -> float:
    return get_current_tier(player).multiplier


def compute_attack(player: Player) -> int:
    """attack = spirit_power × level_multiplier"""
    return int(player.spirit_power * get_multiplier(player))


def compute_defense(player: Player) -> int:
    """defense = floor(spirit_power / 2) + 5"""
    return player.spirit_power // 2 + 5


def cultivate(player: Player) -> Player:
    """修炼: spirit_power += random(1,3). Returns updated player copy."""
    gain = random.randint(1, 3)
    updated = player.model_copy(update={"spirit_power": player.spirit_power + gain})
    return updated


def resolve_combat(player: Player, enemy: Encounter, flee: bool = False) -> tuple[CombatResult, Player, Encounter]:
    """
    Deterministic combat resolution. Engine is the sole source of truth for numbers.
    Returns (CombatResult, updated_player, updated_enemy).
    """
    p_atk = compute_attack(player)
    p_def = compute_defense(player)

    if flee:
        result = CombatResult(
            dmg_to_enemy=0, dmg_to_player=0, result="flee",
            enemy_remaining_hp=enemy.hp, player_remaining_hp=player.hp
        )
        return result, player, enemy

    # Player attacks enemy
    dmg_to_enemy = max(1, p_atk - enemy.defense)
    enemy_hp_after = enemy.hp - dmg_to_enemy

    # Enemy retaliates only if still alive
    if enemy_hp_after > 0:
        dmg_to_player = max(1, enemy.attack - p_def)
    else:
        dmg_to_player = 0

    player_hp_after = player.hp - dmg_to_player

    # Determine result
    if enemy_hp_after <= 0:
        result_str = "win"
    elif player_hp_after <= 0:
        result_str = "lose"
    else:
        # Both alive — combat continues (slice: treat as one round, "win" if enemy <50% HP)
        result_str = "win" if enemy_hp_after <= enemy.max_hp // 2 else "flee"

    # Clamp HP
    enemy_remaining = max(0, enemy_hp_after)
    player_remaining = max(1, player_hp_after) if result_str != "lose" else max(0, player_hp_after)

    result = CombatResult(
        dmg_to_enemy=dmg_to_enemy,
        dmg_to_player=dmg_to_player,
        result=result_str,
        enemy_remaining_hp=enemy_remaining,
        player_remaining_hp=player_remaining,
    )

    updated_player = player.model_copy(update={"hp": player_remaining})
    updated_enemy = enemy.model_copy(update={"hp": enemy_remaining})

    return result, updated_player, updated_enemy


def check_breakthrough(player: Player) -> BreakthroughResult | None:
    """
    Check if player qualifies for a level breakthrough.
    Returns BreakthroughResult if they do, None otherwise.
    Breakthrough is deterministic: if spirit_power >= next tier threshold relative to player.level.
    """
    current_idx = None
    for i, tier in enumerate(LEVEL_TABLE):
        if tier.name == player.level:
            current_idx = i
            break

    if current_idx is None:
        return None  # Player level not found in table

    if current_idx + 1 >= len(LEVEL_TABLE):
        return None  # Already at max level

    next_tier = LEVEL_TABLE[current_idx + 1]
    if player.spirit_power >= next_tier.spirit_threshold:
        return BreakthroughResult(from_level=player.level, to_level=next_tier.name)
    return None


def move(player: Player, destination: str) -> Player:
    """Move player to *destination* if it connects to current_scene.

    Returns an updated Player with current_scene set to *destination* on
    success, or the original Player unchanged if the move is invalid.
    """
    current = SCENE_MAP.get(player.current_scene)
    if current is None:
        return player
    if destination not in current.connections:
        return player
    return player.model_copy(update={"current_scene": destination})