"""Tests for the M4 ending system."""
from engine.models import (
    WorldState, Player, PHASE_0_BIBLE,
    TensionRuntime, ResolvedTension, TERMINAL_ARCHETYPES,
)
from engine.ending import check_ending


def test_sealed_returns_none_before_wanderer():
    """A sealed world returns None even though wanderer (always: True) would match."""
    ws = WorldState(tensions={}, sealed=True)
    result = check_ending(ws, PHASE_0_BIBLE, Player())
    assert result is None


def test_ascension_hits_when_level_met():
    """Player at 筑基期 triggers ascension ending."""
    ws = WorldState(tensions={})
    result = check_ending(ws, PHASE_0_BIBLE, Player(level="筑基期"))
    assert result == "ascension"


def test_wanderer_fires_as_fallback_after_min_tick():
    """When no other condition is met and min_tick is satisfied, wanderer fires."""
    ws = WorldState(tensions={})
    result = check_ending(ws, PHASE_0_BIBLE, Player(tick=510))
    assert result == "wanderer"


def test_wanderer_does_not_fire_before_min_tick():
    """Before min_tick threshold, wanderer (the fallback) does not fire."""
    ws = WorldState(tensions={})
    result = check_ending(ws, PHASE_0_BIBLE, Player(tick=200))
    assert result is None


def test_demonic_hits_when_tension_resolved():
    """Ending with tension_resolved condition fires when that tension is resolved."""
    ws = WorldState(
        resolved_tensions=[ResolvedTension(
            tension_id="demonic_temptation", resolved_tick=10, path_id="succumb",
        )],
    )
    result = check_ending(ws, PHASE_0_BIBLE, Player())
    assert result == "demonic"


def test_priority_orders_archetypes():
    """When multiple conditions match, the highest priority fires."""
    ws = WorldState(
        resolved_tensions=[ResolvedTension(
            tension_id="lost_love", resolved_tick=10, path_id="part_ways",
        )],
    )
    # unrequited (priority 7) and wanderer (priority 1) both match,
    # but unrequited should win.
    result = check_ending(ws, PHASE_0_BIBLE, Player())
    assert result == "unrequited"


def test_hermit_hits_when_peaceful_retreat_resolved():
    ws = WorldState(
        resolved_tensions=[ResolvedTension(
            tension_id="peaceful_retreat", resolved_tick=15, path_id="retire",
        )],
    )
    result = check_ending(ws, PHASE_0_BIBLE, Player())
    assert result == "hermit"


def test_unifier_hits_when_sect_unified_resolved():
    ws = WorldState(
        resolved_tensions=[ResolvedTension(
            tension_id="sect_unified", resolved_tick=20, path_id="unify",
        )],
    )
    result = check_ending(ws, PHASE_0_BIBLE, Player())
    assert result == "unifier"


def test_fall_hits_when_ultimate_sacrifice_resolved():
    ws = WorldState(
        resolved_tensions=[ResolvedTension(
            tension_id="ultimate_sacrifice", resolved_tick=25, path_id="sacrifice",
        )],
    )
    result = check_ending(ws, PHASE_0_BIBLE, Player())
    assert result == "fall"
