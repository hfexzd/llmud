# World State Scaffold (M1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the emergent world's state scaffold — `WorldState` + runtime sub-models + `WorldBible` canon/behavior/content models + a hand-authored phase-0 seed — and wire a rule-driven world tick (NPC step + tension stub) into the action pipeline, persisted to SQLite, with zero behavior change.

**Architecture:** Per the spec (`docs/superpowers/specs/2026-06-21-emergent-world-design.md`), the world gains its own state (`WorldState`: tick, phase, pressure, tensions, npc_state, faction_state, resolved history, sealed/ending) tracked alongside the player. `PHASE_0_BIBLE` is hand-authored from existing data (no LLM — LLM worldgen is M5). Each action runs a rule-driven `npc_step` (NPCs move per their presence schedule) + a no-op `tension_tick` stub (real tension machine is M2). The world state is persisted but not yet fed to the DM prompt (that is M3), so existing narrative behavior is unchanged.

**Tech Stack:** Python 3.14, Pydantic v2, FastAPI, SQLite (sqlite3), pytest.

## Global Constraints

- **Engine = 骨 (deterministic, no LLM):** `npc_step` and `tension_tick` are pure functions, no I/O, no LLM calls. Unit-testable.
- **Canon constraint (existing):** the DM may only mention system-existing entities; this plan does not relax it.
- **Single hardcoded player `p1`**, single world state keyed `"default"`.
- **Behavior unchanged:** M1 only *adds* world-state tracking; it must not alter story/status/combat output. All 153 existing tests must still pass.
- **Follow existing patterns:** world data lives in `engine/models.py` (like `SCENE_MAP`/`ALL_EVENTS`/`NPC_PRESENCES`); world logic lives in `engine/world.py`; persistence in `db/repository.py` + `db/connection.py`; wiring in `api/routes.py` + `api/app.py`.
- **Reuse `Scene`** (already in `models.py`) as the scene spec — do not create a redundant `SceneSpec`.
- Tests use the `db_conn` fixture (`tests/conftest.py`, in-memory SQLite with `init_db`) and `pytest`.

---

## File Structure

- **Modify `engine/models.py`** — replace the `WorldState` stub (lines 233-235) with the full runtime model set; append canon/behavior/content models + `WorldBible` + `PHASE_0_BIBLE` at end of file.
- **Modify `engine/world.py`** — add `npc_step` (rule-driven) and `tension_tick` (M1 stub) pure functions.
- **Modify `db/repository.py`** — add `WorldRepository` (get/save via single JSON `data` column).
- **Modify `db/connection.py`** — add `world_state` table + migration.
- **Modify `api/routes.py`** — `create_router` gains `world_repo`; `game_action` runs the world tick after `advance_tick`.
- **Modify `api/app.py`** — construct `WorldRepository(conn)` and pass to `create_router`.
- **Modify `tests/test_world_models.py`** — update `TestWorldStateModel` to the new schema.
- **Create `tests/test_world_state_scaffold.py`** — new tests for models, seed, `npc_step`, persistence, wiring.

---

## Task 1: World state + canon/behavior models in `engine/models.py`

**Files:**
- Modify: `engine/models.py:233-235` (replace `WorldState` stub)
- Modify: `engine/models.py` (append canon/behavior models + `WorldBible` at end of file, after `world_canon`)
- Modify: `tests/test_world_models.py:93-97` (update `TestWorldStateModel`)

**Interfaces:**
- Produces: `WorldState`, `TensionRuntime`, `NPCRuntimeState`, `FactionRuntime`, `ResolvedTension`, `TensionTrigger`, `ResolutionPath`, `TensionSpec`, `NPCGoal`, `BehaviorTrigger`, `BehaviorAction`, `BehaviorModel`, `FactionSpec`, `ItemSpec`, `SkillSpec`, `WorldBible` — all importable from `engine.models`. Later tasks consume `WorldState`/`NPCRuntimeState` (Task 3), `WorldBible`/`BehaviorModel` (Task 2 seed), and `WorldState` persistence (Task 4).

- [ ] **Step 1: Write the failing tests**

First extend the module-level import at the top of `tests/test_world_models.py` (lines 2-6) to include the new models — the file already imports `WorldState` there, so add the rest alongside it. The import block becomes:

```python
from engine.models import (
    Scene, EventTrigger, WorldEvent, NPCPresence, SceneSchedule,
    NPCInteraction, WorldState, Player, Intent, ENCOUNTERS_BY_SCENE,
    SCENE_MAP, ALL_EVENTS, NPC_PRESENCES, NPC_INTERACTIONS,
    NPCRuntimeState, TensionRuntime, WorldBible, FactionSpec, ItemSpec,
    SkillSpec, TensionSpec, TensionTrigger, BehaviorModel,
)
```

Then append a new test class (after `TestWorldStateModel`) — no local imports, it uses the module-level names above:

```python
class TestEmergentWorldModels:
    def test_world_state_defaults(self):
        state = WorldState()
        assert state.tick == 0
        assert state.phase_id == 0
        assert state.world_pressure == 0
        assert state.tensions == {}
        assert state.npc_state == {}
        assert state.faction_state == {}
        assert state.resolved_tensions == []
        assert state.sealed is False
        assert state.ending is None

    def test_npc_runtime_state_defaults(self):
        s = NPCRuntimeState(npc_id="chenhao", scene_id="market")
        assert s.npc_id == "chenhao"
        assert s.scene_id == "market"
        assert s.mood == ""
        assert s.goal_progress == {}
        assert s.schedule_tick == 0
        assert s.last_autonomous_action is None

    def test_world_bible_holds_content_catalogs(self):
        bible = WorldBible(phase_id=0, phase_title="练气篇",
                          scenes=[Scene(id="outer_gate", name="x", description="d", atmosphere="a",
                                        connections=[], available_actions=[], encounter_ids=[], npc_ids=[])],
                          factions=[FactionSpec(id="qingyun_sect", name="青云门", type="门派")],
                          items=[ItemSpec(id="spirit_herb", name="灵草", kind="灵材")],
                          skills=[SkillSpec(id="qs", name="青云剑诀", kind="功法")],
                          tensions=[], npc_models=[BehaviorModel(npc_id="linwaner")])
        assert bible.phase_id == 0
        assert len(bible.scenes) == 1
        assert bible.factions[0].id == "qingyun_sect"
        assert bible.items[0].kind == "灵材"
        assert bible.skills[0].name == "青云剑诀"
        assert bible.npc_models[0].npc_id == "linwaner"

    def test_tension_spec_carries_axis_and_emotion(self):
        t = TensionSpec(id="beast_surge", name="妖兽潮", axis=["探索", "成长"],
                       emotion="失所有", trigger=TensionTrigger(type="stat", conditions={}))
        assert t.axis == ["探索", "成长"]
        assert t.emotion == "失所有"
        assert t.trigger.type == "stat"
        assert t.pressure_weight == 1
        assert t.difficulty == 1
```

Also update the existing `TestWorldStateModel` (lines 93-97) — replace its body so it no longer references the removed `current_tick`/`npc_locations`. `WorldState` is already module-level imported, so no local import:

```python
class TestWorldStateModel:
    def test_world_state_defaults(self):
        state = WorldState()
        assert state.tick == 0
        assert state.npc_state == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world_models.py::TestEmergentWorldModels -v`
Expected: FAIL with ImportError for `WorldBible`/`FactionSpec`/`ItemSpec`/`SkillSpec`/`TensionSpec`/`NPCRuntimeState` (not defined), and the old `TestWorldStateModel` failing on `current_tick`/`npc_locations` if not yet updated.

- [ ] **Step 3: Replace the `WorldState` stub with runtime models**

In `engine/models.py`, replace the existing block (lines 233-235):

```python
class WorldState(BaseModel):
    current_tick: int = 0
    npc_locations: dict[str, str] = {}
```

with:

```python
# --- Emergent world runtime models (M1 scaffold; see design spec §5) ---

class TensionRuntime(BaseModel):
    status: str = "dormant"            # dormant | active | resolved
    pressure: int = 0
    progress: dict[str, int] = Field(default_factory=dict)
    activated_tick: int | None = None
    resolved_tick: int | None = None
    resolved_path: str | None = None


class NPCRuntimeState(BaseModel):
    npc_id: str
    scene_id: str
    mood: str = ""
    goal_progress: dict[str, int] = Field(default_factory=dict)
    schedule_tick: int = 0
    last_autonomous_action: str | None = None


class FactionRuntime(BaseModel):
    faction_id: str
    trust: int = 0
    dominance: int = 0


class ResolvedTension(BaseModel):
    tension_id: str
    resolved_tick: int
    path_id: str
    summary: str = ""


class WorldState(BaseModel):
    tick: int = 0
    phase_id: int = 0
    world_pressure: int = 0
    tensions: dict[str, TensionRuntime] = Field(default_factory=dict)
    npc_state: dict[str, NPCRuntimeState] = Field(default_factory=dict)
    faction_state: dict[str, FactionRuntime] = Field(default_factory=dict)
    resolved_tensions: list[ResolvedTension] = Field(default_factory=list)
    sealed: bool = False
    ending: str | None = None
```

- [ ] **Step 4: Append canon/behavior/content models + `WorldBible` at end of file**

Append to the end of `engine/models.py` (after the existing `world_canon` function):

```python
# --- World canon / behavior / content models (M1 scaffold; spec §4, §4.2) ---
# Leaf models first, then WorldBible (which references them). `Scene` is the
# existing scene model (reused as the scene spec — no redundant SceneSpec).

class TensionTrigger(BaseModel):
    type: str                          # stat | tick | tension_resolved | npc_state
    conditions: dict = Field(default_factory=dict)


class ResolutionPath(BaseModel):
    id: str
    label: str
    condition: dict = Field(default_factory=dict)
    outcome_state: dict = Field(default_factory=dict)
    ending_lean: str | None = None


class TensionSpec(BaseModel):
    id: str
    name: str
    axis: list[str] = Field(default_factory=list)
    emotion: str = ""
    involved_npcs: list[str] = Field(default_factory=list)
    involved_factions: list[str] = Field(default_factory=list)
    trigger: TensionTrigger
    resolution_paths: list[ResolutionPath] = Field(default_factory=list)
    pressure_weight: int = 1
    difficulty: int = 1


class NPCGoal(BaseModel):
    id: str
    label: str
    axis: str                          # 成长 / 陪伴 / 探索
    satisfy_condition: dict = Field(default_factory=dict)
    progress_driver: dict = Field(default_factory=dict)
    tragic_potential: str | None = None


class BehaviorTrigger(BaseModel):
    type: str
    conditions: dict = Field(default_factory=dict)


class BehaviorAction(BaseModel):
    type: str                           # move | mood | goal_progress | interact_npc
    params: dict = Field(default_factory=dict)
    condition: dict = Field(default_factory=dict)


class BehaviorModel(BaseModel):
    npc_id: str
    motive: str = ""
    goals: list[NPCGoal] = Field(default_factory=list)
    triggers: list[BehaviorTrigger] = Field(default_factory=list)
    routine: list[BehaviorAction] = Field(default_factory=list)
    decision_rules: list[str] = Field(default_factory=list)


class FactionSpec(BaseModel):
    id: str
    name: str
    type: str                           # 门派 | 散修组织 | 妖兽势力 | 中立方
    stance: str = ""                    # 正 | 魔 | 中立 | 野
    relations: dict[str, str] = Field(default_factory=dict)
    tensions_involved: list[str] = Field(default_factory=list)
    lore: str = ""


class ItemSpec(BaseModel):
    id: str
    name: str
    kind: str                           # 灵材 | 丹药 | 法器 | 材料 | 暗器
    rarity: str = "凡"                   # 凡 | 灵 | 玄 | 天
    effect: str = ""
    source: list[str] = Field(default_factory=list)
    axis: str = ""
    lore: str = ""


class SkillSpec(BaseModel):
    id: str
    name: str
    kind: str                           # 功法 | 招式 | 身法 | 心法
    school: str = ""                    # references a FactionSpec.id
    requirement: str = ""
    effect: str = ""
    axis: str = ""
    lore: str = ""


class WorldBible(BaseModel):
    phase_id: int = 0
    phase_title: str = ""
    scenes: list[Scene] = Field(default_factory=list)
    factions: list[FactionSpec] = Field(default_factory=list)
    items: list[ItemSpec] = Field(default_factory=list)
    skills: list[SkillSpec] = Field(default_factory=list)
    tensions: list[TensionSpec] = Field(default_factory=list)
    npc_models: list[BehaviorModel] = Field(default_factory=list)
    ending_hints: dict = Field(default_factory=dict)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world_models.py -v`
Expected: PASS (including updated `TestWorldStateModel` and new `TestEmergentWorldModels`).

- [ ] **Step 6: Commit**

```bash
git add engine/models.py tests/test_world_models.py
git commit -m "feat(world): emergent world-state + WorldBible canon/behavior models (M1)"
```

---

## Task 2: `PHASE_0_BIBLE` seed in `engine/models.py`

**Files:**
- Modify: `engine/models.py` (append `PHASE_0_BIBLE` at end of file)
- Test: `tests/test_world_state_scaffold.py` (new file)

**Interfaces:**
- Consumes: `WorldBible`, `FactionSpec`, `ItemSpec`, `SkillSpec`, `BehaviorModel`, `NPCGoal`, `BehaviorAction` (Task 1), existing `SCENE_MAP`, `NPC_PRESENCES`, `ALL_NPC_PROFILES`.
- Produces: `PHASE_0_BIBLE: WorldBible` — the active canon for M1–M4; `npc_step` (Task 3) consumes its `npc_models`; the pipeline (Task 5) loads it as the active bible.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_world_state_scaffold.py`:

```python
from engine.models import PHASE_0_BIBLE, WorldBible


class TestPhase0Bible:
    def test_is_world_bible_phase_0(self):
        assert isinstance(PHASE_0_BIBLE, WorldBible)
        assert PHASE_0_BIBLE.phase_id == 0
        assert PHASE_0_BIBLE.phase_title == "练气篇"

    def test_reuses_existing_five_scenes(self):
        ids = {s.id for s in PHASE_0_BIBLE.scenes}
        assert ids == {"outer_gate", "inner_gate", "bamboo_forest", "market", "mountain_range"}

    def test_has_three_npc_models_matching_profiles(self):
        ids = {m.npc_id for m in PHASE_0_BIBLE.npc_models}
        assert ids == {"linwaner", "chenhao", "old_yang"}
        # each model has a schedule-follow routine (M1 minimal behavior)
        for m in PHASE_0_BIBLE.npc_models:
            assert any(a.type == "move" and a.params.get("schedule") for a in m.routine)

    def test_has_seed_factions_items_skills(self):
        assert any(f.id == "qingyun_sect" for f in PHASE_0_BIBLE.factions)
        assert any(i.name == "灵草" for i in PHASE_0_BIBLE.items)
        assert any(s.name == "青云剑诀" for s in PHASE_0_BIBLE.skills)

    def test_tensions_empty_in_m1(self):
        # Real tension data + machine arrive in M2.
        assert PHASE_0_BIBLE.tensions == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world_state_scaffold.py -v`
Expected: FAIL with ImportError: cannot import `PHASE_0_BIBLE`.

- [ ] **Step 3: Append `PHASE_0_BIBLE` to `engine/models.py`**

Append at the very end of `engine/models.py`:

```python
# --- Phase-0 WorldBible seed (hand-authored, no LLM; LLM worldgen is M5) ---
# Translates the existing hand-authored SCENE_MAP + NPC profiles into a
# WorldBible, plus a small starter set of factions/items/skills so the canon
# (DM prompt + validator) has concrete entities to reference from turn 1.
# Tensions are empty in M1; M2 adds real tension data + the tension machine.
PHASE_0_BIBLE = WorldBible(
    phase_id=0,
    phase_title="练气篇",
    scenes=list(SCENE_MAP.values()),
    factions=[
        FactionSpec(id="qingyun_sect", name="青云门", type="门派", stance="正",
                    relations={"sanxiu_league": "疏"}, lore="主角所在宗门，门规森严。"),
        FactionSpec(id="sanxiu_league", name="散修盟", type="散修组织", stance="中立",
                    relations={"qingyun_sect": "疏"}, lore="松散的散修互助组织，消息灵通。"),
    ],
    items=[
        ItemSpec(id="spirit_herb", name="灵草", kind="灵材", rarity="凡",
                 effect="服用可缓缓增益灵力", source=["幽竹林"], axis="成长",
                 lore="竹林深处偶现的泛光灵草。"),
        ItemSpec(id="ninglu_grass", name="凝露草", kind="灵材", rarity="凡",
                 effect="服用可小幅恢复气血", source=["幽竹林", "outer_gate"], axis="成长",
                 lore="叶尖凝露，清心养气。"),
        ItemSpec(id="qi_pill", name="聚气丹", kind="丹药", rarity="凡",
                 effect="服用可增益灵力", source=["修士集市"], axis="成长",
                 lore="集市常见的入门丹药。"),
    ],
    skills=[
        SkillSpec(id="qingyun_sword_art", name="青云剑诀", kind="功法",
                  school="qingyun_sect", requirement="练气期一层",
                  effect="提升攻击", axis="成长", lore="青云门入门剑法，中正平和。"),
        SkillSpec(id="fentian_palm", name="焚天掌", kind="招式", school="",
                  requirement="灵根·火", effect="火属性攻击招式", axis="成长",
                  lore="以火灵根催动的烈掌。"),
    ],
    tensions=[],
    npc_models=[
        BehaviorModel(
            npc_id="linwaner",
            motive="希望找到一个可信赖之人，又怕身世暴露。",
            goals=[NPCGoal(id="seek_confidant", label="寻一可托付之人", axis="陪伴",
                           tragic_potential="身世暴露或被弃")],
            routine=[BehaviorAction(type="move", params={"schedule": True}, condition={})],
        ),
        BehaviorModel(
            npc_id="chenhao",
            motive="想变强护人，又受禁术诱惑。",
            goals=[NPCGoal(id="grow_strong", label="变强护人", axis="成长",
                           tragic_potential="禁术败露被逐出宗门")],
            routine=[BehaviorAction(type="move", params={"schedule": True}, condition={})],
        ),
        BehaviorModel(
            npc_id="old_yang",
            motive="守护外门，偶尔点拨有缘人。",
            goals=[NPCGoal(id="guard_gate", label="守护外门", axis="探索",
                           tragic_potential=None)],
            routine=[BehaviorAction(type="move", params={"schedule": True}, condition={})],
        ),
    ],
    ending_hints={},
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world_state_scaffold.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/models.py tests/test_world_state_scaffold.py
git commit -m "feat(world): hand-authored PHASE_0_BIBLE seed (M1)"
```

---

## Task 3: `npc_step` + `tension_tick` stub in `engine/world.py`

**Files:**
- Modify: `engine/world.py` (add two functions; add imports)
- Test: `tests/test_world_state_scaffold.py` (append)

**Interfaces:**
- Consumes: `WorldState`, `NPCRuntimeState`, `WorldBible`, `BehaviorModel` (Tasks 1-2), existing `NPC_PRESENCES`.
- Produces: **module-level** pure functions `npc_step(world_state: WorldState, bible: WorldBible, tick: int) -> WorldState` and `tension_tick(world_state: WorldState, bible: WorldBible, player: Player) -> WorldState` (per spec §6 — pure functions, unit-testable, not `WorldEngine` methods). The pipeline (Task 5) imports and calls them directly each action.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_world_state_scaffold.py`:

```python
from engine.models import WorldState, PHASE_0_BIBLE, Player
from engine.world import npc_step, tension_tick


class TestNpcStep:
    def test_npc_at_default_scene_when_no_schedule_matches(self):
        ws = WorldState()
        out = npc_step(ws, PHASE_0_BIBLE, tick=0)
        # linwaner default inner_gate, schedule market only at tick 10-20
        assert out.npc_state["linwaner"].scene_id == "inner_gate"
        assert out.npc_state["chenhao"].scene_id == "market"
        assert out.npc_state["old_yang"].scene_id == "outer_gate"
        # schedule_tick records the tick the step ran at
        assert out.npc_state["chenhao"].schedule_tick == 0

    def test_linwaner_moves_to_market_on_schedule(self):
        ws = WorldState()
        out = npc_step(ws, PHASE_0_BIBLE, tick=15)
        assert out.npc_state["linwaner"].scene_id == "market"

    def test_pure_function_does_not_mutate_input(self):
        ws = WorldState()
        npc_step(ws, PHASE_0_BIBLE, tick=15)
        assert ws.npc_state == {}  # input untouched

    def test_preserves_existing_goal_progress_and_mood(self):
        from engine.models import NPCRuntimeState
        ws = WorldState(npc_state={
            "chenhao": NPCRuntimeState(npc_id="chenhao", scene_id="market",
                                       mood="eager", goal_progress={"grow_strong": 30}),
        })
        out = npc_step(ws, PHASE_0_BIBLE, tick=5)
        assert out.npc_state["chenhao"].mood == "eager"
        assert out.npc_state["chenhao"].goal_progress == {"grow_strong": 30}
        assert out.npc_state["chenhao"].scene_id == "market"


class TestTensionTickStub:
    def test_stub_is_noop(self):
        ws = WorldState(world_pressure=3)
        out = tension_tick(ws, PHASE_0_BIBLE, Player())
        # M1 stub: no-op, state unchanged
        assert out is not ws
        assert out.world_pressure == 3
        assert out.tensions == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world_state_scaffold.py::TestNpcStep tests/test_world_state_scaffold.py::TestTensionTickStub -v`
Expected: FAIL with ImportError: cannot import `npc_step` / `tension_tick`.

- [ ] **Step 3: Add imports to `engine/world.py`**

In `engine/world.py`, extend the existing `from engine.models import (...)` block to add `WorldState`, `WorldBible`, `NPCRuntimeState`. The current import block (lines 7-21) becomes:

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
    QuestState,
    resolve_scene_id,
    WorldState,
    WorldBible,
    NPCRuntimeState,
)
```

- [ ] **Step 4: Append `npc_step` + `tension_tick` as module-level functions to `engine/world.py`**

Append at the very end of `engine/world.py`, **after the `WorldEngine` class ends** (i.e. after `resolve_scene_move`, dedented to module scope — these are free functions, not methods, per spec §6):

```python
# ----------------------------------------------------------------------
# Emergent world tick (M1 scaffold) — module-level pure functions, no LLM.
# ----------------------------------------------------------------------

def npc_step(world_state: WorldState, bible: WorldBible, tick: int) -> WorldState:
    """Rule-driven NPC step: set each NPC's scene_id from its presence
    schedule at the given tick. No LLM. Pure function — returns a new
    WorldState, leaves the input untouched.

    M1 behavior is minimal: NPCs follow their NPC_PRESENCES schedule (the
    same logic as WorldEngine.get_npcs_in_scene). Richer routine actions
    (mood shifts, goal_progress bumps, interact_npc) arrive in later
    milestones.
    """
    new_npc_state = dict(world_state.npc_state)
    for npc_model in bible.npc_models:
        presence = NPC_PRESENCES.get(npc_model.npc_id)
        scene = presence.default_scene if presence else "outer_gate"
        if presence:
            for schedule in presence.schedule:
                lo, hi = schedule.tick_range
                if lo <= tick <= hi:
                    scene = schedule.scene_id
                    break
        prev = new_npc_state.get(npc_model.npc_id)
        new_npc_state[npc_model.npc_id] = NPCRuntimeState(
            npc_id=npc_model.npc_id,
            scene_id=scene,
            mood=prev.mood if prev else "",
            goal_progress=dict(prev.goal_progress) if prev else {},
            schedule_tick=tick,
            last_autonomous_action=prev.last_autonomous_action if prev else None,
        )
    return world_state.model_copy(update={"npc_state": new_npc_state})


def tension_tick(world_state: WorldState, bible: WorldBible, player: Player) -> WorldState:
    """Tension state machine stub (M1): no-op. Returns a copy so callers
    can chain model_copy updates uniformly. M2 implements trigger /
    progress / resolve; M7 adds world_pressure accumulation."""
    return world_state.model_copy()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world_state_scaffold.py -v`
Expected: PASS (all Task 2 + Task 3 tests).

- [ ] **Step 6: Commit**

```bash
git add engine/world.py tests/test_world_state_scaffold.py
git commit -m "feat(world): rule-driven npc_step + tension_tick stub (M1)"
```

---

## Task 4: `WorldRepository` + `world_state` table

**Files:**
- Modify: `db/repository.py` (add `WorldRepository`, import `WorldState`)
- Modify: `db/connection.py` (add `world_state` table + migration)
- Test: `tests/test_world_state_scaffold.py` (append)

**Interfaces:**
- Consumes: `WorldState` (Task 1).
- Produces: `WorldRepository(conn)` with `.get(world_id="default") -> WorldState | None` and `.save(state, world_id="default") -> None`. The pipeline (Task 5) and `app.py` construct it from the shared connection.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_world_state_scaffold.py`:

```python
from engine.models import NPCRuntimeState, TensionRuntime
from db.repository import WorldRepository


class TestWorldRepository:
    def test_get_returns_none_when_absent(self, db_conn):
        repo = WorldRepository(db_conn)
        assert repo.get() is None

    def test_save_then_get_round_trip(self, db_conn):
        repo = WorldRepository(db_conn)
        ws = WorldState(
            tick=42, phase_id=0, world_pressure=7,
            npc_state={"chenhao": NPCRuntimeState(npc_id="chenhao", scene_id="market",
                                                  mood="eager", goal_progress={"g": 5})},
            tensions={"t1": TensionRuntime(status="active", pressure=2,
                                           progress={"rally": 10})},
        )
        repo.save(ws)
        got = repo.get()
        assert got is not None
        assert got.tick == 42
        assert got.world_pressure == 7
        assert got.npc_state["chenhao"].scene_id == "market"
        assert got.npc_state["chenhao"].goal_progress == {"g": 5}
        assert got.tensions["t1"].status == "active"
        assert got.tensions["t1"].progress == {"rally": 10}

    def test_save_overwrites_existing(self, db_conn):
        repo = WorldRepository(db_conn)
        repo.save(WorldState(tick=1))
        repo.save(WorldState(tick=2, world_pressure=5))
        got = repo.get()
        assert got.tick == 2
        assert got.world_pressure == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world_state_scaffold.py::TestWorldRepository -v`
Expected: FAIL with ImportError: cannot import `WorldRepository`.

- [ ] **Step 3: Add the `world_state` table + migration in `db/connection.py`**

In `db/connection.py` `init_db`, add a new `CREATE TABLE` inside the function (after the `npc_memories` table block, before `conn.commit()`):

```python
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS world_state (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
```

- [ ] **Step 4: Add `WorldRepository` to `db/repository.py`**

At the top of `db/repository.py`, change the import (line 4) to include `WorldState`:

```python
from engine.models import Player, WorldState
```

Append at the end of `db/repository.py`:

```python
class WorldRepository:
    """Persists the single WorldState (keyed 'default') as one JSON blob.

    Single-column `data` keeps the schema flexible as WorldState grows across
    milestones — no per-field migrations needed for world-state evolution.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, world_id: str = "default") -> WorldState | None:
        row = self.conn.execute(
            "SELECT data FROM world_state WHERE id = ?", (world_id,)
        ).fetchone()
        if row is None:
            return None
        return WorldState.model_validate_json(row["data"])

    def save(self, state: WorldState, world_id: str = "default") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO world_state (id, data) VALUES (?, ?)",
            (world_id, state.model_dump_json()),
        )
        self.conn.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world_state_scaffold.py -v`
Expected: PASS (all tests so far).

- [ ] **Step 6: Commit**

```bash
git add db/repository.py db/connection.py tests/test_world_state_scaffold.py
git commit -m "feat(db): WorldRepository + world_state table (M1)"
```

---

## Task 5: Wire the world tick into the action pipeline

**Files:**
- Modify: `api/routes.py` (imports; `create_router` signature; `game_action` world-tick block)
- Modify: `api/app.py` (construct `WorldRepository`, pass to `create_router`)
- Test: `tests/test_world_state_scaffold.py` (append integration test)

**Interfaces:**
- Consumes: `WorldRepository` (Task 4), `WorldState`/`PHASE_0_BIBLE` (Tasks 1-2), `npc_step`/`tension_tick` (Task 3).
- Produces: each `/game/action` persists an updated `WorldState` with `npc_state` reflecting the current tick; existing story/status/combat behavior unchanged.

- [ ] **Step 1: Write the failing integration test**

First add these imports to the top of `tests/test_world_state_scaffold.py` (merging with the imports Tasks 2-4 already added there):

```python
import json
import pytest
from httpx import AsyncClient, ASGITransport
from api.app import create_app
from dm.client import MockLLMClient
```

Then append the integration test class. This mirrors the existing `tests/test_api.py` async pattern (`httpx.AsyncClient` + `ASGITransport` + `@pytest.mark.asyncio`) — the suite does not use `pytest.TestClient`:

```python
def _make_app(mock, tmp_path):
    """Create an app with a temp database (mirrors test_api.py's helper)."""
    return create_app(llm_client=mock, db_path=str(tmp_path / "t.db"))


class TestPipelineWorldTick:
    @pytest.mark.asyncio
    async def test_action_persists_world_state_with_npc_positions(self, tmp_path):
        # A MockLLMClient returning a minimal valid DM JSON so the streaming
        # pipeline completes without a real LLM call.
        mock = MockLLMClient(response=json.dumps({
            "story": "你静心修炼片刻。", "intent": "cultivate",
            "action_valid": True, "invalid_reason": "", "state_delta": {},
            "breakthrough": None, "combat": None, "npc_update": None,
        }, ensure_ascii=False))
        app = _make_app(mock, tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Advance the world a few ticks (each action advances tick by 1).
            for _ in range(3):
                r = await client.post("/game/action", json={"user_input": "修炼"})
                assert r.status_code == 200
                body = json.loads(r.text)  # body is a single streamed JSON object
                assert "story" in body

        # The world state should now be persisted with NPC positions at tick 3.
        ws = WorldRepository(app.state.db_conn).get()
        assert ws is not None
        assert ws.tick == 3
        assert ws.npc_state["chenhao"].scene_id == "market"
        assert ws.npc_state["old_yang"].scene_id == "outer_gate"
        assert ws.npc_state["linwaner"].scene_id == "inner_gate"  # tick 3 < 10
        assert ws.sealed is False
        assert ws.ending is None

    @pytest.mark.asyncio
    async def test_behavior_unchanged_status_still_works(self, tmp_path):
        mock = MockLLMClient(response=json.dumps({
            "story": "你打坐片刻。", "intent": "cultivate",
            "action_valid": True, "invalid_reason": "",
            "state_delta": {"spirit_power": 1},
            "breakthrough": None, "combat": None, "npc_update": None,
        }, ensure_ascii=False))
        app = _make_app(mock, tmp_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/game/action", json={"user_input": "修炼"})
            assert r.status_code == 200
            # status endpoint still returns the player scene (existing behavior)
            s = await client.get("/player/status")
            assert s.status_code == 200
            assert s.json()["current_scene"] == "outer_gate"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world_state_scaffold.py::TestPipelineWorldTick -v`
Expected: FAIL — `WorldRepository` not passed into the router / `app.state.db_conn` may exist but world state never saved (the world-tick block doesn't exist yet).

- [ ] **Step 3: Update `api/routes.py` imports + `create_router` signature**

In `api/routes.py`, update the `engine.models` import (line 12) to add `WorldState`, `PHASE_0_BIBLE`:

```python
from engine.models import Intent, Player, Encounter, DEFAULT_ENCOUNTER, NPCInteraction, EventTrigger, WorldEvent, SCENE_MAP, next_spirit_threshold, DMResponse, WorldState, PHASE_0_BIBLE
```

Update the `engine.world` import (line 14) to add the two module-level functions from Task 3:

```python
from engine.world import WorldEngine, npc_step, tension_tick
```

Add a `WorldRepository` import alongside the existing repository imports (line 15):

```python
from db.repository import PlayerRepository, NPCRepository, WorldRepository
```

Update `create_router` signature (line 56) to accept `world_repo`:

```python
def create_router(
    llm_client: LLMClient,
    player_repo: PlayerRepository,
    npc_repo: NPCRepository,
    encounter: Encounter,
    world_engine: WorldEngine,
    world_repo: WorldRepository,
) -> APIRouter:
```

- [ ] **Step 4: Add the world-tick block in `game_action`**

In `api/routes.py` `game_action`, immediately after the line `player = world_engine.advance_tick(player)` (the existing Step 4 world-tick start, ~line 268), insert:

```python
        # World layer scaffold (M1): track emergent world state alongside the
        # player. Rule-driven npc_step (NPCs follow their schedule) + a no-op
        # tension_tick stub. Behavior is unchanged — world state is NOT yet fed
        # to the DM prompt (that arrives in M3 with the outcome resolver).
        world_state = world_repo.get("default") or WorldState()
        bible = PHASE_0_BIBLE  # M5 swaps in LLM-regenerated bibles; M1 is always phase-0
        world_state = npc_step(world_state, bible, player.tick)
        world_state = tension_tick(world_state, bible, player)
        world_state = world_state.model_copy(update={"tick": player.tick})
        world_repo.save(world_state)
```

- [ ] **Step 5: Update `api/app.py` to construct and pass `world_repo`**

In `api/app.py`, add `WorldRepository` to the existing `from db.repository import ...` line (line 10):

```python
from db.repository import PlayerRepository, NPCRepository, WorldRepository
```

After `npc_repo = NPCRepository(conn)` (~line 42), add:

```python
    world_repo = WorldRepository(conn)
```

Update the `create_router(...)` call (~line 64) to pass it:

```python
    router = create_router(
        llm_client=llm,
        player_repo=player_repo,
        npc_repo=npc_repo,
        encounter=DEFAULT_ENCOUNTER,
        world_engine=world_engine,
        world_repo=world_repo,
    )
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_world_state_scaffold.py::TestPipelineWorldTick -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite to confirm behavior unchanged**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest -q`
Expected: All tests PASS (the pre-existing 153 plus the new M1 tests). No existing test should fail — M1 only adds parallel world-state tracking.

- [ ] **Step 8: Commit**

```bash
git add api/routes.py api/app.py tests/test_world_state_scaffold.py
git commit -m "feat(api): wire rule-driven world tick into action pipeline (M1)"
```

---

## Self-Review (completed)

**Spec coverage (M1 scope = spec §15 M1):**
- WorldState/TensionRuntime/NPCRuntimeState/FactionRuntime/ResolvedTension models → Task 1 ✓ (spec §5)
- WorldBible + content/behavior models (scenes/factions/items/skills/tensions/npc_models) → Task 1 ✓ (spec §4, §4.2)
- Phase-0 hand-authored seed (no LLM) → Task 2 ✓ (spec §4, D7)
- Rule-driven npc_step (no LLM) → Task 3 ✓ (spec §6)
- Tension machine stub (no-op) → Task 3 ✓ (spec §15 M1 "张力机桩")
- SQLite persistence of WorldState → Task 4 ✓ (spec §5 "持久化进 SQLite")
- World tick wired into pipeline after advance_tick → Task 5 ✓ (spec §3 ③)
- Behavior unchanged → Task 5 Step 7 full-suite gate ✓ (spec §15 M1 "行为不变")
- Items/skills/factions seed in canon → Task 2 ✓ (spec §4.2, D9)
Out of M1 scope (later milestones): tension machine logic (M2), validator + world_delta (M3), endings (M4), LLM worldgen + milestone regen (M5), offline growth (M6), flow/emotion tuning (M7).

**Placeholder scan:** none — all steps contain concrete code and exact commands.

**Type consistency:** `npc_step(world_state, bible, tick) -> WorldState`, `tension_tick(world_state, bible, player) -> WorldState` defined in Task 3 and called with matching args in Task 5. `WorldRepository.get(world_id="default")` / `.save(state, world_id="default")` defined in Task 4 and used in Task 5. `WorldState`/`NPCRuntimeState`/`PHASE_0_BIBLE` field names match across Tasks 1-5.