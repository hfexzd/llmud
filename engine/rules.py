import random
from engine.models import (
    Player, Encounter, CombatResult, BreakthroughResult, LevelTier, LEVEL_TABLE,
    SCENE_MAP, PHASE_0_BIBLE,
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
    Deterministic combat resolution for a single round. Engine is the sole
    source of truth for numbers. Returns (CombatResult, updated_player, updated_enemy).

    The caller is responsible for persisting updated_enemy.hp across rounds
    (via the player's active_enemy state) — this function is stateless and
    only resolves one round against the HP it is given.

    Result is one of:
      - "win"     enemy HP dropped to 0 (killed)
      - "lose"    player HP dropped to 0 (defeated)
      - "ongoing" both still standing — fight continues next round
      - "flee"    player chose to flee (flee=True)
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
        # Both alive — neither side is finished; the fight resumes next round.
        result_str = "ongoing"

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


def use_item(player: Player, item_name: str) -> tuple[Player, str]:
    """Use a consumable item from the player's inventory.

    Looks up the item in PHASE_0_BIBLE items. If found and the player has it,
    consumes one and applies the effect. Returns (updated_player, message).
    """
    if not player.inventory:
        return player, "你身上没有携带任何物品。"

    # Find the item by name (case-insensitive partial match)
    item = None
    matched = [i for i in player.inventory if item_name in i]
    if not matched:
        return player, f"你没有{item_name}。"
    item_key = matched[0]

    # Look up the item spec
    item_spec = None
    for spec in PHASE_0_BIBLE.items:
        if spec.name in item_key:
            item_spec = spec
            break

    new_inv = list(player.inventory)
    new_inv.remove(item_key)
    new_p = player.model_copy(update={"inventory": new_inv})

    # Apply effect based on item spec
    effect_msg = ""
    if item_spec and item_spec.effect:
        if "增益灵力" in item_spec.effect or "灵力" in item_spec.effect:
            gain = 10 if item_spec.rarity == "灵" else 3
            new_p = new_p.model_copy(update={"spirit_power": new_p.spirit_power + gain})
            effect_msg = f"灵力+{gain}"
        if "恢复气血" in item_spec.effect or "气血" in item_spec.effect:
            heal = 25 if item_spec.rarity == "灵" else 10
            new_hp = min(new_p.max_hp, new_p.hp + heal)
            new_p = new_p.model_copy(update={"hp": new_hp})
            effect_msg += f"，气血+{heal}"
        if "气血上限" in item_spec.effect:
            new_p = new_p.model_copy(update={"max_hp": new_p.max_hp + 10, "hp": new_p.hp + 10})
            effect_msg = "气血上限+10"
        if "解除" in item_spec.effect:
            effect_msg = "毒素已清除"
    else:
        effect_msg = "但似乎没有什么效果。"

    msg = f"使用了{item_key}。{effect_msg}。" if effect_msg else f"使用了{item_key}。"
    return new_p, msg