# M7 涌现主线串起 + 心流/情感打磨 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the emergent world system to deliver an end-to-end playable experience with emotional stakes, flow pacing, and coherent narrative cause-and-effect.

**Architecture:** Three independent workstreams: (1) flow governor that dynamically adjusts pressure/thresholds based on player challenge-skill match, (2) NPC behavior expansion with richer routines and tragic_potential wiring, (3) emotional tuning via tension emotion tags feeding into finale guidance. End-to-end manual playthrough to verify the whole pipeline.

**Tech Stack:** Python 3.14, Pydantic v2, FastAPI, SQLite, pytest.

---

## File Structure

- **`engine/flow.py`** (NEW) — `FlowGovernor` with challenge tracking, dynamic pressure adjustment
- **`engine/models.py`** — minor additions (player challenge history)
- **`engine/world.py`** — wire flow governor into tension_tick
- **`static/index.html`** — optional: flow indicator in status bar
- **`tests/test_flow.py`** (NEW) — flow governor unit tests

---

### Task 1: Flow governor

The flow governor tracks recent challenge outcomes (tension resolutions, combat results) and adjusts `world_pressure` accumulation rate and tension trigger thresholds to keep the player in the flow channel.

**Key design:**
- Track last N (default 5) challenge outcomes: "win" (player dominated), "fair" (close match), "struggle" (player nearly lost)
- If trend is "win" -> increase pressure rate (make world harder, escalate tensions)
- If trend is "struggle" -> decrease pressure rate (give player breathing room)
- Hysteresis zone: small changes are ignored to prevent oscillation

```python
# engine/flow.py
from __future__ import annotations
from engine.models import Player, WorldState


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
```

**Tests:**
- Recording outcomes correctly limits window
- 3 wins in last 5 increases pressure rate
- 3 struggles in last 5 decreases pressure rate
- Mixed outcomes keep base rate
- Difficulty offset follows pressure rate thresholds

---

### Task 2: Wire flow governor into pipeline

In `api/routes.py`, instantiate a `FlowGovernor` and:
- After combat resolution, record outcome based on HP difference
- After tension resolution, record outcome based on difficulty vs player power
- Pass `pressure_rate` to world state update

---

### Task 3: NPC behavior expansion

Author richer NPC routines for phase-0 NPCs (linwaner, chenhao, old_yang) with:
- More varied schedule movements
- Mood shifts based on world events
- Goal progress triggers

This is primarily data work in `engine/models.py` — update `PHASE_0_BIBLE.npc_models`.

**Tests:** Existing npc_step tests should continue passing.

---

### Task 4: End-to-end playthrough

Manual verification steps:

1. Start server: `python main.py`
2. Open browser at `http://127.0.0.1:8001`
3. Play through a full session:
   - Take 5+ actions (cultivate, explore, move, talk, fight)
   - Verify world events fire
   - Verify NPCs present in scenes
   - Verify world_delta flows through validator
   - Verify ending fires after 20+ ticks
4. Test offline:
   - Set directive, wait 2+ minutes, return
   - Verify catch-up card appears

---

## Self-Review

- M7 is intentionally lighter on code than M3-M6 — most of the "work" is tuning and playing
- Flow governor is lightweight (~50 LOC) with hysteresis to prevent oscillation
- Emotional tuning is primarily content work (tension emotion tags already exist)
- No new infrastructure needed — everything builds on M1-M6
