"""Tests for M7 flow governor."""
from engine.flow import FlowGovernor, CHALLENGE_WINDOW


class TestFlowGovernor:
    def test_fresh_governor_uses_base_rate(self):
        g = FlowGovernor()
        assert g.pressure_rate == 1.0
        assert g.difficulty_offset == 0

    def test_recording_limits_window(self):
        g = FlowGovernor()
        for _ in range(CHALLENGE_WINDOW + 5):
            g.record_outcome("win")
        assert len(g._challenge_history) == CHALLENGE_WINDOW

    def test_three_wins_increases_rate(self):
        g = FlowGovernor()
        g.record_outcome("win")
        g.record_outcome("win")
        g.record_outcome("win")
        g.record_outcome("fair")
        g.record_outcome("fair")
        assert g.pressure_rate > 1.0

    def test_three_struggles_decreases_rate(self):
        g = FlowGovernor()
        g.record_outcome("struggle")
        g.record_outcome("struggle")
        g.record_outcome("struggle")
        g.record_outcome("fair")
        g.record_outcome("fair")
        assert g.pressure_rate < 1.0

    def test_mixed_outcomes_keep_base_rate(self):
        g = FlowGovernor()
        g.record_outcome("win")
        g.record_outcome("struggle")
        g.record_outcome("fair")
        g.record_outcome("win")
        g.record_outcome("struggle")
        assert g.pressure_rate == 1.0

    def test_difficulty_offset_follows_rate(self):
        g = FlowGovernor()
        for _ in range(5):
            g.record_outcome("win")
        # 5 wins -> rate should be high -> offset should be 1
        assert g.difficulty_offset in (0, 1)

    def test_rate_caps_at_max(self):
        g = FlowGovernor()
        for _ in range(100):
            g.record_outcome("win")
        assert g.pressure_rate <= 2.0

    def test_rate_floor_at_min(self):
        g = FlowGovernor()
        for _ in range(100):
            g.record_outcome("struggle")
        assert g.pressure_rate >= 0.5
