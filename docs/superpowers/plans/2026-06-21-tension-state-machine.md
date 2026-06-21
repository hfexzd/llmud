# 张力状态机 + 所务迁移 (M2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the M1 `tension_tick` no-op stub with a rule-driven tension state machine (dormant→active→resolved), hand-author the 4 phase-0 `TensionSpec`s that map 1:1 to the existing 4 `venture_*` goals, and migrate the 所务 system so `current_goal`/`visible_quests`/`next_quest`/`update_quests` derive from the tension machine's output instead of the fixed `GOALS` list — all deterministic, no LLM, behavior-compatible.

**Architecture:** A condition evaluator (`evaluate_condition`) interprets the `dict` predicates on `TensionTrigger.conditions` / `ResolutionPath.condition` against `(player, world_state)`. `tension_tick` runs the machine: dormant→active when the trigger holds, active→resolved when any resolution path's condition holds, accumulates `world_pressure` from active tensions, appends `ResolvedTension` history. The 所务 methods become a pure projection of `world_state.tensions[*].status` (active→current goal, resolved→completed, dormant→hidden/next), mapped to `Goal` labels via `GOAL_BY_ID` (phase-0 tension ids == goal ids, so labels/guidance are unchanged). The pipeline already loads/saves `world_state` in the M1 block; M2 threads that `world_state` + `PHASE_0_BIBLE` into the 所务 call sites.

**Tech Stack:** Python 3.14, Pydantic v2 (`model_copy`/`model_dump_json`/`model_validate_json`), FastAPI, SQLite, pytest + pytest-asyncio 1.4.0, httpx `AsyncClient`+`ASGITransport` for integration tests.

## Global Constraints

- **Rule-driven only (引擎定骨).** M2 adds NO LLM calls. `evaluate_condition`, `tension_tick`, and the 所务 methods are pure/deterministic functions of `(player, world_state, bible)`. No `world_delta`, no validator, no milestone regen, no endings, no offline — those are M3/M4/M5/M6.
- **phase-0 is hand-authored (D7).** The 4 `TensionSpec`s are hand-written in `PHASE_0_BIBLE`; LLM worldgen stays out until M5.
- **Behavior compatibility (spec §10).** The 4 phase-0 tensions map 1:1 to the existing 4 `venture_*` goals: same `id`, same priority order (`venture_bamboo`, `probe_anomaly`, `cultivate_breakthrough`, `venture_mountain`), trigger == goal unlock condition, resolution path == goal satisfy condition. Therefore the player-visible 所务 labels, guidance, and progression are identical to today. The existing `GOALS` list + `Goal` model are KEPT (source of labels/guidance); only the *selection* logic moves from GOALS-iteration to tension-status projection.
- **Test run command:** `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest <path> -v` (Windows shell). Unit tests are sync; integration tests use `@pytest.mark.asyncio` + `AsyncClient(transport=ASGITransport(app=app), base_url="http://test")` — NEVER `pytest.TestClient`.
- **TDD, DRY, YAGNI, frequent commits.** Each task: write failing test → verify it fails → minimal implementation → verify pass → commit. The condition evaluator supports only the predicates the 4 phase-0 tensions use plus the trivial near-term ones the spec lists (`always`, `visited`, `seen_event`, `level`, `min_spirit`, `min_tick`, `tension_resolved`) — no `npc_state`/`max_spirit` until a tension needs them.
- **Purity.** `evaluate_condition` and `tension_tick` are module-level pure functions returning new `WorldState`/bool; they never mutate inputs. 所务 methods return new `Player`/lists, never mutate.

---

## File Structure

- **`engine/models.py`** — add `GOAL_BY_ID: dict[str, Goal]` lookup after `GOALS`; replace `PHASE_0_BIBLE`'s empty `tensions=[]` (line 752) with the 4 hand-authored `TensionSpec`s. No new model classes (TensionSpec/ResolutionPath/TensionTrigger/TensionRuntime/ResolvedTension/WorldState all exist from M1).
- **`engine/world.py`** — add module-level `evaluate_condition(condition, player, world_state) -> bool`; replace the M1 `tension_tick` no-op stub with the real machine; refactor `WorldEngine.current_goal`/`visible_quests`/`next_quest`/`update_quests` to take `(player, world_state, bible)` and project from `world_state.tensions[*].status`; delete the now-unused `_quest_unlocked`/`_goal_satisfied`; extend the module-top import block.
- **`api/routes.py`** — thread `world_state` + `PHASE_0_BIBLE` into the 7 所务 call sites (get_status ×3, game_action ×4); `get_status` loads `world_state` from `world_repo`.
- **`tests/test_tension_machine.py`** (NEW) — `TestEvaluateCondition`, `TestPhase0Tensions`, `TestTensionTick`.
- **`tests/test_world.py`** — rewrite `TestCurrentGoal` + `TestQuestLog` to the new `(player, world_state, bible)` signatures via a `_ws(player)` helper; extend the top import block.
- **`tests/test_world_state_scaffold.py`** — delete the M1 `TestTensionTickStub.test_stub_is_noop` (superseded by `TestTensionTick`); drop the now-unused `tension_tick` from that file's import.

---

## Task 1: Condition evaluator + 4 phase-0 tensions data

**Files:**
- Modify: `engine/models.py` (add `GOAL_BY_ID` after line 209; replace line 752 `tensions=[]`)
- Modify: `engine/world.py` (add `evaluate_condition` module function; extend imports)
- Test: `tests/test_tension_machine.py` (NEW)

**Interfaces:**
- Produces: `engine.world.evaluate_condition(condition: dict, player: Player, world_state: WorldState) -> bool`; `engine.models.GOAL_BY_ID: dict[str, Goal]`; `PHASE_0_BIBLE.tensions: list[TensionSpec]` with 4 entries in priority order.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tension_machine.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_tension_machine.py -v`
Expected: FAIL — `ImportError: cannot import name 'evaluate_condition' from 'engine.world'` (and `PHASE_0_BIBLE.tensions` is empty, so `TestPhase0Tensions._spec` raises `StopIteration`).

- [ ] **Step 3: Add `GOAL_BY_ID` + the 4 phase-0 tensions to `engine/models.py`**

First, add the `GOAL_BY_ID` lookup immediately after the `GOALS` list (after the closing `]` on line 209, before the `class SceneSchedule` line 212):

```python
]


# Lookup by id for the 所务 derivation (phase-0 tensions share ids with these
# goals, so the player-visible labels/guidance stay constant when selection
# moves off the GOALS list in M2).
GOAL_BY_ID: dict[str, Goal] = {g.id: g for g in GOALS}


class SceneSchedule(BaseModel):
```

Second, replace the empty `tensions=[],` line (line 752) inside the `PHASE_0_BIBLE(...)` constructor with the 4 hand-authored tensions. The surrounding context is the end of `skills=[...]` (line 751 `],`) and `npc_models=[` (line 753):

```python
    ],
    tensions=[
        TensionSpec(
            id="venture_bamboo",
            name="同探幽竹林",
            axis=["陪伴", "探索"],
            emotion="执念",
            involved_npcs=["linwaner"],
            involved_factions=["qingyun_sect"],
            trigger=TensionTrigger(type="stat", conditions={"always": True}),
            resolution_paths=[
                ResolutionPath(
                    id="reach_bamboo",
                    label="抵达幽竹林",
                    condition={"visited": "bamboo_forest"},
                    outcome_state={},
                    ending_lean=None,
                ),
            ],
            pressure_weight=1,
            difficulty=1,
        ),
        TensionSpec(
            id="probe_anomaly",
            name="查探灵草异气",
            axis=["探索"],
            emotion="求不得",
            involved_npcs=["linwaner"],
            involved_factions=["qingyun_sect"],
            trigger=TensionTrigger(type="stat", conditions={"visited": "bamboo_forest"}),
            resolution_paths=[
                ResolutionPath(
                    id="witness_herb",
                    label="得见灵草异象",
                    condition={"seen_event": "spirit_herb"},
                    outcome_state={},
                    ending_lean=None,
                ),
            ],
            pressure_weight=1,
            difficulty=1,
        ),
        TensionSpec(
            id="cultivate_breakthrough",
            name="突破练气期二层",
            axis=["成长"],
            emotion="执念",
            involved_npcs=[],
            involved_factions=["qingyun_sect"],
            trigger=TensionTrigger(type="stat", conditions={"seen_event": "spirit_herb"}),
            resolution_paths=[
                ResolutionPath(
                    id="breakthrough",
                    label="突破至练气期二层",
                    condition={"level": "练气期二层"},
                    outcome_state={},
                    ending_lean=None,
                ),
            ],
            pressure_weight=2,
            difficulty=2,
        ),
        TensionSpec(
            id="venture_mountain",
            name="深入妖兽山脉",
            axis=["成长", "探索"],
            emotion="执念",
            involved_npcs=[],
            involved_factions=[],
            trigger=TensionTrigger(type="stat", conditions={"level": "练气期二层"}),
            resolution_paths=[
                ResolutionPath(
                    id="reach_mountain",
                    label="抵达妖兽山脉",
                    condition={"visited": "mountain_range"},
                    outcome_state={},
                    ending_lean=None,
                ),
            ],
            pressure_weight=1,
            difficulty=2,
        ),
    ],
    npc_models=[
```

- [ ] **Step 4: Add `evaluate_condition` to `engine/world.py`**

Extend the module-top import block (lines 7-24) to add `TensionRuntime`, `ResolvedTension` (needed in Task 2, imported now so the block is edited once), and `GOAL_BY_ID` (needed in Task 3, same rationale). Replace the existing import block:

```python
from engine.models import (
    NPC_PRESENCES,
    NPC_INTERACTIONS,
    ALL_EVENTS,
    ENCOUNTERS_BY_SCENE,
    SCENE_MAP,
    NPCInteraction,
    Player,
    Scene,
    WorldEvent,
    Goal,
    GOALS,
    GOAL_BY_ID,
    QuestState,
    resolve_scene_id,
    WorldState,
    WorldBible,
    NPCRuntimeState,
    TensionRuntime,
    ResolvedTension,
)
```

Then add `evaluate_condition` as a module-level pure function, placed immediately before the existing `def npc_step` (before the `# Emergent world tick` section header at line 342). Insert:

```python
# ----------------------------------------------------------------------
# Condition evaluator — interprets the dict predicates on
# TensionTrigger.conditions / ResolutionPath.condition against the player
# and world state. Pure, deterministic, no LLM. AND across keys: every key
# must hold. Unknown predicate keys fail safe (False).
# ----------------------------------------------------------------------

def evaluate_condition(condition: dict, player: Player, world_state: WorldState) -> bool:
    """Return True iff every predicate in *condition* holds for (player, world_state).

    Supported keys (AND-combined; empty dict → True):
      - always: bool             — truthy → True
      - visited: scene_id         — scene_id in player.visited_scenes
      - seen_event: event_id       — event_id in player.seen_events
      - level: 境界 str            — player.level == value
      - min_spirit: int            — player.spirit_power >= value
      - min_tick: int              — player.tick >= value
      - tension_resolved: tid       — tid in world_state.resolved_tensions
    """
    if not condition:
        return True
    visited = set(player.visited_scenes or [])
    seen = set(player.seen_events or [])
    for key, val in condition.items():
        if key == "always":
            if not val:
                return False
        elif key == "visited":
            if val not in visited:
                return False
        elif key == "seen_event":
            if val not in seen:
                return False
        elif key == "level":
            if player.level != val:
                return False
        elif key == "min_spirit":
            if player.spirit_power < val:
                return False
        elif key == "min_tick":
            if player.tick < val:
                return False
        elif key == "tension_resolved":
            if not any(rt.tension_id == val for rt in world_state.resolved_tensions):
                return False
        else:
            return False  # unknown predicate — fail safe
    return True
```

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_tension_machine.py -v`
Expected: PASS (all `TestEvaluateCondition` + `TestPhase0Tensions` tests green).

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest -v`
Expected: PASS — the M1 `TestTensionTickStub.test_stub_is_noop` still passes (tension_tick is still the no-op stub here; the real machine lands in Task 2). All 172 prior tests + the new ones green.

- [ ] **Step 7: Commit**

```bash
git add engine/models.py engine/world.py tests/test_tension_machine.py
git commit -m "feat(world): condition evaluator + 4 phase-0 tensions (M2)"
```

---

## Task 2: Tension state machine (real `tension_tick`)

**Files:**
- Modify: `engine/world.py` (replace the `tension_tick` no-op stub)
- Modify: `tests/test_world_state_scaffold.py` (delete the M1 stub test; drop unused import)
- Test: `tests/test_tension_machine.py` (extend with `TestTensionTick`)

**Interfaces:**
- Consumes: `evaluate_condition` (Task 1); `PHASE_0_BIBLE.tensions` (Task 1); `TensionRuntime`/`ResolvedTension`/`WorldState` (M1 models).
- Produces: `tension_tick(world_state: WorldState, bible: WorldBible, player: Player) -> WorldState` — the real machine. `world_state.tensions[id].status` transitions dormant→active→resolved; `world_state.world_pressure` = sum of active tensions' `pressure_weight`; `world_state.resolved_tensions` accumulates. Pure (new WorldState, input untouched). Does NOT set `tick` (the pipeline does).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tension_machine.py` (extend the top import to include `TensionRuntime`; replace the existing `from engine.models import (...)` with):

```python
from engine.models import (
    Player, WorldState, PHASE_0_BIBLE, ResolvedTension, TensionRuntime,
)
from engine.world import evaluate_condition, tension_tick
```

Then append a new class at the end of the file:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_tension_machine.py::TestTensionTick -v`
Expected: FAIL — `tension_tick` is still the M1 no-op (`out.tensions == {}`, `world_pressure` unchanged), so the status assertions fail.

- [ ] **Step 3: Replace the `tension_tick` stub with the real machine**

In `engine/world.py`, replace the entire M1 `tension_tick` function (the `def tension_tick(...)` at the end of the file, including its docstring) with:

```python
def tension_tick(world_state: WorldState, bible: WorldBible, player: Player) -> WorldState:
    """Tension state machine (M2). Rule-driven, no LLM. Pure — returns a new
    WorldState, leaves the input untouched.

    For each TensionSpec in bible priority order:
      - dormant + trigger holds  → active (sets activated_tick)
      - active + a resolution_path condition holds → resolved (sets
        resolved_tick/resolved_path, appends a ResolvedTension)
      - resolved → stable (skipped, no duplicate history entry)
    Conditions are evaluated against the *input* world_state, so a tension
    resolving this tick does not propagate to later tensions until next tick
    (deterministic, order-independent within a tick).

    world_pressure is recomputed absolutely as the sum of every active (not
    resolved) tension's pressure_weight. tick is left untouched here — the
    pipeline sets it.
    """
    new_tensions = dict(world_state.tensions)
    new_resolved = list(world_state.resolved_tensions)

    for spec in bible.tensions:
        rt = new_tensions.get(spec.id)
        if rt is not None and rt.status == "resolved":
            continue  # stable — already resolved
        if rt is None:
            rt = TensionRuntime()
        if rt.status == "dormant" and evaluate_condition(spec.trigger.conditions, player, world_state):
            rt = rt.model_copy(update={"status": "active", "activated_tick": player.tick})
        if rt.status == "active":
            for path in spec.resolution_paths:
                if evaluate_condition(path.condition, player, world_state):
                    rt = rt.model_copy(update={
                        "status": "resolved",
                        "resolved_tick": player.tick,
                        "resolved_path": path.id,
                    })
                    new_resolved.append(ResolvedTension(
                        tension_id=spec.id,
                        resolved_tick=player.tick,
                        path_id=path.id,
                        summary=path.label,
                    ))
                    break
        new_tensions[spec.id] = rt

    pressure = 0
    for spec in bible.tensions:
        rt = new_tensions.get(spec.id)
        if rt is not None and rt.status == "active":
            pressure += spec.pressure_weight

    return world_state.model_copy(update={
        "tensions": new_tensions,
        "resolved_tensions": new_resolved,
        "world_pressure": pressure,
    })
```

- [ ] **Step 4: Delete the M1 stub test + drop its unused import in `tests/test_world_state_scaffold.py`**

The M1 test `TestTensionTickStub.test_stub_is_noop` asserts `out.tensions == {}` and `out.world_pressure == 3`, which the real machine now violates. It is superseded by `TestTensionTick`. In `tests/test_world_state_scaffold.py`:

(a) Change the import on line 32 from `from engine.world import npc_step, tension_tick` to:

```python
from engine.world import npc_step
```

(b) Delete the entire `TestTensionTickStub` class (the class definition, its docstring, and its `test_stub_is_noop` method — approximately lines 70-79 in the current file). Leave the surrounding `class TestNpcStep` (above) and the later imports/classes (`from engine.models import NPCRuntimeState, TensionRuntime` onward) intact.

- [ ] **Step 5: Run the tension-machine tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_tension_machine.py -v`
Expected: PASS — all `TestEvaluateCondition`, `TestPhase0Tensions`, `TestTensionTick` green.

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest -v`
Expected: PASS — `TestTensionTickStub` is gone; the M1 pipeline test `test_action_persists_world_state_with_npc_positions` still passes (it asserts `tick`, npc positions, `sealed`, `ending` — none of which the real `tension_tick` touches; `tensions`/`world_pressure` now populate but that test does not assert them). The `test_after_*` tests in `tests/test_world.py` will FAIL here — that is expected: those call `engine.current_goal(player)` with the OLD one-arg signature, which Task 3 changes. Do NOT fix them in this task; they are fixed in Task 3. Confirm only that the failures are the expected `TypeError: current_goal() missing argument` / `AssertionError` from the 6 `TestCurrentGoal` + `TestQuestLog` tests, and that `test_tension_machine.py` + all non-所务 tests pass.

- [ ] **Step 7: Commit**

```bash
git add engine/world.py tests/test_tension_machine.py tests/test_world_state_scaffold.py
git commit -m "feat(world): rule-driven tension state machine (M2)"
```

---

## Task 3: 所务 derivation from tensions (所务迁移)

**Files:**
- Modify: `engine/world.py` (refactor `current_goal`/`visible_quests`/`next_quest`/`update_quests`; delete `_quest_unlocked`/`_goal_satisfied`)
- Modify: `tests/test_world.py` (rewrite `TestCurrentGoal` + `TestQuestLog`; extend top imports + add `_ws` helper)
- Test: `tests/test_world.py`

**Interfaces:**
- Consumes: `GOAL_BY_ID` + `PHASE_0_BIBLE.tensions` (Task 1); `world_state.tensions[*].status` produced by `tension_tick` (Task 2).
- Produces: `WorldEngine.current_goal(self, player, world_state, bible) -> Goal | None`; `visible_quests(self, player, world_state, bible) -> list[dict]`; `next_quest(self, player, world_state, bible) -> Goal | None`; `update_quests(self, player, world_state, bible) -> Player`. Removes `_quest_unlocked` / `_goal_satisfied` (replaced by `evaluate_condition` + status projection).

- [ ] **Step 1: Rewrite the breaking tests with the new signatures**

In `tests/test_world.py`, replace the top import block (lines 7-15) with:

```python
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
```

Then replace the entire `TestCurrentGoal` class (the class starting at line 186 through its last method `test_goal_never_leaks_english_id` ending ~line 231) with:

```python
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
```

Then replace the entire `TestQuestLog` class (starting at line 382 through `test_current_goal_gated_on_unlock` ending ~line 448) with:

```python
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
```

- [ ] **Step 2: Run the rewritten tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world.py::TestCurrentGoal tests/test_world.py::TestQuestLog -v`
Expected: FAIL — `TypeError: current_goal() takes 2 positional arguments but 4 were given` (the methods still have the old `(self, player)` signature).

- [ ] **Step 3: Refactor the four WorldEngine methods**

In `engine/world.py`, replace the entire `current objective (所务) + quest log` section — from the section header comment `# Current objective (所务) + quest log` (line 180) through the end of `update_quests` (line 274, just before the `# Tick progression` section header) — with:

```python
    # ------------------------------------------------------------------
    # Current objective (所务) + quest log
    #
    # 所务迁移 (spec §10): the visible 所务 list is now a projection of the
    # tension state machine's output (world_state.tensions[*].status), not a
    # fixed GOALS iteration. current_goal = first active (non-resolved)
    # tension; visible_quests = active→"active", resolved→"completed" (until
    # expiry), dormant→hidden; next_quest = first dormant tension. The
    # tension→Goal label mapping uses GOAL_BY_ID (phase-0 tension ids == goal
    # ids, so labels/guidance are unchanged — behavior compatible).
    # ------------------------------------------------------------------

    def current_goal(self, player: Player, world_state: WorldState,
                     bible: WorldBible) -> Goal | None:
        """The player's current objective: the first active (trigger-met,
        not-yet-resolved) tension, mapped to its Goal. None when no tension
        is active (the arc is complete or not yet begun past dormant)."""
        for spec in bible.tensions:
            rt = world_state.tensions.get(spec.id)
            if rt is not None and rt.status == "active":
                return GOAL_BY_ID[spec.id]
        return None

    def _quest_record(self, player: Player, goal_id: str) -> QuestState | None:
        """Return the persisted record for a goal, if any."""
        for q in player.quests or []:
            if q.id == goal_id:
                return q
        return None

    def visible_quests(self, player: Player, world_state: WorldState,
                      bible: WorldBible) -> list[dict]:
        """The visible 所务 list, derived from tension statuses. Each entry is
        {id, label, status}. Active tensions show as 'active'; resolved ones
        show as 'completed' until QUEST_EXPIRY_TICKS after their recorded
        completed_tick; dormant tensions (trigger not yet met) are hidden."""
        visible: list[dict] = []
        for spec in bible.tensions:
            rt = world_state.tensions.get(spec.id)
            if rt is None or rt.status == "dormant":
                continue
            goal = GOAL_BY_ID[spec.id]
            if rt.status == "resolved":
                rec = self._quest_record(player, spec.id)
                completed_tick = rec.completed_tick if rec else player.tick
                if player.tick - completed_tick < QUEST_EXPIRY_TICKS:
                    visible.append({"id": spec.id, "label": goal.label, "status": "completed"})
            else:
                visible.append({"id": spec.id, "label": goal.label, "status": "active"})
        return visible

    def next_quest(self, player: Player, world_state: WorldState,
                   bible: WorldBible) -> Goal | None:
        """The first dormant (not-yet-triggered) tension (preview '将解锁…'),
        or None when every tension is active or resolved."""
        for spec in bible.tensions:
            rt = world_state.tensions.get(spec.id)
            if rt is None or rt.status == "dormant":
                return GOAL_BY_ID[spec.id]
        return None

    def update_quests(self, player: Player, world_state: WorldState,
                      bible: WorldBible) -> Player:
        """Called once per action after the world tick. Records completed_tick
        for newly-resolved tensions (so the visible list can expire them) and
        prunes expired records. Returns a new Player. The visible list itself
        is derived from tension statuses; this only maintains the lifecycle
        records — it does not change what is 'true'."""
        now = player.tick
        records: dict[str, QuestState] = {q.id: q for q in player.quests or []}
        for spec in bible.tensions:
            rt = world_state.tensions.get(spec.id)
            if rt is not None and rt.status == "resolved" and spec.id not in records:
                records[spec.id] = QuestState(
                    id=spec.id, status="completed",
                    unlocked_tick=now, completed_tick=now,
                )
        kept = [
            q for q in records.values()
            if not (q.status == "completed"
                    and (now - (q.completed_tick if q.completed_tick is not None else now)) >= QUEST_EXPIRY_TICKS)
        ]
        return player.model_copy(update={"quests": list(kept)})
```

This removes the old `_quest_unlocked` and `_goal_satisfied` methods (their role is now filled by `evaluate_condition` against the tension specs, run inside `tension_tick`). Confirm those two method definitions are gone after the replacement.

- [ ] **Step 4: Run the rewritten tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world.py::TestCurrentGoal tests/test_world.py::TestQuestLog -v`
Expected: PASS — all `TestCurrentGoal` + `TestQuestLog` tests green with the new signatures, behavior identical to the old GOALS-iteration.

- [ ] **Step 5: Run the full suite (integration tests will still fail until Task 4)**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest -v`
Expected: `test_tension_machine.py` + `test_world.py` + `test_world_state_scaffold.py` unit tests PASS. The `tests/test_api.py` integration tests that hit `/player/status` and `/game/action` will FAIL here — they exercise `routes.py`, which still calls the old 2-arg signatures. That is expected and is fixed in Task 4. Confirm the only failures are `TypeError: ... takes 2 positional arguments but 3 were given` from `test_api.py`.

- [ ] **Step 6: Commit**

```bash
git add engine/world.py tests/test_world.py
git commit -m "refactor(world): derive 所务 from tension machine output (M2)"
```

---

## Task 4: Wire tension-driven 所务 into the pipeline

**Files:**
- Modify: `api/routes.py` (thread `world_state` + `PHASE_0_BIBLE` into 7 call sites; `get_status` loads `world_state`)
- Test: `tests/test_world_state_scaffold.py` (extend `TestPipelineWorldTick` with a goal-assertion test)

**Interfaces:**
- Consumes: the new 4-arg signatures from Task 3; the M1 world-tick block that loads/saves `world_state` and defines `bible = PHASE_0_BIBLE` (already present in `game_action`); `world_repo` (already a `create_router` param + in scope in `get_status`).
- Produces: a pipeline where `/player/status` and `/game/action` derive 所务 from the persisted tension state, end-to-end, behavior-compatible.

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_world_state_scaffold.py`, inside the existing `TestPipelineWorldTick` class (after `test_behavior_unchanged_status_still_works`):

```python
    @pytest.mark.asyncio
    async def test_action_surfaces_tension_driven_goal(self, tmp_path):
        """End-to-end: a fresh cultivate action surfaces venture_bamboo as the
        current 所务 (always-active tension) in both the action response and
        /player/status, proving the pipeline threads world_state + bible into
        the tension-derived 所务 methods."""
        mock = MockLLMClient(response=json.dumps({
            "story": "你静心修炼片刻。", "intent": "cultivate",
            "action_valid": True, "invalid_reason": "", "state_delta": {},
            "breakthrough": None, "combat": None, "npc_update": None,
        }, ensure_ascii=False))
        app = _make_app(mock, tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/game/action", json={"user_input": "修炼"})
            assert r.status_code == 200
            body = json.loads(r.text)
            assert body["goal"]["id"] == "venture_bamboo"
            assert body["quests"][0]["id"] == "venture_bamboo"
            assert body["quests"][0]["status"] == "active"
            # /player/status reads the persisted world_state and agrees
            s = await client.get("/player/status")
            assert s.status_code == 200
            assert s.json()["goal"]["id"] == "venture_bamboo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world_state_scaffold.py::TestPipelineWorldTick::test_action_surfaces_tension_driven_goal -v`
Expected: FAIL — `TypeError: current_goal() takes 2 positional arguments but 3 were given` (routes still calls `world_engine.current_goal(player)`).

- [ ] **Step 3: Thread `world_state` + `bible` into the `get_status` call sites**

In `api/routes.py`, in the `get_status` handler, insert two lines immediately before the existing `goal = world_engine.current_goal(player)` (line 104) — right after the `npcs = [...]` block closes (after line 102):

```python
        world_state = world_repo.get("default") or WorldState()
        bible = PHASE_0_BIBLE
```

Then update the three 所务 call sites in `get_status` (the `goal`, `next_quest`, and `quests` lines). Replace:

```python
        goal = world_engine.current_goal(player)
        goal_info = {"id": goal.id, "label": goal.label} if goal else {
            "id": None, "label": "暂无要务，随心而行",
        }

        next_quest = world_engine.next_quest(player)
        next_quest_info = {"label": next_quest.label} if next_quest else None
```

with:

```python
        goal = world_engine.current_goal(player, world_state, bible)
        goal_info = {"id": goal.id, "label": goal.label} if goal else {
            "id": None, "label": "暂无要务，随心而行",
        }

        next_quest = world_engine.next_quest(player, world_state, bible)
        next_quest_info = {"label": next_quest.label} if next_quest else None
```

and replace:

```python
            "quests": world_engine.visible_quests(player),
            "next_quest": next_quest_info,
```

with:

```python
            "quests": world_engine.visible_quests(player, world_state, bible),
            "next_quest": next_quest_info,
```

- [ ] **Step 4: Thread `world_state` + `bible` into the `game_action` call sites**

The M1 world-tick block in `game_action` (after `player = world_engine.advance_tick(player)`) already defines `world_state` and `bible = PHASE_0_BIBLE` as locals and saves `world_state`. `world_state` is a local in the `game_action` body; the response-streaming closure reads it without reassignment (so no `nonlocal` is needed for reads — only `player` is reassigned and needs `nonlocal`).

Update the four call sites in `game_action`:

(a) The pre-stream current objective (line ~339). Replace:

```python
        goal = world_engine.current_goal(player)
```

with:

```python
        goal = world_engine.current_goal(player, world_state, bible)
```

(b) The quest lifecycle update inside the streaming closure (line ~509). Replace:

```python
            player = world_engine.update_quests(player)
```

with:

```python
            player = world_engine.update_quests(player, world_state, bible)
```

(c) The post-stream current objective recompute (line ~531). Replace:

```python
            goal = world_engine.current_goal(player)
```

with:

```python
            goal = world_engine.current_goal(player, world_state, bible)
```

(d) The panel refresh in the response `rest` dict (lines ~570-571). Replace:

```python
                "quests": world_engine.visible_quests(player),
                "next_quest": ({"label": nq.label} if (nq := world_engine.next_quest(player)) else None),
```

with:

```python
                "quests": world_engine.visible_quests(player, world_state, bible),
                "next_quest": ({"label": nq.label} if (nq := world_engine.next_quest(player, world_state, bible)) else None),
```

- [ ] **Step 5: Run the new integration test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world_state_scaffold.py::TestPipelineWorldTick -v`
Expected: PASS — all three `TestPipelineWorldTick` tests green, including the new goal-assertion test.

- [ ] **Step 6: Run the FULL suite to confirm behavior is unchanged end-to-end**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest -v`
Expected: PASS — every test green. In particular the `test_api.py` integration assertions that check 所务 labels (e.g. `next_quest["label"] == "深入妖兽山脉，试炼身手"`) pass unchanged, because the 4 phase-0 tensions map 1:1 to the 4 `venture_*` goals. No behavior change is visible to the player.

- [ ] **Step 7: Commit**

```bash
git add api/routes.py tests/test_world_state_scaffold.py
git commit -m "feat(api): wire tension-derived 所务 into the pipeline (M2)"
```

---

## Self-Review

**1. Spec coverage (spec §15 M2: "TensionSpec/ResolutionPath、张力机、所务从张力派生；TensionSpec 加 emotion/difficulty；测：张力机、所务派生；仍无 LLM worldgen"):**
- TensionSpec/ResolutionPath real data with emotion/difficulty → Task 1 (4 hand-authored specs with `emotion` + `difficulty` + `axis` + `involved_npcs/factions`).
- 张力机 (dormant→active→resolved, path selection, world_pressure) → Task 2 (`tension_tick` real machine + `world_pressure` accumulation per §7).
- 所务从张力派生 → Task 3 (`current_goal`/`visible_quests`/`next_quest`/`update_quests` project from `world_state.tensions[*].status`, per §10).
- 测：张力机 → `TestTensionTick` (Task 2); 所务派生 → `TestCurrentGoal`/`TestQuestLog` (Task 3); end-to-end → `TestPipelineWorldTick` (Task 4).
- 仍无 LLM worldgen → Global Constraints forbid it; no LLM touched. ✓
- §7 `world_pressure` from active tensions × `pressure_weight` → Task 2 `test_world_pressure_is_sum_of_active_pressure_weights`. ✓
- §6 purity (rule-driven, no LLM, pure function) → Task 2 `test_purity_does_not_mutate_input`. ✓
- §10 phase-0 保留 4 个 venture_* 映射 → Task 1 `test_four_tensions_in_priority_order` + the 1:1 id/trigger/resolution mapping. ✓
No spec gaps for M2.

**2. Placeholder scan:** Searched for TBD/TODO/"implement later"/"add error handling" — none. Every step has complete code. No "similar to Task N" — each task's full code is shown. No undefined types: `evaluate_condition`, `GOAL_BY_ID`, `tension_tick`, the 4 method signatures, `ResolvedTension`, `TensionRuntime`, `QuestState`, `WorldState`, `WorldBible`, `PHASE_0_BIBLE` all defined in M1 models or earlier tasks.

**3. Type consistency:**
- `current_goal(self, player, world_state, bible) -> Goal | None` — same signature used in Task 3 def + Task 4 routes call sites (lines 339/531/get_status). ✓
- `visible_quests(self, player, world_state, bible) -> list[dict]` — Task 3 def + Task 4 call sites (get_status line 127, game_action line 570). ✓
- `next_quest(self, player, world_state, bible) -> Goal | None` — Task 3 def + Task 4 call sites (get_status line 109, game_action line 571). ✓
- `update_quests(self, player, world_state, bible) -> Player` — Task 3 def + Task 4 call site (line 509). ✓
- `evaluate_condition(condition, player, world_state) -> bool` — Task 1 def + Task 2 `tension_tick` usage. ✓
- `tension_tick(world_state, bible, player) -> WorldState` — Task 2 def + Task 3 `_ws` helper + M1 pipeline call. ✓
- `GOAL_BY_ID: dict[str, Goal]` — Task 1 def + Task 3 usage (`GOAL_BY_ID[spec.id]`). Import added to `engine/world.py` in Task 1. ✓
- `TensionRuntime`/`ResolvedTension` imported in `engine/world.py` (Task 1) for `tension_tick` (Task 2). ✓
- `WorldState`/`PHASE_0_BIBLE` already imported in `api/routes.py` (M1); `world_repo` already a `create_router` param (M1). ✓

**Cross-task ordering note (verified):** Task 2's full-suite run intentionally shows `test_world.py` 所务 failures (old signatures) — those are fixed in Task 3, not Task 2. Task 3's full-suite run intentionally shows `test_api.py` integration failures (routes still old signatures) — fixed in Task 4. This staged breakage is correct: each task's own tests pass at its Step 5, and the cross-task failures are exactly the ones the next task addresses. Final green at Task 4 Step 6.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-21-tension-state-machine.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**