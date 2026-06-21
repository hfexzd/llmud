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
    WorldState,
    QuestState,
    PHASE_0_BIBLE,
)
from engine.world import WorldEngine, tension_tick


def _ws(player: Player) -> WorldState:
    """Run the tension machine against a fresh world state so the 所务
    derivation methods have up-to-date tension statuses to project."""
    return tension_tick(WorldState(), PHASE_0_BIBLE, player)


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
# TestResolveSceneMove
# -------------------------------------------------------------------


# -------------------------------------------------------------------
# TestCurrentGoal
# -------------------------------------------------------------------


class TestCurrentGoal:
    def test_fresh_player_gets_bamboo_goal(self, engine: WorldEngine, fresh_player: Player):
        """A new player has not visited 竹林, so the first objective is to go there."""
        goal = engine.current_goal(fresh_player, _ws(fresh_player), PHASE_0_BIBLE)
        assert goal is not None
        assert goal.id == "venture_bamboo"

    def test_after_visiting_bamboo_advances_to_anomaly(self, engine: WorldEngine):
        player = Player(visited_scenes=["outer_gate", "bamboo_forest"])
        goal = engine.current_goal(player, _ws(player), PHASE_0_BIBLE)
        assert goal is not None
        assert goal.id == "probe_anomaly"

    def test_after_spirit_herb_advances_to_breakthrough(self, engine: WorldEngine):
        player = Player(visited_scenes=["bamboo_forest"], seen_events=["spirit_herb"])
        goal = engine.current_goal(player, _ws(player), PHASE_0_BIBLE)
        assert goal is not None
        assert goal.id == "cultivate_breakthrough"

    def test_after_breakthrough_advances_to_mountain(self, engine: WorldEngine):
        player = Player(
            level="练气期二层", visited_scenes=["bamboo_forest"], seen_events=["spirit_herb"],
        )
        goal = engine.current_goal(player, _ws(player), PHASE_0_BIBLE)
        assert goal is not None
        assert goal.id == "venture_mountain"

    def test_all_done_returns_none(self, engine: WorldEngine):
        player = Player(
            level="练气期二层", visited_scenes=["bamboo_forest", "mountain_range"],
            seen_events=["spirit_herb"],
        )
        assert engine.current_goal(player, _ws(player), PHASE_0_BIBLE) is None

    def test_goal_never_leaks_english_id(self, engine: WorldEngine, fresh_player: Player):
        """The 所务 label is player-facing in-world text — never a raw id."""
        goal = engine.current_goal(fresh_player, _ws(fresh_player), PHASE_0_BIBLE)
        assert goal is not None
        assert goal.id not in goal.label


class TestResolveSceneMove:
    def test_exact_scene_id(self, engine: WorldEngine, fresh_player: Player):
        status, result = engine.resolve_scene_move(fresh_player, "inner_gate")
        assert status == "ok"
        assert result == "inner_gate"

    def test_exact_full_name(self, engine: WorldEngine, fresh_player: Player):
        status, result = engine.resolve_scene_move(fresh_player, "青云门内门")
        assert status == "ok"
        assert result == "inner_gate"

    def test_short_alias(self, engine: WorldEngine, fresh_player: Player):
        status, result = engine.resolve_scene_move(fresh_player, "去内门")
        assert status == "ok"
        assert result == "inner_gate"

    def test_natural_language_phrase(self, engine: WorldEngine, fresh_player: Player):
        """The reported bug: '去内门灵泉旁修炼' must resolve to inner_gate."""
        status, result = engine.resolve_scene_move(fresh_player, "去内门灵泉旁修炼")
        assert status == "ok"
        assert result == "inner_gate"

    def test_unreachable_scene(self, engine: WorldEngine, fresh_player: Player):
        # bamboo_forest is not directly connected to outer_gate
        status, result = engine.resolve_scene_move(fresh_player, "去竹林")
        assert status == "error"
        # Error must use Chinese scene names, never raw ids
        assert "青云门外门" in result
        assert "幽竹林" in result

    def test_unknown_destination(self, engine: WorldEngine, fresh_player: Player):
        status, result = engine.resolve_scene_move(fresh_player, "去火星")
        assert status == "error"
        # In-world fallback — no system-style "未知地点: X"
        assert "寻不到这般去处" in result

    def test_empty_destination(self, engine: WorldEngine, fresh_player: Player):
        status, result = engine.resolve_scene_move(fresh_player, "")
        assert status == "error"
        assert "寻不到这般去处" in result

    def test_landmark_altar(self, engine: WorldEngine, fresh_player: Player):
        """A landmark introduced by DM narration ('去祭坛看看') resolves to its scene."""
        status, result = engine.resolve_scene_move(fresh_player, "去祭坛看看")
        assert status == "ok"
        assert result == "inner_gate"

    def test_landmark_spring(self, engine: WorldEngine, fresh_player: Player):
        status, result = engine.resolve_scene_move(fresh_player, "去灵泉")
        assert status == "ok"
        assert result == "inner_gate"

    def test_landmark_in_current_scene_is_noop(self, engine: WorldEngine, fresh_player: Player):
        """A landmark in the player's current scene is a local move, not a failed transition."""
        # fresh_player is at outer_gate, whose landmarks include 柴房
        status, result = engine.resolve_scene_move(fresh_player, "去柴房")
        assert status == "ok"
        assert result == "outer_gate"


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


# -------------------------------------------------------------------
# TestEdgeCases
# -------------------------------------------------------------------


class TestEdgeCases:
    def test_event_does_not_repeat(self, engine: WorldEngine):
        """One-time events should not trigger again after being seen."""
        player = Player(current_scene="outer_gate", seen_events=["faint_spirit_sense", "visited_outer_gate"])
        event = engine.check_events("outer_gate", player)
        # faint_spirit_sense should not trigger again
        assert event is None or event.id != "faint_spirit_sense"

    def test_only_one_event_per_check(self, engine: WorldEngine):
        """check_events should return at most one event."""
        player = Player(current_scene="outer_gate")
        event = engine.check_events("outer_gate", player)
        # Just verify it returns at most one
        assert event is None or isinstance(event, WorldEvent)

    def test_move_to_nonexistent_scene(self, engine: WorldEngine):
        """Moving to a nonexistent scene should fail."""
        result = engine.validate_move("outer_gate", "nonexistent")
        assert result is False

    def test_npc_schedule_outside_range(self, engine: WorldEngine):
        """NPCs should be at default scene outside schedule range."""
        # At tick 25, linwaner should be back at inner_gate
        npcs = engine.get_npcs_in_scene("market", 25)
        assert "linwaner" not in npcs
        npcs_at_inner = engine.get_npcs_in_scene("inner_gate", 25)
        assert "linwaner" in npcs_at_inner


# -------------------------------------------------------------------
# TestQuestStateModel
# -------------------------------------------------------------------


class TestQuestStateModel:
    def test_quest_state_defaults(self):
        from engine.models import QuestState
        q = QuestState(id="venture_bamboo", status="active", unlocked_tick=0)
        assert q.status == "active"
        assert q.completed_tick is None
        assert q.unlocked_tick == 0

    def test_player_has_empty_quests_by_default(self):
        from engine.models import Player
        assert Player().quests == []


# -------------------------------------------------------------------
# TestQuestLog
# -------------------------------------------------------------------


class TestQuestLog:
    def test_fresh_visible_quests_shows_only_venture_bamboo(self, engine: WorldEngine):
        """A new player has only venture_bamboo unlocked (it is always unlocked)."""
        player = Player()
        v = engine.visible_quests(player, _ws(player), PHASE_0_BIBLE)
        ids = [q["id"] for q in v]
        assert ids == ["venture_bamboo"]
        assert v[0]["status"] == "active"

    def test_visible_after_bamboo_shows_completed_plus_anomaly(self, engine: WorldEngine):
        player = Player(visited_scenes=["outer_gate", "bamboo_forest"])
        v = {
            q["id"]: q["status"]
            for q in engine.visible_quests(player, _ws(player), PHASE_0_BIBLE)
        }
        assert v["venture_bamboo"] == "completed"
        assert v["probe_anomaly"] == "active"
        # cultivate/venture not unlocked yet -> not visible
        assert "cultivate_breakthrough" not in v
        assert "venture_mountain" not in v

    def test_next_quest_is_first_locked(self, engine: WorldEngine):
        assert engine.next_quest(Player(), _ws(Player()), PHASE_0_BIBLE).id == "probe_anomaly"
        player = Player(visited_scenes=["bamboo_forest"], seen_events=["spirit_herb"])
        assert engine.next_quest(player, _ws(player), PHASE_0_BIBLE).id == "venture_mountain"

    def test_next_quest_none_when_all_unlocked(self, engine: WorldEngine):
        player = Player(
            level="练气期二层", visited_scenes=["bamboo_forest"], seen_events=["spirit_herb"],
        )
        assert engine.next_quest(player, _ws(player), PHASE_0_BIBLE) is None

    def test_update_quests_records_completed_tick(self, engine: WorldEngine):
        player = Player(tick=3, visited_scenes=["outer_gate", "bamboo_forest"])
        updated = engine.update_quests(player, _ws(player), PHASE_0_BIBLE)
        rec = next(q for q in updated.quests if q.id == "venture_bamboo")
        assert rec.status == "completed"
        assert rec.completed_tick == 3

    def test_completed_quest_expires_after_6_ticks(self, engine: WorldEngine):
        # venture_bamboo was completed at tick 2; now at tick 8 (>= 6 later)
        player = Player(
            tick=8, visited_scenes=["outer_gate", "bamboo_forest"],
            quests=[QuestState(id="venture_bamboo", status="completed",
                               unlocked_tick=0, completed_tick=2)],
        )
        v = engine.visible_quests(player, _ws(player), PHASE_0_BIBLE)
        assert "venture_bamboo" not in [q["id"] for q in v]

    def test_completed_quest_visible_within_6_ticks(self, engine: WorldEngine):
        player = Player(
            tick=5, visited_scenes=["outer_gate", "bamboo_forest"],
            quests=[QuestState(id="venture_bamboo", status="completed",
                               unlocked_tick=0, completed_tick=2)],
        )
        v = {
            q["id"]: q["status"]
            for q in engine.visible_quests(player, _ws(player), PHASE_0_BIBLE)
        }
        assert v["venture_bamboo"] == "completed"

    def test_current_goal_gated_on_unlock(self, engine: WorldEngine):
        """current_goal = first active tension; venture_bamboo is always active
        for a fresh player, so behavior matches the old GOALS-iteration."""
        assert engine.current_goal(Player(), _ws(Player()), PHASE_0_BIBLE).id == "venture_bamboo"
        player = Player(
            level="练气期二层", visited_scenes=["bamboo_forest", "mountain_range"],
            seen_events=["spirit_herb"],
        )
        assert engine.current_goal(player, _ws(player), PHASE_0_BIBLE) is None