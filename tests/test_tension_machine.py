"""Tests for the tension condition evaluator + phase-0 tension data (M2)."""
from engine.models import (
    Player, WorldState, PHASE_0_BIBLE, ResolvedTension,
)
from engine.world import evaluate_condition


class TestEvaluateCondition:
    def test_empty_condition_is_true(self):
        assert evaluate_condition({}, Player(), WorldState()) is True

    def test_always_true(self):
        assert evaluate_condition({"always": True}, Player(), WorldState()) is True

    def test_always_false(self):
        assert evaluate_condition({"always": False}, Player(), WorldState()) is False

    def test_visited_present(self):
        p = Player(visited_scenes=["bamboo_forest"])
        assert evaluate_condition({"visited": "bamboo_forest"}, p, WorldState()) is True

    def test_visited_absent(self):
        p = Player(visited_scenes=["outer_gate"])
        assert evaluate_condition({"visited": "bamboo_forest"}, p, WorldState()) is False

    def test_seen_event_present(self):
        p = Player(seen_events=["spirit_herb"])
        assert evaluate_condition({"seen_event": "spirit_herb"}, p, WorldState()) is True

    def test_seen_event_absent(self):
        assert evaluate_condition({"seen_event": "spirit_herb"}, Player(), WorldState()) is False

    def test_level_match(self):
        p = Player(level="练气期二层")
        assert evaluate_condition({"level": "练气期二层"}, p, WorldState()) is True

    def test_level_mismatch(self):
        p = Player(level="练气期一层")
        assert evaluate_condition({"level": "练气期二层"}, p, WorldState()) is False

    def test_min_spirit_meets(self):
        p = Player(spirit_power=25)
        assert evaluate_condition({"min_spirit": 20}, p, WorldState()) is True

    def test_min_spirit_below(self):
        p = Player(spirit_power=10)
        assert evaluate_condition({"min_spirit": 20}, p, WorldState()) is False

    def test_min_tick_meets(self):
        p = Player(tick=5)
        assert evaluate_condition({"min_tick": 5}, p, WorldState()) is True

    def test_min_tick_below(self):
        p = Player(tick=3)
        assert evaluate_condition({"min_tick": 5}, p, WorldState()) is False

    def test_tension_resolved_present(self):
        ws = WorldState(resolved_tensions=[
            ResolvedTension(tension_id="venture_bamboo", resolved_tick=2, path_id="reach_bamboo"),
        ])
        assert evaluate_condition({"tension_resolved": "venture_bamboo"}, Player(), ws) is True

    def test_tension_resolved_absent(self):
        assert evaluate_condition({"tension_resolved": "venture_bamboo"}, Player(), WorldState()) is False

    def test_and_semantics_all_must_hold(self):
        p = Player(visited_scenes=["bamboo_forest"], seen_events=["spirit_herb"])
        assert evaluate_condition(
            {"visited": "bamboo_forest", "seen_event": "spirit_herb"}, p, WorldState()
        ) is True
        assert evaluate_condition(
            {"visited": "bamboo_forest", "seen_event": "no_such_event"}, p, WorldState()
        ) is False

    def test_unknown_predicate_fails_safe(self):
        assert evaluate_condition({"bogus": 1}, Player(), WorldState()) is False


class TestPhase0Tensions:
    """The 4 phase-0 tensions map 1:1 to the existing 4 venture_* goals:
    trigger == goal unlock condition, resolution == goal satisfy condition."""

    def _spec(self, tid: str):
        return next(t for t in PHASE_0_BIBLE.tensions if t.id == tid)

    def test_four_tensions_in_priority_order(self):
        ids = [t.id for t in PHASE_0_BIBLE.tensions]
        assert ids == [
            "venture_bamboo", "probe_anomaly",
            "cultivate_breakthrough", "venture_mountain",
        ]

    def test_venture_bamboo_trigger_always_resolution_visited_bamboo(self):
        s = self._spec("venture_bamboo")
        assert evaluate_condition(s.trigger.conditions, Player(), WorldState()) is True
        assert evaluate_condition(
            s.resolution_paths[0].condition,
            Player(visited_scenes=["bamboo_forest"]), WorldState(),
        ) is True
        assert evaluate_condition(
            s.resolution_paths[0].condition,
            Player(visited_scenes=["outer_gate"]), WorldState(),
        ) is False

    def test_probe_anomaly_trigger_visited_bamboo_resolution_seen_herb(self):
        s = self._spec("probe_anomaly")
        assert evaluate_condition(
            s.trigger.conditions, Player(visited_scenes=["bamboo_forest"]), WorldState()
        ) is True
        assert evaluate_condition(s.trigger.conditions, Player(), WorldState()) is False
        assert evaluate_condition(
            s.resolution_paths[0].condition,
            Player(seen_events=["spirit_herb"]), WorldState(),
        ) is True

    def test_cultivate_breakthrough_trigger_seen_herb_resolution_level(self):
        s = self._spec("cultivate_breakthrough")
        assert evaluate_condition(
            s.trigger.conditions, Player(seen_events=["spirit_herb"]), WorldState()
        ) is True
        assert evaluate_condition(
            s.resolution_paths[0].condition, Player(level="练气期二层"), WorldState()
        ) is True
        assert evaluate_condition(
            s.resolution_paths[0].condition, Player(level="练气期一层"), WorldState()
        ) is False

    def test_venture_mountain_trigger_level_resolution_visited_mountain(self):
        s = self._spec("venture_mountain")
        assert evaluate_condition(
            s.trigger.conditions, Player(level="练气期二层"), WorldState()
        ) is True
        assert evaluate_condition(
            s.trigger.conditions, Player(level="练气期一层"), WorldState()
        ) is False
        assert evaluate_condition(
            s.resolution_paths[0].condition,
            Player(visited_scenes=["mountain_range"]), WorldState(),
        ) is True