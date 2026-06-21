"""Tests for the tension condition evaluator + phase-0 tension data (M2)."""
from engine.models import (
    Player, WorldState, PHASE_0_BIBLE, ResolvedTension, TensionRuntime,
)
from engine.world import evaluate_condition, tension_tick


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


class TestTensionTick:
    def test_dormant_to_active_when_trigger_met(self):
        # venture_bamboo trigger is {always}; fresh player → active
        out = tension_tick(WorldState(), PHASE_0_BIBLE, Player(tick=1))
        assert out.tensions["venture_bamboo"].status == "active"
        assert out.tensions["venture_bamboo"].activated_tick == 1

    def test_dormant_stays_dormant_when_trigger_unmet(self):
        out = tension_tick(WorldState(), PHASE_0_BIBLE, Player())
        assert out.tensions["probe_anomaly"].status == "dormant"
        assert out.tensions["cultivate_breakthrough"].status == "dormant"
        assert out.tensions["venture_mountain"].status == "dormant"

    def test_active_to_resolved_when_resolution_met(self):
        p = Player(tick=2, visited_scenes=["bamboo_forest"])
        out = tension_tick(WorldState(), PHASE_0_BIBLE, p)
        assert out.tensions["venture_bamboo"].status == "resolved"
        assert out.tensions["venture_bamboo"].resolved_tick == 2
        assert out.tensions["venture_bamboo"].resolved_path == "reach_bamboo"
        # probe_anomaly trigger (visited bamboo) now met → active same tick
        assert out.tensions["probe_anomaly"].status == "active"

    def test_resolved_tension_appended_with_summary(self):
        p = Player(tick=2, visited_scenes=["bamboo_forest"])
        out = tension_tick(WorldState(), PHASE_0_BIBLE, p)
        rt = [r for r in out.resolved_tensions if r.tension_id == "venture_bamboo"]
        assert len(rt) == 1
        assert rt[0].resolved_tick == 2
        assert rt[0].path_id == "reach_bamboo"
        assert rt[0].summary == "抵达幽竹林"

    def test_already_resolved_stays_resolved_no_duplicate(self):
        ws = WorldState(
            tensions={"venture_bamboo": TensionRuntime(
                status="resolved", resolved_tick=1, resolved_path="reach_bamboo")},
            resolved_tensions=[ResolvedTension(
                tension_id="venture_bamboo", resolved_tick=1, path_id="reach_bamboo",
                summary="抵达幽竹林")],
        )
        out = tension_tick(ws, PHASE_0_BIBLE, Player(tick=2, visited_scenes=["bamboo_forest"]))
        assert out.tensions["venture_bamboo"].status == "resolved"
        rts = [r for r in out.resolved_tensions if r.tension_id == "venture_bamboo"]
        assert len(rts) == 1  # no duplicate appended

    def test_world_pressure_is_sum_of_active_pressure_weights(self):
        # fresh: only venture_bamboo active (weight 1) → pressure 1
        out = tension_tick(WorldState(), PHASE_0_BIBLE, Player())
        assert out.world_pressure == 1
        # at 二层 + seen herb + visited bamboo: only venture_mountain active (weight 1)
        p = Player(level="练气期二层", visited_scenes=["bamboo_forest"], seen_events=["spirit_herb"])
        out2 = tension_tick(WorldState(), PHASE_0_BIBLE, p)
        assert out2.tensions["venture_mountain"].status == "active"
        assert out2.world_pressure == 1

    def test_resolved_tension_does_not_count_to_pressure(self):
        p = Player(tick=2, visited_scenes=["bamboo_forest"])
        out = tension_tick(WorldState(), PHASE_0_BIBLE, p)
        # venture_bamboo resolved (not counted); probe_anomaly active (weight 1)
        assert out.world_pressure == 1

    def test_purity_does_not_mutate_input(self):
        ws = WorldState()
        out = tension_tick(ws, PHASE_0_BIBLE, Player())
        assert out is not ws
        assert ws.tensions == {}  # input untouched
        assert ws.world_pressure == 0

    def test_full_arc_resolves_first_three_activates_mountain(self):
        p = Player(level="练气期二层", visited_scenes=["bamboo_forest"], seen_events=["spirit_herb"])
        out = tension_tick(WorldState(), PHASE_0_BIBLE, p)
        assert out.tensions["venture_bamboo"].status == "resolved"
        assert out.tensions["probe_anomaly"].status == "resolved"
        assert out.tensions["cultivate_breakthrough"].status == "resolved"
        assert out.tensions["venture_mountain"].status == "active"
        assert len(out.resolved_tensions) == 3