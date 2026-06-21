"""Flow governor (M7). Tracks challenge-skill match and adjusts world pacing.

Records recent challenge outcomes (combat results, tension resolutions) and
dynamically adjusts world_pressure accumulation rate and tension difficulty
thresholds to keep the player in the flow channel. Hysteresis prevents
oscillation.
"""

from __future__ import annotations


CHALLENGE_WINDOW = 5
PRESSURE_RATE_BASE = 1.0
PRESSURE_RATE_MIN = 0.5
PRESSURE_RATE_MAX = 2.0


class FlowGovernor:
    """Tracks challenge-skill match and adjusts world pacing."""

    def __init__(self):
        self._challenge_history: list[str] = []

    def record_outcome(self, outcome: str) -> None:
        """Record a challenge outcome: 'win', 'fair', or 'struggle'."""
        self._challenge_history.append(outcome)
        if len(self._challenge_history) > CHALLENGE_WINDOW:
            self._challenge_history.pop(0)

    @property
    def pressure_rate(self) -> float:
        """Return the current pressure accumulation multiplier."""
        if len(self._challenge_history) < 3:
            return PRESSURE_RATE_BASE
        wins = self._challenge_history.count("win")
        struggles = self._challenge_history.count("struggle")
        if wins >= 3:
            return min(PRESSURE_RATE_MAX, PRESSURE_RATE_BASE + 0.2 * wins)
        if struggles >= 3:
            return max(PRESSURE_RATE_MIN, PRESSURE_RATE_BASE - 0.2 * struggles)
        return PRESSURE_RATE_BASE

    @property
    def difficulty_offset(self) -> int:
        """Adjustment to tension difficulty checks (-1, 0, or +1)."""
        rate = self.pressure_rate
        if rate > 1.5:
            return 1  # harder
        if rate < 0.7:
            return -1  # easier
        return 0
