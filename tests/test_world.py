"""Tests for engine.world.WorldEngine."""

import random

import pytest

from engine.models import (
    ALL_EVENTS,
    NPC_PRESENCES,
    Player,
    SCENE_MAP,
    EventTrigger,
    WorldEvent,
)
from engine.world import WorldEngine


@pytest.fixture
def engine() -> WorldEngine:
    return WorldEngine()


@pytest.fixture
def fresh_player() -> Player:
    return Player()


# -------------------------------------------------------------------
# TestGetScene
# -------------------------------------------------------------------


class TestGetScene:
    def test_existing_scene(self, engine: WorldEngine):
        scene = engine.get_scene("outer_gate")
        assert scene is not None
        assert scene.id == "outer_gate"
        assert scene.name == "青云门外门"

    def test_nonexistent_scene_returns_none(self, engine: WorldEngine):
        assert engine.get_scene("does_not_exist") is None

    def test_all_scenes_accessible(self, engine: WorldEngine):
        for sid in ("outer_gate", "inner_gate", "bamboo_forest", "market", "mountain_range"):
            scene = engine.get_scene(sid)
            assert scene is not None, f"Scene {sid} should exist"


# -------------------------------------------------------------------
# TestGetNpcsInScene
# -------------------------------------------------------------------


class TestGetNpcsInScene:
    def test_default_scene_npc(self, engine: WorldEngine):
        """old_yang's default_scene is outer_gate."""
        npcs = engine.get_npcs_in_scene("outer_gate", tick=0)
        assert "old_yang" in npcs

    def test_schedule_moves_npc(self, engine: WorldEngine):
        """linwaner default=inner_gate, schedule sends her to market tick 10-20."""
        # At tick 5, linwaner should be at her default (inner_gate)
        npcs_inner = engine.get_npcs_in_scene("inner_gate", tick=5)
        assert "linwaner" in npcs_inner
        # At tick 15, linwaner should be at market (scheduled)
        npcs_market = engine.get_npcs_in_scene("market", tick=15)
        assert "linwaner" in npcs_market

    def test_schedule_boundary_start(self, engine: WorldEngine):
        """At tick_range start (10), linwaner should be at market."""
        npcs = engine.get_npcs_in_scene("market", tick=10)
        assert "linwaner" in npcs

    def test_schedule_boundary_end(self, engine: WorldEngine):
        """At tick_range end (20), linwaner should still be at market."""
        npcs = engine.get_npcs_in_scene("market", tick=20)
        assert "linwaner" in npcs

    def test_empty_scene_returns_empty_list(self, engine: WorldEngine):
        """bamboo_forest has no default NPCs and no schedules place NPCs there at tick 0."""
        npcs = engine.get_npcs_in_scene("bamboo_forest", tick=0)
        assert npcs == []


# -------------------------------------------------------------------
# TestCheckEvents
# -------------------------------------------------------------------


class TestCheckEvents:
    def test_location_enter_event_fires_first_time(self, engine: WorldEngine, fresh_player: Player):
        """faint_spirit_sense is a location_enter/first_time event at outer_gate."""
        event = engine.check_events("outer_gate", fresh_player)
        assert event is not None
        assert event.id == "faint_spirit_sense"

    def test_one_time_event_skipped_after_seen(self, engine: WorldEngine):
        """After a one-time event is seen, it should not fire again."""
        player = Player(seen_events=["faint_spirit_sense"])
        event = engine.check_events("outer_gate", player)
        # Should skip faint_spirit_sense, may return another event or None
        if event is not None:
            assert event.id != "faint_spirit_sense"

    def test_stat_threshold_event_fires_when_met(self, engine: WorldEngine):
        """bamboo_whisper requires min_spirit 20, scene inner_gate."""
        player = Player(spirit_power=25, current_scene="inner_gate")
        event = engine.check_events("inner_gate", player)
        # waner_worry (location_enter, higher priority) fires first for fresh player;
        # but if seen, bamboo_whisper should fire next.
        # Let's test with waner_worry already seen.
        player = Player(spirit_power=25, current_scene="inner_gate", seen_events=["waner_worry"])
        event = engine.check_events("inner_gate", player)
        assert event is not None
        assert event.id == "bamboo_whisper"

    def test_tick_interval_event(self, engine: WorldEngine):
        """market_rumor requires min_tick 5 at market."""
        player = Player(tick=7, current_scene="market")
        event = engine.check_events("market", player)
        # merchant_gossip (tick_interval, min_tick 3) has priority 3,
        # higher priority than random but lower than stat_threshold
        # At tick 7, both merchant_gossip and market_rumor qualify by tick.
        # market_rumor has min_tick 5 and is tick_interval (priority 3).
        # merchant_gossip has min_tick 3 and is tick_interval (priority 3).
        # Among same-priority, order in ALL_EVENTS matters.
        # market_rumor appears before merchant_gossip in ALL_EVENTS.
        assert event is not None

    def test_no_event_for_scene_with_none(self, engine: WorldEngine):
        """mountain_range has no events defined in ALL_EVENTS."""
        player = Player(current_scene="mountain_range")
        event = engine.check_events("mountain_range", player)
        assert event is None


# -------------------------------------------------------------------
# TestCheckNpcInteractions
# -------------------------------------------------------------------


class TestCheckNpcInteractions:
    def test_interaction_fires_when_npcs_present(self, engine: WorldEngine):
        """waner_chenhao_chat needs linwaner+chenhao at market, tick >= 5."""
        # At tick 15, linwaner is at market (scheduled), chenhao is always at market.
        interaction = engine.check_npc_interactions("market", tick=15)
        assert interaction is not None
        assert interaction.id == "waner_chenhao_chat"

    def test_no_interaction_when_tick_too_low(self, engine: WorldEngine):
        """waner_chenhao_chat requires tick_min 5."""
        interaction = engine.check_npc_interactions("market", tick=3)
        assert interaction is None


# -------------------------------------------------------------------
# TestValidateMove
# -------------------------------------------------------------------


class TestValidateMove:
    def test_valid_move(self, engine: WorldEngine):
        assert engine.validate_move("outer_gate", "inner_gate") is True

    def test_invalid_move_not_connected(self, engine: WorldEngine):
        # outer_gate does not connect directly to bamboo_forest
        assert engine.validate_move("outer_gate", "bamboo_forest") is False

    def test_invalid_move_nonexistent_source(self, engine: WorldEngine):
        assert engine.validate_move("does_not_exist", "outer_gate") is False

    def test_invalid_move_nonexistent_dest(self, engine: WorldEngine):
        assert engine.validate_move("outer_gate", "does_not_exist") is False


# -------------------------------------------------------------------
# TestAdvanceTick
# -------------------------------------------------------------------


class TestAdvanceTick:
    def test_tick_increments(self, engine: WorldEngine, fresh_player: Player):
        updated = engine.advance_tick(fresh_player)
        assert updated.tick == 1
        assert fresh_player.tick == 0  # original unchanged

    def test_tick_accumulates(self, engine: WorldEngine):
        player = Player(tick=5)
        updated = engine.advance_tick(player)
        assert updated.tick == 6


# -------------------------------------------------------------------
# TestGetEncounterForScene
# -------------------------------------------------------------------


class TestGetEncounterForScene:
    def test_scene_with_encounters(self, engine: WorldEngine):
        encounters = engine.get_encounters_for_scene("bamboo_forest")
        assert "e1" in encounters

    def test_scene_without_encounters(self, engine: WorldEngine):
        encounters = engine.get_encounters_for_scene("outer_gate")
        assert encounters == []