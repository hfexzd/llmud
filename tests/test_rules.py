from engine.models import Player, Encounter, LEVEL_TABLE
from engine.rules import (
    compute_attack, compute_defense, cultivate,
    resolve_combat, check_breakthrough, move
)


def test_compute_attack_practitioner_layer_1():
    """练气期一层: attack = spirit_power × 1.0"""
    player = Player(
        id="p1", name="张铁柱", level="练气期一层", spirit_power=10,
        hp=100, max_hp=100, affinity="火", current_scene="青云门外门柴房",
        inventory=[]
    )
    assert compute_attack(player) == 10


def test_compute_defense_practitioner_layer_1():
    """练气期一层: defense = floor(spirit_power / 2) + 5"""
    player = Player(
        id="p1", name="张铁柱", level="练气期一层", spirit_power=10,
        hp=100, max_hp=100, affinity="火", current_scene="青云门外门柴房",
        inventory=[]
    )
    assert compute_defense(player) == 10  # floor(10/2) + 5 = 10


def test_cultivate_increases_spirit_power():
    player = Player(id="p1", name="张铁柱", level="练气期一层", spirit_power=10,
                    hp=100, max_hp=100, affinity="火", current_scene="青云门外门柴房", inventory=[])
    result = cultivate(player)
    assert result.spirit_power >= 11
    assert result.spirit_power <= 13
    # Original unchanged (pure function)
    assert player.spirit_power == 10


def test_resolve_combat_win():
    player = Player(id="p1", name="张铁柱", level="练气期一层", spirit_power=50,
                    hp=100, max_hp=100, affinity="火", current_scene="外门", inventory=[])
    enemy = Encounter(id="e1", name="赤眼妖狼", attack=8, defense=3, hp=30, max_hp=30)
    result, updated_player, updated_enemy = resolve_combat(player, enemy)
    # attack=50*1.0=50, dmg_to_enemy=max(1,50-3)=47
    assert result.dmg_to_enemy == 47
    assert result.result == "win"
    assert updated_enemy.hp == 0  # 30 - 47 clamped to 0


def test_resolve_combat_flee():
    player = Player(id="p1", name="张铁柱", level="练气期一层", spirit_power=10,
                    hp=100, max_hp=100, affinity="火", current_scene="外门", inventory=[])
    enemy = Encounter(id="e1", name="赤眼妖狼", attack=8, defense=3, hp=30, max_hp=30)
    result, _, _ = resolve_combat(player, enemy, flee=True)
    assert result.result == "flee"
    assert result.dmg_to_enemy == 0
    assert result.dmg_to_player == 0


def test_check_breakthrough_qualifies():
    player = Player(id="p1", name="张铁柱", level="练气期一层", spirit_power=30,
                    hp=100, max_hp=100, affinity="火", current_scene="外门", inventory=[])
    result = check_breakthrough(player)
    assert result is not None
    assert result.from_level == "练气期一层"
    assert result.to_level == "练气期二层"


def test_check_breakthrough_not_yet():
    player = Player(id="p1", name="张铁柱", level="练气期一层", spirit_power=15,
                    hp=100, max_hp=100, affinity="火", current_scene="外门", inventory=[])
    result = check_breakthrough(player)
    assert result is None


def test_move_to_connected_scene():
    player = Player(current_scene="outer_gate")
    result = move(player, "inner_gate")
    assert result.current_scene == "inner_gate"


def test_move_to_invalid_scene():
    player = Player(current_scene="outer_gate")
    result = move(player, "mountain_range")
    assert result.current_scene == "outer_gate"


def test_move_preserves_other_fields():
    player = Player(current_scene="outer_gate", spirit_power=42, hp=80)
    result = move(player, "inner_gate")
    assert result.spirit_power == 42
    assert result.hp == 80
    assert result.current_scene == "inner_gate"