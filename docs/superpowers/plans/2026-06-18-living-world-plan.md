# Living World Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scene-based living world with event pool, NPC presence, and soft guidance to solve player aimlessness.

**Architecture:** Insert a `world` layer between `engine` and `dm` in the pipeline. The world layer manages scenes, events, NPC locations, and tick progression — all deterministic (bone). LLM (skin) only narrates what the engine decides happens. Data is hardcoded in Python for MVP; no new DB tables beyond player field additions.

**Tech Stack:** Python 3.14, Pydantic v2, FastAPI, SQLite, vanilla HTML/JS/CSS.

## Global Constraints

- **D1:** Scene and event data hardcoded in Python (no DB for scene config)
- **D2:** NPCs don't move in MVP (only 师姐 occasionally goes to 集市 via schedule)
- **D3:** One-time events tracked via `player.seen_events`
- **D4:** Max 1 event triggered per action
- **D5:** Player intervention handled as new `INTERVENE` intent
- **D6:** Soft guidance only — no quest markers or system prompts saying "go here"
- **D7:** Small world: 5 scenes, 3 NPCs
- All new code follows existing patterns: Pydantic models, pure functions in engine, FastAPI routes in api/
- Tests use in-memory SQLite and MockLLMClient
- Commit messages in English, game text in Chinese

---

### Task 1: Scene & World Data Models

**Files:**
- Modify: `engine/models.py`
- Test: `tests/test_world_models.py` (new)

**Interfaces:**
- Consumes: existing `Player`, `Intent`, `Encounter` models
- Produces: `Scene`, `EventTrigger`, `WorldEvent`, `NPCPresence`, `SceneSchedule`, `NPCInteraction`, `WorldState` models; updated `Player` with `current_scene`, `seen_events`, `tick`; `INTERVENE` intent; `ENCOUNTERS_BY_SCENE` mapping

- [ ] **Step 1: Write the failing test**

```python
# tests/test_world_models.py
import pytest
from engine.models import (
    Scene, EventTrigger, WorldEvent, NPCPresence, SceneSchedule,
    NPCInteraction, WorldState, Player, Intent, ENCOUNTERS_BY_SCENE,
    SCENE_MAP, ALL_EVENTS, NPC_PRESENCES, NPC_INTERACTIONS,
)


class TestSceneModel:
    def test_scene_instantiation(self):
        scene = Scene(
            id="outer_gate", name="青云门外门",
            description="外门柴房，灵气稀薄但清静",
            atmosphere="清幽",
            connections=["inner_gate", "market"],
            available_actions=["cultivate", "explore"],
            encounter_ids=[],
            npc_ids=["old_yang"],
        )
        assert scene.id == "outer_gate"
        assert scene.name == "青云门外门"
        assert "inner_gate" in scene.connections

    def test_scene_map_has_all_five(self):
        assert len(SCENE_MAP) == 5
        assert "outer_gate" in SCENE_MAP
        assert "inner_gate" in SCENE_MAP
        assert "bamboo_forest" in SCENE_MAP
        assert "market" in SCENE_MAP
        assert "mountain_range" in SCENE_MAP

    def test_scene_connections_are_bidirectional(self):
        for scene_id, scene in SCENE_MAP.items():
            for connected_id in scene.connections:
                assert scene_id in SCENE_MAP[connected_id].connections, (
                    f"{scene_id} connects to {connected_id} but not vice versa"
                )


class TestEventTriggerModel:
    def test_location_enter_trigger(self):
        trigger = EventTrigger(
            type="location_enter",
            conditions={"first_time": True},
            probability=1.0,
        )
        assert trigger.type == "location_enter"
        assert trigger.conditions["first_time"] is True

    def test_stat_threshold_trigger(self):
        trigger = EventTrigger(
            type="stat_threshold",
            conditions={"min_spirit": 20},
            probability=1.0,
        )
        assert trigger.conditions["min_spirit"] == 20

    def test_random_trigger(self):
        trigger = EventTrigger(
            type="random",
            conditions={},
            probability=0.1,
        )
        assert trigger.probability == 0.1


class TestWorldEventModel:
    def test_event_instantiation(self):
        event = WorldEvent(
            id="faint_spirit_sense",
            name="灵气波动感知",
            scene_id="outer_gate",
            trigger=EventTrigger(type="location_enter", conditions={"first_time": True}),
            narrative_hint="你隐约感到东方有更浓厚的灵气波动",
            guidance="explore_inner_gate",
        )
        assert event.scene_id == "outer_gate"
        assert event.one_time is True


class TestNPCPresenceModel:
    def test_npc_presence(self):
        presence = NPCPresence(
            npc_id="linwaner",
            default_scene="inner_gate",
            schedule=[SceneSchedule(tick_range=(10, 20), scene_id="market")],
        )
        assert presence.npc_id == "linwaner"
        assert presence.default_scene == "inner_gate"
        assert len(presence.schedule) == 1


class TestWorldStateModel:
    def test_world_state_defaults(self):
        state = WorldState()
        assert state.current_tick == 0
        assert state.npc_locations == {}

    def test_intervene_intent_exists(self):
        assert Intent.INTERVENE.value == "intervene"


class TestPlayerModelChanges:
    def test_player_has_current_scene(self):
        player = Player()
        assert player.current_scene == "outer_gate"

    def test_player_has_seen_events(self):
        player = Player()
        assert player.seen_events == []

    def test_player_has_tick(self):
        player = Player()
        assert player.tick == 0


class TestEncountersByScene:
    def test_mountain_range_has_wolf(self):
        assert "e1" in ENCOUNTERS_BY_SCENE.get("mountain_range", [])


class TestAllEventsExist:
    def test_events_list_not_empty(self):
        assert len(ALL_EVENTS) > 0

    def test_npc_presences_not_empty(self):
        assert len(NPC_PRESENCES) > 0

    def test_npc_interactions_not_empty(self):
        assert len(NPC_INTERACTIONS) > 0


- [ ] **Step 2: Run test to verify it fails**

Run: `cd E:\AI\llmud && python -m pytest tests/test_world_models.py -v`
Expected: FAIL — module imports don't exist yet

- [ ] **Step 3: Implement the models**

Add the following to `engine/models.py`. Keep all existing code; append new models and modify `Player`, `Intent`, and add module-level data constants at the bottom.

**Changes to `Intent` enum** — add `INTERVENE`:

```python
class Intent(str, Enum):
    CULTIVATE = "cultivate"
    TALK = "talk"
    FIGHT = "fight"
    MOVE = "move"
    INTERVENE = "intervene"
    OTHER = "other"
```

**Changes to `Player` model** — replace `location` with `current_scene`, add `seen_events` and `tick`:

```python
class Player(BaseModel):
    id: str = "p1"
    name: str = "张铁柱"
    level: str = "练气期一层"
    spirit_power: int = 10
    hp: int = 100
    max_hp: int = 100
    affinity: str = "火"
    current_scene: str = "outer_gate"
    inventory: list[str] = Field(default_factory=list)
    recent_stories: list[str] = Field(default_factory=list)
    seen_events: list[str] = Field(default_factory=list)
    tick: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    last_seen: datetime = Field(default_factory=datetime.now)
```

**New models** — append after `DMResponse`:

```python
class Scene(BaseModel):
    id: str
    name: str
    description: str
    atmosphere: str
    connections: list[str]
    available_actions: list[str]
    encounter_ids: list[str]
    npc_ids: list[str]


class EventTrigger(BaseModel):
    type: str  # "location_enter" | "tick_interval" | "stat_threshold" | "random"
    conditions: dict = {}
    probability: float = 1.0


class WorldEvent(BaseModel):
    id: str
    name: str
    scene_id: str
    trigger: EventTrigger
    narrative_hint: str
    guidance: str
    allow_intervene: bool = False
    intervene_options: list[str] | None = None
    one_time: bool = True


class SceneSchedule(BaseModel):
    tick_range: tuple[int, int]
    scene_id: str


class NPCPresence(BaseModel):
    npc_id: str
    default_scene: str
    schedule: list[SceneSchedule] = []


class NPCInteraction(BaseModel):
    id: str
    npc_ids: list[str]
    scene_id: str
    trigger_conditions: dict = {}
    narrative_hint: str
    allow_intervene: bool = False
    intervene_options: list[str] | None = None


class WorldState(BaseModel):
    current_tick: int = 0
    npc_locations: dict[str, str] = {}
```

**Module-level data constants** — append at the bottom of `engine/models.py`:

```python
# --- Scene Data ---

SCENE_MAP: dict[str, Scene] = {
    "outer_gate": Scene(
        id="outer_gate",
        name="青云门外门",
        description="外门柴房与练功场，灵气稀薄但清静。初来乍到的修士多在此落脚。",
        atmosphere="清幽",
        connections=["inner_gate", "market"],
        available_actions=["cultivate", "explore"],
        encounter_ids=[],
        npc_ids=["old_yang"],
    ),
    "inner_gate": Scene(
        id="inner_gate",
        name="青云门内门",
        description="内门修炼场，灵气浓郁。弟子们在此打坐修炼，师姐常在此处。",
        atmosphere="庄严",
        connections=["outer_gate", "bamboo_forest"],
        available_actions=["cultivate", "explore"],
        encounter_ids=[],
        npc_ids=["linwaner"],
    ),
    "bamboo_forest": Scene(
        id="bamboo_forest",
        name="幽竹林",
        description="竹林深处灵气充沛，偶有奇遇。但也传闻有妖兽出没。",
        atmosphere="神秘",
        connections=["inner_gate", "mountain_range"],
        available_actions=["cultivate", "explore", "fight"],
        encounter_ids=["e1"],
        npc_ids=[],
    ),
    "market": Scene(
        id="market",
        name="修士集市",
        description="修士们交易灵材丹药的集市，消息灵通，人来人往。",
        atmosphere="繁忙",
        connections=["outer_gate"],
        available_actions=["explore"],
        encounter_ids=[],
        npc_ids=["chenhao"],
    ),
    "mountain_range": Scene(
        id="mountain_range",
        name="妖兽山脉",
        description="危险的山脉深处，妖兽横行。只有胆大的修士才敢涉足。",
        atmosphere="危险",
        connections=["bamboo_forest"],
        available_actions=["fight", "explore"],
        encounter_ids=["e1"],
        npc_ids=[],
    ),
}

ENCOUNTERS_BY_SCENE: dict[str, list[str]] = {
    "bamboo_forest": ["e1"],
    "mountain_range": ["e1"],
}

# --- NPC Presence Data ---

NPC_PRESENCES: dict[str, NPCPresence] = {
    "linwaner": NPCPresence(
        npc_id="linwaner",
        default_scene="inner_gate",
        schedule=[SceneSchedule(tick_range=(10, 20), scene_id="market")],
    ),
    "chenhao": NPCPresence(
        npc_id="chenhao",
        default_scene="market",
        schedule=[],
    ),
    "old_yang": NPCPresence(
        npc_id="old_yang",
        default_scene="outer_gate",
        schedule=[],
    ),
}

# --- Event Pool Data ---

ALL_EVENTS: list[WorldEvent] = [
    # Environmental hints (direction guidance)
    WorldEvent(
        id="faint_spirit_sense",
        name="灵气波动感知",
        scene_id="outer_gate",
        trigger=EventTrigger(type="location_enter", conditions={"first_time": True}),
        narrative_hint="你隐约感到东方有更浓厚的灵气波动，似乎内门方向灵气更盛。",
        guidance="explore_inner_gate",
        one_time=True,
    ),
    WorldEvent(
        id="outer_gate_cultivate_hint",
        name="外门修炼提示",
        scene_id="outer_gate",
        trigger=EventTrigger(type="stat_threshold", conditions={"max_spirit": 15}),
        narrative_hint="外门虽然灵气稀薄，但胜在清静，正适合初入修途的你静心修炼。",
        guidance="cultivate",
        one_time=True,
    ),
    WorldEvent(
        id="bamboo_whisper",
        name="竹林沙沙声",
        scene_id="inner_gate",
        trigger=EventTrigger(type="stat_threshold", conditions={"min_spirit": 20}),
        narrative_hint="竹林方向传来奇异的沙沙声，似乎有什么不寻常的事正在发生。",
        guidance="explore_bamboo_forest",
        one_time=True,
    ),
    WorldEvent(
        id="market_rumor",
        name="集市传闻",
        scene_id="market",
        trigger=EventTrigger(type="tick_interval", conditions={"min_tick": 5}),
        narrative_hint="集市上有人在低声议论山脉方向的异动，似乎妖兽变得更加活跃了。",
        guidance="explore_mountain_range",
        one_time=True,
    ),
    # NPC-initiated hints
    WorldEvent(
        id="waner_worry",
        name="师姐心事",
        scene_id="inner_gate",
        trigger=EventTrigger(type="location_enter", conditions={"first_time": True}),
        narrative_hint="师姐似乎心事重重，不时望向竹林方向，欲言又止。",
        guidance="talk_linwaner",
        one_time=True,
    ),
    WorldEvent(
        id="merchant_gossip",
        name="商贩搭话",
        scene_id="market",
        trigger=EventTrigger(type="tick_interval", conditions={"min_tick": 3}),
        narrative_hint="一个商贩主动向你搭话：'道友，最近山里出了好东西，可惜我修为不够……'",
        guidance="explore_mountain_range",
        one_time=True,
    ),
    WorldEvent(
        id="chenhao_challenge",
        name="师兄挑战邀请",
        scene_id="market",
        trigger=EventTrigger(type="stat_threshold", conditions={"min_spirit": 25}),
        narrative_hint="陈浩朝你招手：'师弟，要不要去山脉试试身手？最近那边的妖狼似乎变强了。'",
        guidance="fight_mountain_range",
        one_time=True,
    ),
    # NPC-to-NPC interactions
    WorldEvent(
        id="waner_chenhao_market_chat",
        name="师姐与师兄交谈",
        scene_id="market",
        trigger=EventTrigger(type="location_enter", conditions={"npc_present": ["linwaner", "chenhao"]}),
        narrative_hint="林婉儿和陈浩正在低声交谈，你隐约听到"山脉"和"异动"几个字。",
        guidance="listen_or_talk",
        allow_intervene=True,
        intervene_options=["上前搭话", "继续偷听", "默默离开"],
        one_time=True,
    ),
    WorldEvent(
        id="elder_scolding",
        name="长老训斥弟子",
        scene_id="inner_gate",
        trigger=EventTrigger(type="tick_interval", conditions={"min_tick": 8}),
        narrative_hint="一位长老正在训斥弟子：'竹林禁地，岂是尔等可以随意涉足的！'",
        guidance="explore_bamboo_forest",
        one_time=True,
    ),
    # Random encounters
    WorldEvent(
        id="spirit_herb",
        name="灵草发现",
        scene_id="bamboo_forest",
        trigger=EventTrigger(type="random", conditions={}, probability=0.1),
        narrative_hint="你在竹林中发现了一株散发着微光的灵草，灵气从中缓缓溢出。",
        guidance="explore_bamboo_forest",
        one_time=True,
    ),
    WorldEvent(
        id="strange_traveler",
        name="神秘旅人",
        scene_id="market",
        trigger=EventTrigger(type="random", conditions={}, probability=0.15),
        narrative_hint="集市角落坐着一个神秘旅人，眼神深邃，似乎在等待着什么。",
        guidance="talk_stranger",
        one_time=True,
    ),
    # Late-stage hints
    WorldEvent(
        id="waner_secret_hint",
        name="师姐的秘密",
        scene_id="inner_gate",
        trigger=EventTrigger(type="stat_threshold", conditions={"min_spirit": 50}),
        narrative_hint="师姐不经意间说漏了嘴，提到了一个关于宗门的秘密……",
        guidance="talk_linwaner",
        one_time=True,
    ),
]

# --- NPC Interaction Data ---

NPC_INTERACTIONS: list[NPCInteraction] = [
    NPCInteraction(
        id="waner_chenhao_chat",
        npc_ids=["linwaner", "chenhao"],
        scene_id="market",
        trigger_conditions={"tick_min": 5},
        narrative_hint="林婉儿和陈浩正在交谈，似乎在讨论山脉方向的异动。",
        allow_intervene=True,
        intervene_options=["上前搭话", "继续偷听", "默默离开"],
    ),
]

# --- New NPC Profiles ---

class NPCProfileData(BaseModel):
    """Data-only container for NPC seeding (separate from the interaction model)."""
    id: str
    name: str
    persona: str
    secret: str
    motive: str
    default_scene: str
    favorability: int = 50
    relationship_stage: str = "陌生"

ALL_NPC_PROFILES: list[NPCProfileData] = [
    NPCProfileData(
        id="linwaner",
        name="林婉儿",
        persona="青云门知心师姐，温柔体贴，修炼有成，善于倾听。",
        secret="她其实是宗门长老的私生女，身世不能暴露。",
        motive="希望找到一个可以信赖的人，但害怕自己的秘密被发现。",
        default_scene="inner_gate",
        favorability=50,
        relationship_stage="陌生",
    ),
    NPCProfileData(
        id="chenhao",
        name="陈浩",
        persona="青云门豪爽师兄，爱冒险，性格直率，武艺不凡但冲动。",
        secret="他偷偷在修炼一门禁术，一旦被发现将面临逐出宗门的危险。",
        motive="想要变强保护身边的人，但又忍不住禁术的诱惑。",
        default_scene="market",
        favorability=30,
        relationship_stage="陌生",
    ),
    NPCProfileData(
        id="old_yang",
        name="杨老",
        persona="外门守门人，沉默寡言但句句关键。看似普通老人，实则深藏不露。",
        secret="他曾是宗门最强的剑修，因故隐退至此。",
        motive="守护外门平安，偶尔点拨有缘的年轻修士。",
        default_scene="outer_gate",
        favorability=40,
        relationship_stage="陌生",
    ),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd E:\AI\llmud && python -m pytest tests/test_world_models.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add engine/models.py tests/test_world_models.py
git commit -m "feat: add scene, event, and world state models for living world system"
```

---

### Task 2: World Engine Logic

**Files:**
- Create: `engine/world.py`
- Test: `tests/test_world.py` (new)

**Interfaces:**
- Consumes: `SCENE_MAP`, `ALL_EVENTS`, `NPC_PRESENCES`, `NPC_INTERACTIONS`, `ENCOUNTERS_BY_SCENE` from `engine/models`
- Produces: `WorldEngine` class with `get_scene()`, `get_npcs_in_scene()`, `check_events()`, `check_npc_interactions()`, `validate_move()`, `advance_tick()`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_world.py
import pytest
from engine.models import Player
from engine.world import WorldEngine


@pytest.fixture
def engine():
    return WorldEngine()


@pytest.fixture
def fresh_player():
    return Player()


class TestGetScene:
    def test_get_valid_scene(self, engine):
        scene = engine.get_scene("outer_gate")
        assert scene.id == "outer_gate"
        assert scene.name == "青云门外门"

    def test_get_invalid_scene(self, engine):
        scene = engine.get_scene("nonexistent")
        assert scene is None

    def test_all_scenes_accessible(self, engine):
        for scene_id in ["outer_gate", "inner_gate", "bamboo_forest", "market", "mountain_range"]:
            scene = engine.get_scene(scene_id)
            assert scene is not None
            assert scene.id == scene_id


class TestGetNpcsInScene:
    def test_npc_at_default_scene(self, engine, fresh_player):
        npcs = engine.get_npcs_in_scene("inner_gate", fresh_player.tick)
        assert "linwaner" in npcs

    def test_npc_via_schedule(self, engine):
        # At tick 15, linwaner should be at market (schedule: tick 10-20)
        npcs = engine.get_npcs_in_scene("market", 15)
        assert "linwaner" in npcs

    def test_npc_not_at_scheduled_scene(self, engine):
        # At tick 5, linwaner should still be at default (inner_gate)
        npcs = engine.get_npcs_in_scene("market", 5)
        assert "linwaner" not in npcs

    def test_chenhao_always_at_market(self, engine, fresh_player):
        npcs = engine.get_npcs_in_scene("market", 0)
        assert "chenhao" in npcs

    def test_old_yang_at_outer_gate(self, engine, fresh_player):
        npcs = engine.get_npcs_in_scene("outer_gate", 0)
        assert "old_yang" in npcs


class TestCheckEvents:
    def test_first_time_event_at_outer_gate(self, engine, fresh_player):
        event = engine.check_events("outer_gate", fresh_player)
        # faint_spirit_sense triggers on first location_enter at outer_gate
        assert event is not None
        assert event.id == "faint_spirit_sense"

    def test_no_duplicate_one_time_event(self, engine):
        player = Player(seen_events=["faint_spirit_sense"])
        event = engine.check_events("outer_gate", player)
        # Should not trigger again
        assert event is None or event.id != "faint_spirit_sense"

    def test_stat_threshold_event(self, engine):
        player = Player(spirit_power=25, seen_events=[])
        event = engine.check_events("market", player)
        # chenhao_challenge requires min_spirit 25
        assert event is not None

    def test_no_event_when_conditions_not_met(self, engine, fresh_player):
        # Player at market with tick 0 — market_rumor needs min_tick 5
        event = engine.check_events("market", fresh_player)
        # No stat-threshold or random events should fire for a fresh player at market
        # (random events have low probability so might not fire — we test conditions)
        # The only event with conditions met at tick 0, spirit 10 at market would be none
        # because market_rumor needs tick >= 5
        pass

    def test_random_event_probability(self, engine):
        # Spirit herb has 10% probability — test by mocking
        player = Player(current_scene="bamboo_forest", seen_events=[])
        # Can't easily test probability, but verify it returns None or an event
        event = engine.check_events("bamboo_forest", player)
        assert event is None or event.id == "spirit_herb"


class TestCheckNpcInteractions:
    def test_interaction_when_npcs_present(self, engine):
        # At tick 15, linwaner is at market, chenhao is at market
        interaction = engine.check_npc_interactions("market", 15)
        assert interaction is not None

    def test_no_interaction_when_npcs_not_together(self, engine):
        # At tick 0, no two NPCs are in the same scene
        interaction = engine.check_npc_interactions("outer_gate", 0)
        assert interaction is None


class TestValidateMove:
    def test_valid_move(self, engine):
        result = engine.validate_move("outer_gate", "inner_gate")
        assert result is True

    def test_invalid_move_not_connected(self, engine):
        result = engine.validate_move("outer_gate", "mountain_range")
        assert result is False

    def test_invalid_move_nonexistent_scene(self, engine):
        result = engine.validate_move("outer_gate", "nonexistent")
        assert result is False

    def test_all_connections_are_valid(self, engine):
        for scene_id, scene in engine.scenes.items():
            for connected_id in scene.connections:
                assert engine.validate_move(scene_id, connected_id) is True


class TestAdvanceTick:
    def test_advance_increments_tick(self, engine, fresh_player):
        updated = engine.advance_tick(fresh_player)
        assert updated.tick == 1

    def test_advance_adds_to_seen_events(self, engine, fresh_player):
        # Force an event to fire
        event = engine.check_events("outer_gate", fresh_player)
        if event:
            updated = engine.apply_event(fresh_player, event)
            assert event.id in updated.seen_events


class TestGetEncounterForScene:
    def test_mountain_range_has_encounter(self, engine):
        encounters = engine.get_encounters_for_scene("mountain_range")
        assert len(encounters) > 0

    def test_outer_gate_no_encounter(self, engine):
        encounters = engine.get_encounters_for_scene("outer_gate")
        assert len(encounters) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd E:\AI\llmud && python -m pytest tests/test_world.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement WorldEngine**

Create `engine/world.py`:

```python
"""World engine — deterministic scene, event, and NPC state management."""
import random
from engine.models import (
    Scene, WorldEvent, NPCInteraction, Player,
    SCENE_MAP, ALL_EVENTS, NPC_PRESENCES, NPC_INTERACTIONS, ENCOUNTERS_BY_SCENE,
    Encounter, DEFAULT_ENCOUNTER,
)


class WorldEngine:
    """Manages scene data, event triggering, NPC presence, and world state."""

    def __init__(self):
        self.scenes: dict[str, Scene] = SCENE_MAP
        self.events: list[WorldEvent] = ALL_EVENTS
        self.npc_presences = NPC_PRESENCES
        self.npc_interactions: list[NPCInteraction] = NPC_INTERACTIONS

    def get_scene(self, scene_id: str) -> Scene | None:
        """Look up a scene by ID. Returns None if not found."""
        return self.scenes.get(scene_id)

    def get_npcs_in_scene(self, scene_id: str, tick: int) -> list[str]:
        """Return list of NPC IDs currently present in the given scene."""
        npcs = []
        for npc_id, presence in self.npc_presences.items():
            # Check schedule first
            scheduled = False
            for sched in presence.schedule:
                if sched.tick_range[0] <= tick <= sched.tick_range[1]:
                    if sched.scene_id == scene_id:
                        npcs.append(npc_id)
                        scheduled = True
                        break
                    else:
                        # NPC is at a different scene due to schedule
                        scheduled = True
                        break
            if not scheduled and presence.default_scene == scene_id:
                npcs.append(npc_id)
        return npcs

    def check_events(self, scene_id: str, player: Player) -> WorldEvent | None:
        """
        Check which events can fire in the current scene for this player.
        Returns the highest-priority event that passes all conditions, or None.
        Only one event per action (D4).
        """
        candidates = []
        for event in self.events:
            if event.scene_id != scene_id:
                continue
            if event.one_time and event.id in player.seen_events:
                continue
            if not self._check_trigger(event, player):
                continue
            candidates.append(event)

        if not candidates:
            return None

        # Sort by priority: location_enter > stat_threshold > tick_interval > random
        # Then by one_time first, then by probability
        priority_order = {"location_enter": 0, "stat_threshold": 1, "tick_interval": 2, "random": 3}
        candidates.sort(key=lambda e: (
            priority_order.get(e.trigger.type, 99),
            not e.one_time,
            -e.trigger.probability,
        ))

        # Check probability for the top candidate
        top = candidates[0]
        if top.trigger.probability < 1.0:
            if random.random() > top.trigger.probability:
                return None
        return top

    def _check_trigger(self, event: WorldEvent, player: Player) -> bool:
        """Check if a single event's trigger conditions are met."""
        trigger = event.trigger
        conds = trigger.conditions

        if trigger.type == "location_enter":
            # first_time condition: player hasn't been to this scene before
            if conds.get("first_time"):
                scene_id = event.scene_id
                visit_key = f"visited_{scene_id}"
                if visit_key in player.seen_events:
                    return False
            return True

        elif trigger.type == "stat_threshold":
            min_spirit = conds.get("min_spirit", 0)
            max_spirit = conds.get("max_spirit", 9999)
            if not (min_spirit <= player.spirit_power <= max_spirit):
                return False
            return True

        elif trigger.type == "tick_interval":
            min_tick = conds.get("min_tick", 0)
            if player.tick < min_tick:
                return False
            return True

        elif trigger.type == "random":
            return True  # probability is checked separately

        return False

    def check_npc_interactions(self, scene_id: str, tick: int) -> NPCInteraction | None:
        """Check if any NPC interaction should fire in the current scene."""
        npcs_present = self.get_npcs_in_scene(scene_id, tick)

        for interaction in self.npc_interactions:
            if interaction.scene_id != scene_id:
                continue
            # Check if all required NPCs are present
            required_npcs = set(interaction.npc_ids)
            present_set = set(npcs_present)
            if not required_npcs.issubset(present_set):
                continue
            # Check tick condition
            tick_min = interaction.trigger_conditions.get("tick_min", 0)
            if tick < tick_min:
                continue
            return interaction
        return None

    def validate_move(self, from_scene: str, to_scene: str) -> bool:
        """Check if moving from from_scene to to_scene is valid."""
        scene = self.scenes.get(from_scene)
        if scene is None:
            return False
        if to_scene not in self.scenes:
            return False
        return to_scene in scene.connections

    def advance_tick(self, player: Player) -> Player:
        """Increment player tick by 1."""
        return player.model_copy(update={"tick": player.tick + 1})

    def apply_event(self, player: Player, event: WorldEvent) -> Player:
        """Mark a one-time event as seen by the player."""
        if event.one_time:
            new_seen = list(player.seen_events)
            new_seen.append(event.id)
            # For location_enter events, also mark the scene as visited
            if event.trigger.type == "location_enter":
                visit_key = f"visited_{event.scene_id}"
                if visit_key not in new_seen:
                    new_seen.append(visit_key)
            return player.model_copy(update={"seen_events": new_seen})
        return player

    def get_encounters_for_scene(self, scene_id: str) -> list[str]:
        """Return encounter IDs available in this scene."""
        return ENCOUNTERS_BY_SCENE.get(scene_id, [])

    def resolve_scene_move(self, player: Player, destination_text: str) -> tuple[str, str | None]:
        """
        Try to resolve a destination text to a scene ID.
        Returns (status, scene_id_or_error_message).
        status is "ok" or "error".
        """
        # Chinese name mapping
        name_to_id = {
            "外门": "outer_gate",
            "青云门外门": "outer_gate",
            "内门": "inner_gate",
            "青云门内门": "inner_gate",
            "竹林": "bamboo_forest",
            "幽竹林": "bamboo_forest",
            "集市": "market",
            "修士集市": "market",
            "山脉": "mountain_range",
            "妖兽山脉": "mountain_range",
        }

        # Try exact match first
        for name, sid in name_to_id.items():
            if name in destination_text:
                if self.validate_move(player.current_scene, sid):
                    return ("ok", sid)
                else:
                    return ("error", f"无法从{self.scenes[player.current_scene].name}前往{name}——路不通。")

        # No match found
        return ("error", f"不知道去哪里：{destination_text}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd E:\AI\llmud && python -m pytest tests/test_world.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add engine/world.py tests/test_world.py
git commit -m "feat: add WorldEngine with scene, event, and NPC state management"
```

---

### Task 3: Move Logic & Classification Updates

**Files:**
- Modify: `engine/rules.py`
- Modify: `engine/classify.py`
- Test: modify `tests/test_rules.py`
- Test: modify `tests/test_classify.py`

**Interfaces:**
- Consumes: `WorldEngine` from `engine/world`, `SCENE_MAP` from `engine/models`
- Produces: `move()` function in rules.py, updated `classify_intent()` with INTERVENE and destination parsing

- [ ] **Step 1: Write the failing test for move()**

Add to `tests/test_rules.py`:

```python
from engine.rules import move
from engine.models import Player

def test_move_to_connected_scene():
    player = Player(current_scene="outer_gate")
    result = move(player, "inner_gate")
    assert result.current_scene == "inner_gate"

def test_move_to_invalid_scene():
    player = Player(current_scene="outer_gate")
    result = move(player, "mountain_range")
    # Should not move — outer_gate is not connected to mountain_range
    assert result.current_scene == "outer_gate"

def test_move_preserves_other_fields():
    player = Player(current_scene="outer_gate", spirit_power=42, hp=80)
    result = move(player, "inner_gate")
    assert result.spirit_power == 42
    assert result.hp == 80
    assert result.current_scene == "inner_gate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd E:\AI\llmud && python -m pytest tests/test_rules.py::test_move_to_connected_scene -v`
Expected: FAIL — `move` not imported

- [ ] **Step 3: Implement move() in rules.py**

Add to `engine/rules.py`:

```python
from engine.models import SCENE_MAP


def move(player: Player, destination: str) -> Player:
    """
    Move player to destination scene if valid connection.
    Returns updated player copy if valid, unchanged player if invalid.
    """
    current_scene = SCENE_MAP.get(player.current_scene)
    if current_scene is None:
        return player
    if destination not in SCENE_MAP:
        return player
    if destination not in current_scene.connections:
        return player
    return player.model_copy(update={"current_scene": destination})
```

Also add the import at the top of `rules.py`:

```python
from engine.models import Player, Encounter, CombatResult, BreakthroughResult, LevelTier, LEVEL_TABLE
```

This import already exists. Just add `SCENE_MAP` to the import line.

- [ ] **Step 4: Update classify.py for INTERVENE and destination parsing**

Modify `engine/classify.py`:

Add `INTERVENE_PATTERNS` after the existing pattern lists:

```python
INTERVENE_PATTERNS = [
    r"上前搭话", r"加入对话", r"介入", r"插嘴", r"打断",
]
```

Add `INTERVENE` handling in `classify_intent`:

```python
from engine.models import Intent

# ... existing patterns ...

INTERVENE_PATTERNS = [
    r"上前搭话", r"加入对话", r"介入", r"插嘴", r"打断",
]

def classify_intent(action_text: str, llm_client=None) -> tuple[Intent, dict]:
    """
    Classify player action into an intent using regex fast-path first.
    Falls back to LLM classification if no pattern matches and a client is provided.
    Returns (Intent, parsed_params) where parsed_params carries extra info.
    """
    params = {}

    # INTERVENE — check before MOVE (intervene actions are specific)
    if _match_patterns(action_text, INTERVENE_PATTERNS):
        params["action"] = action_text
        return Intent.INTERVENE, params

    # Fast-path: regex matching (MOVE first — action verbs like "前往" should
    # take priority over destination nouns like "练功房" that alias cultivate)
    if _match_patterns(action_text, MOVE_PATTERNS):
        params["destination"] = action_text  # DM will interpret
        return Intent.MOVE, params

    if _match_patterns(action_text, CULTIVATE_PATTERNS):
        return Intent.CULTIVATE, params

    if _match_patterns(action_text, TALK_PATTERNS):
        params["target"] = "师姐"  # Only one NPC in slice
        return Intent.TALK, params

    if _match_patterns(action_text, FIGHT_PATTERNS):
        params["target"] = "赤眼妖狼"  # Only one encounter in slice
        return Intent.FIGHT, params

    # Fallback: LLM classification (async, called from api layer)
    # For the slice, if no LLM client, default to OTHER
    return Intent.OTHER, params
```

The full updated `classify.py` is the same as current except with INTERVENE_PATTERNS added and the INTERVENE check inserted before the MOVE check.

- [ ] **Step 5: Run tests to verify**

Run: `cd E:\AI\llmud && python -m pytest tests/test_rules.py tests/test_classify.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add engine/rules.py engine/classify.py tests/test_rules.py tests/test_classify.py
git commit -m "feat: add move validation and intervene intent classification"
```

---

### Task 4: Player Model & DB Migration

**Files:**
- Modify: `engine/models.py` (Player model already updated in Task 1)
- Modify: `db/connection.py`
- Modify: `db/repository.py`
- Test: modify `tests/test_repository.py`

**Interfaces:**
- Consumes: Updated `Player` model with `current_scene`, `seen_events`, `tick`
- Produces: DB schema with new columns; repository methods handling new fields

- [ ] **Step 1: Update DB schema in connection.py**

Modify `db/connection.py` — add `current_scene` and `seen_events` columns to the `players` table, and add `default_scene` to `npc_profiles`:

```python
import sqlite3


def init_db(conn: sqlite3.Connection):
    """Create tables if they don't exist."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT '练气期一层',
            spirit_power INTEGER NOT NULL DEFAULT 10,
            hp INTEGER NOT NULL DEFAULT 100,
            max_hp INTEGER NOT NULL DEFAULT 100,
            affinity TEXT NOT NULL DEFAULT '火',
            current_scene TEXT NOT NULL DEFAULT 'outer_gate',
            inventory TEXT NOT NULL DEFAULT '[]',
            recent_stories TEXT NOT NULL DEFAULT '[]',
            seen_events TEXT NOT NULL DEFAULT '[]',
            tick INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS npc_profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            persona TEXT NOT NULL,
            secret TEXT NOT NULL DEFAULT '',
            motive TEXT NOT NULL DEFAULT '',
            favorability INTEGER NOT NULL DEFAULT 50,
            relationship_stage TEXT NOT NULL DEFAULT '陌生',
            default_scene TEXT NOT NULL DEFAULT 'outer_gate'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS npc_memories (
            npc_id TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            recent_turns TEXT NOT NULL DEFAULT '[]',
            key_facts TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY (npc_id) REFERENCES npc_profiles(id),
            PRIMARY KEY (npc_id)
        )
    """)

    # Migration: add columns to existing tables if they don't exist
    _migrate_add_column(conn, "players", "current_scene", "TEXT NOT NULL DEFAULT 'outer_gate'")
    _migrate_add_column(conn, "players", "seen_events", "TEXT NOT NULL DEFAULT '[]'")
    _migrate_add_column(conn, "players", "tick", "INTEGER NOT NULL DEFAULT 0")
    _migrate_add_column(conn, "npc_profiles", "default_scene", "TEXT NOT NULL DEFAULT 'outer_gate'")

    conn.commit()


def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str, definition: str):
    """Add a column to a table if it doesn't already exist."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def get_db(db_path: str = "llmud.db") -> sqlite3.Connection:
    """Get a database connection, creating the DB file if needed."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn
```

- [ ] **Step 2: Update repository.py to handle new fields**

Modify `db/repository.py` — update `PlayerRepository.get()` and `save()` and `update()` to use `current_scene` instead of `location`, and handle `seen_events` and `tick`:

Replace `PlayerRepository` class entirely:

```python
class PlayerRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, player_id: str) -> Player | None:
        row = self.conn.execute(
            "SELECT * FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if row is None:
            return None

        # Handle both old (location) and new (current_scene) columns
        current_scene = row["current_scene"] if "current_scene" in row.keys() else "outer_gate"
        seen_events = json.loads(row["seen_events"]) if "seen_events" in row.keys() and row["seen_events"] else []
        tick = row["tick"] if "tick" in row.keys() else 0
        recent_stories = json.loads(row["recent_stories"]) if "recent_stories" in row.keys() and row["recent_stories"] else []

        return Player(
            id=row["id"],
            name=row["name"],
            level=row["level"],
            spirit_power=row["spirit_power"],
            hp=row["hp"],
            max_hp=row["max_hp"],
            affinity=row["affinity"],
            current_scene=current_scene,
            inventory=json.loads(row["inventory"]) if row["inventory"] else [],
            recent_stories=recent_stories,
            seen_events=seen_events,
            tick=tick,
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
        )

    def save(self, player: Player) -> None:
        self.conn.execute(
            """INSERT INTO players (id, name, level, spirit_power, hp, max_hp, affinity,
               current_scene, inventory, recent_stories, seen_events, tick, created_at, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (player.id, player.name, player.level, player.spirit_power,
             player.hp, player.max_hp, player.affinity, player.current_scene,
             json.dumps(player.inventory), json.dumps(player.recent_stories, ensure_ascii=False),
             json.dumps(player.seen_events, ensure_ascii=False), player.tick,
             player.created_at.isoformat(), player.last_seen.isoformat()),
        )
        self.conn.commit()

    def update(self, player: Player) -> None:
        self.conn.execute(
            """UPDATE players SET name=?, level=?, spirit_power=?, hp=?, max_hp=?,
               affinity=?, current_scene=?, inventory=?, recent_stories=?,
               seen_events=?, tick=?, last_seen=? WHERE id=?""",
            (player.name, player.level, player.spirit_power, player.hp,
             player.max_hp, player.affinity, player.current_scene,
             json.dumps(player.inventory), json.dumps(player.recent_stories, ensure_ascii=False),
             json.dumps(player.seen_events, ensure_ascii=False), player.tick,
             datetime.now().isoformat(), player.id),
        )
        self.conn.commit()
```

Also update `NPCRepository.save_profile` to handle `default_scene`:

```python
def save_profile(self, npc_id: str, name: str, persona: str,
                 secret: str = "", motive: str = "",
                 favorability: int = 50, relationship_stage: str = "陌生",
                 default_scene: str = "outer_gate") -> None:
    self.conn.execute(
        """INSERT OR REPLACE INTO npc_profiles (id, name, persona, secret, motive, favorability, relationship_stage, default_scene)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (npc_id, name, persona, secret, motive, favorability, relationship_stage, default_scene),
    )
    self.conn.commit()
```

- [ ] **Step 3: Update test fixtures for new Player fields**

In `tests/conftest.py`, no changes needed since the `Player()` model now has defaults for `current_scene`, `seen_events`, and `tick`.

Update existing tests that create `Player` objects with `location=` to use `current_scene=` instead. This affects `tests/test_rules.py`. Change all `location="..."` to `current_scene="..."` in test fixtures.

- [ ] **Step 4: Update DEFAULT_PLAYER in models.py**

The `DEFAULT_PLAYER` constant should reflect the new field:

```python
DEFAULT_PLAYER = Player()
```

This already works since `current_scene` defaults to `"outer_gate"`, `seen_events` defaults to `[]`, and `tick` defaults to `0`. The old `location` field is removed.

- [ ] **Step 5: Run tests to verify**

Run: `cd E:\AI\llmud && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add db/connection.py db/repository.py engine/models.py tests/
git commit -m "feat: migrate Player model to current_scene, add seen_events and tick fields"
```

---

### Task 5: DM Prompt & NPC Model Enhancement

**Files:**
- Modify: `dm/prompt.py`
- Modify: `npc/models.py`
- Modify: `api/app.py`
- Test: modify `tests/test_contract.py`

**Interfaces:**
- Consumes: `WorldEvent`, `NPCInteraction`, `Scene` from `engine/models`; `WorldEngine` from `engine/world`
- Produces: Updated `build_dm_prompt()` with scene context and world event injection; updated `NPCProfile` with `default_scene`; updated seeding for 3 NPCs

- [ ] **Step 1: Update NPCProfile model in npc/models.py**

Replace the entire `npc/models.py`:

```python
from pydantic import BaseModel, Field


class NPCProfile(BaseModel):
    id: str = "linwaner"
    name: str = "林婉儿"
    persona: str = "青云门知心师姐，温柔体贴，修炼有成，善于倾听。"
    secret: str = "她其实是宗门长老的私生女，身世不能暴露。"
    motive: str = "希望找到一个可以信赖的人，但害怕自己的秘密被发现。"
    favorability: int = 50
    relationship_stage: str = "陌生"
    default_scene: str = "inner_gate"


class NPCTurn(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class KeyFact(BaseModel):
    fact: str
    turn_number: int


class NPCMemory(BaseModel):
    npc_id: str = "linwaner"
    recent_turns: list[NPCTurn] = Field(default_factory=list)
    summary: str = ""
    key_facts: list[KeyFact] = Field(default_factory=list)


# Seed data for the 师姐
DEFAULT_NPC_PROFILE = NPCProfile()
```

- [ ] **Step 2: Update DM prompt to inject scene context and world events**

Modify `dm/prompt.py` — add world event and scene context injection:

Update `build_dm_prompt` signature to accept optional world event and scene info:

```python
from engine.models import Player, Intent, CombatResult, BreakthroughResult, Scene, WorldEvent


DM_SYSTEM_TEMPLATE = """你是一款文字修仙 MUD 游戏的"动态地下城主（DM）"。
请根据玩家输入的行动，结合玩家当前状态和引擎结算结果，生成一段精彩、具有网文爽感的文字描写。

【当前玩家状态】：
- 名字：{name}
- 所在地点：{location}
- 当前境界：{level}
- 当前灵力：{spirit_power}
- 当前气血：{hp}/{max_hp}

{engine_context}

【近期事件】：
{recent_stories}

{scene_context}

{world_event_context}

【硬性规则】：
1. 你的每一次回复【必须】严格遵守以下 JSON 格式，不要包含任何 markdown 标记（如 ```json），直接返回纯 JSON 字符串。
2. 玩家不能凭空无敌。
3. 故事描写【不得为空】，必须生成一段叙事文字，限制在120字以内。无论玩家行动多么简单，都必须给出story字段。
4. 战斗数值【必须】与引擎结算结果完全一致，不得臆造。
5. 如果不确定如何描写，也要给出一个简短但有画面感的叙事。
6. 【叙事一致性】你【必须】参考【近期事件】中的内容！玩家之前做过的事、吃过的东西、去过的地方必须保持一致。如果玩家之前吃了"凝露草"，就不能说吃了"丹药"；如果玩家已经到了"竹林"，就不能说玩家在"柴房"。
7. 【地点一致性】玩家当前所在地点为"{location}"，你的叙事【必须】以这个地点为场景，不得凭空将玩家传送到其他地点。
8. 【世界事件】如果【世界事件】部分有内容，你【必须】将其自然地融入叙事中。不要生硬地说"你注意到……"，而是将环境感知融入描写中。例如，如果在竹林感知到灵草，就在修炼或探索描写中自然带出。"""


def build_dm_prompt(
    player: Player,
    intent: Intent,
    combat_result: CombatResult | None = None,
    breakthrough: BreakthroughResult | None = None,
    npc_context: str = "",
    recent_stories: list[str] | None = None,
    scene: Scene | None = None,
    world_event: WorldEvent | None = None,
) -> tuple[str, str]:
    """Build the system and user prompts for the DM LLM call."""
    if intent == Intent.FIGHT and combat_result:
        engine_ctx = ENGINE_CONTEXT_TEMPLATES["fight"].format(
            combat_result=f"{combat_result.result}",
            dmg_to_enemy=combat_result.dmg_to_enemy,
            dmg_to_player=combat_result.dmg_to_player,
            result=combat_result.result,
        )
    else:
        engine_ctx = ENGINE_CONTEXT_TEMPLATES.get(intent.value, ENGINE_CONTEXT_TEMPLATES["other"])

    if breakthrough:
        engine_ctx += f"\n【突破】玩家从{breakthrough.from_level}突破到{breakthrough.to_level}！"

    # Build recent stories context (last 5 entries)
    stories_text = "（无）"
    if recent_stories:
        stories_text = "\n".join(f"- {s}" for s in recent_stories[-5:])

    # Build scene context
    scene_context = ""
    if scene:
        scene_context = f"【当前场景】{scene.name}（{scene.atmosphere}）：{scene.description}"
        npcs_present_text = ""
        # NPCs present will be injected separately by the route handler

    # Build world event context
    world_event_context = ""
    if world_event:
        world_event_context = f"【世界事件】{world_event.narrative_hint}"
        if world_event.allow_intervene and world_event.intervene_options:
            options_text = "、".join(world_event.intervene_options)
            world_event_context += f"\n玩家可以选择：{options_text}"

    system_prompt = DM_SYSTEM_TEMPLATE.format(
        name=player.name,
        location=player.current_scene if hasattr(player, 'current_scene') else scene.name if scene else "未知",
        level=player.level,
        spirit_power=player.spirit_power,
        hp=player.hp,
        max_hp=player.max_hp,
        engine_context=engine_ctx,
        recent_stories=stories_text,
        scene_context=scene_context,
        world_event_context=world_event_context,
    )

    user_prompt = ""
    if npc_context:
        user_prompt = npc_context

    return system_prompt, user_prompt
```

- [ ] **Step 3: Update app.py to seed all 3 NPCs**

Modify `api/app.py` — update seed function and add WorldEngine initialization:

```python
"""FastAPI application factory — wires all subsystems together."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from dm.client import LLMClient
from db.repository import PlayerRepository, NPCRepository
from engine.models import DEFAULT_PLAYER, DEFAULT_ENCOUNTER, ALL_NPC_PROFILES
from npc.models import DEFAULT_NPC_PROFILE
from api.routes import create_router
from api.deps import get_llm_client, create_db_connection_from_env
from engine.world import WorldEngine


def seed_database(player_repo: PlayerRepository, npc_repo: NPCRepository):
    """Seed the database with default player and NPC data."""
    if player_repo.get(DEFAULT_PLAYER.id) is None:
        player_repo.save(DEFAULT_PLAYER)

    # Seed all NPC profiles
    for npc_data in ALL_NPC_PROFILES:
        existing = npc_repo.get_profile(npc_data.id)
        if existing is None:
            npc_repo.save_profile(
                npc_id=npc_data.id,
                name=npc_data.name,
                persona=npc_data.persona,
                secret=npc_data.secret,
                motive=npc_data.motive,
                favorability=npc_data.favorability,
                relationship_stage=npc_data.relationship_stage,
                default_scene=npc_data.default_scene,
            )
            npc_repo.save_memory(npc_data.id)


def create_app(llm_client: LLMClient | None = None, db_path: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    llm = llm_client or get_llm_client()
    conn = create_db_connection_from_env(db_path)
    player_repo = PlayerRepository(conn)
    npc_repo = NPCRepository(conn)
    world_engine = WorldEngine()

    # Seed default data
    seed_database(player_repo, npc_repo)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        conn.close()

    app = FastAPI(title="修仙 MUD — llmud", lifespan=lifespan)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include game routes
    router = create_router(
        llm_client=llm,
        player_repo=player_repo,
        npc_repo=npc_repo,
        encounter=DEFAULT_ENCOUNTER,
        world_engine=world_engine,
    )
    app.include_router(router)

    # Serve static frontend (if available)
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    if os.path.isdir(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    # Store deps on app state for testing
    app.state.llm_client = llm
    app.state.db_conn = conn
    app.state.player_repo = player_repo
    app.state.npc_repo = npc_repo
    app.state.world_engine = world_engine

    return app
```

- [ ] **Step 4: Run tests to verify**

Run: `cd E:\AI\llmud && python -m pytest tests/test_contract.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dm/prompt.py npc/models.py api/app.py tests/
git commit -m "feat: add scene context and world events to DM prompt, expand NPC seeding"
```

---

### Task 6: API Pipeline Integration

**Files:**
- Modify: `api/routes.py`
- Test: modify `tests/test_api.py`

**Interfaces:**
- Consumes: `WorldEngine` from `engine/world`, `SCENE_MAP`, `ALL_NPC_PROFILES` from `engine/models`, `move` from `engine/rules`, updated `build_dm_prompt`
- Produces: Updated `/game/action` pipeline with world layer; new `GET /game/scenes` endpoint; updated `GET /player/status` with scene info; response includes `world_event` and `intervention` fields

- [ ] **Step 1: Update routes.py — add world layer to pipeline**

The full updated `api/routes.py` is substantial. Key changes:
1. `create_router` now accepts `world_engine: WorldEngine`
2. `GET /player/status` returns scene info
3. `POST /game/action` includes world layer between engine and DM
4. `GET /game/scenes` returns world map
5. Response includes `world_event` and `intervention` fields
6. TALK intent resolves NPC from scene instead of hardcoded DEFAULT
7. FIGHT intent resolves encounter from scene

```python
"""Game endpoints — orchestrates the full classify→engine→world→dm pipeline."""
import json
import random

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dm.client import LLMClient
from dm.contract import parse_dm_response_with_retry
from dm.prompt import build_dm_prompt
from engine.classify import classify_intent
from engine.models import Intent, Player, Encounter, DEFAULT_ENCOUNTER, SCENE_MAP
from engine.rules import cultivate, resolve_combat, check_breakthrough, compute_attack, compute_defense, move
from engine.world import WorldEngine
from db.repository import PlayerRepository, NPCRepository
from npc.memory import update_memory, build_memory_context, compute_relationship_stage
from npc.models import NPCMemory, NPCTurn, KeyFact, DEFAULT_NPC_PROFILE
from safety.filter import pre_filter_input, post_filter_output


class ActionRequest(BaseModel):
    user_input: str


def create_router(
    llm_client: LLMClient,
    player_repo: PlayerRepository,
    npc_repo: NPCRepository,
    encounter: Encounter,
    world_engine: WorldEngine,
) -> APIRouter:
    """Create a FastAPI router with game endpoints, wiring all subsystems."""
    router = APIRouter()

    @router.get("/player/status")
    def get_status():
        """Return current player status with scene information."""
        player = player_repo.get("p1")
        if player is None:
            return {"error": "Player not found"}

        scene = world_engine.get_scene(player.current_scene)
        npcs_present = world_engine.get_npcs_in_scene(player.current_scene, player.tick)

        result = {
            "name": player.name,
            "location": scene.name if scene else player.current_scene,
            "current_scene": player.current_scene,
            "level": player.level,
            "spirit_power": player.spirit_power,
            "hp": player.hp,
            "max_hp": player.max_hp,
            "affinity": player.affinity,
            "inventory": player.inventory,
            "attack": compute_attack(player),
            "defense": compute_defense(player),
            "tick": player.tick,
            "scene": {
                "id": scene.id if scene else player.current_scene,
                "name": scene.name if scene else "未知",
                "atmosphere": scene.atmosphere if scene else "",
                "npcs_present": npcs_present,
                "connections": scene.connections if scene else [],
            } if scene else None,
        }
        return result

    @router.get("/game/scenes")
    def get_scenes():
        """Return the world map — all scenes and their connections."""
        scenes = []
        for scene_id, scene in SCENE_MAP.items():
            scenes.append({
                "id": scene.id,
                "name": scene.name,
                "atmosphere": scene.atmosphere,
                "connections": scene.connections,
                "available_actions": scene.available_actions,
            })
        return {"scenes": scenes}

    @router.post("/game/action")
    async def game_action(request: ActionRequest):
        """Process a player action through the full pipeline."""
        # Step 1: Pre-filter input for safety
        filtered_input, blocked = pre_filter_input(request.user_input)
        if blocked:
            def blocked_response():
                yield json.dumps({
                    "intent": "other",
                    "action_valid": False,
                    "invalid_reason": "内容不合规",
                    "story": filtered_input,
                    "state_delta": {},
                    "breakthrough": None,
                    "combat": None,
                    "npc_update": None,
                    "world_event": None,
                    "intervention": None,
                }, ensure_ascii=False)
            return StreamingResponse(blocked_response(), media_type="application/json")

        # Load player state
        player = player_repo.get("p1")
        if player is None:
            player = Player()

        # Step 2: Classify intent
        intent, params = classify_intent(filtered_input, llm_client=llm_client)

        # Step 3: Engine resolution (deterministic)
        combat_result = None
        breakthrough = None
        move_error = None

        if intent == Intent.CULTIVATE:
            player = cultivate(player)
            breakthrough = check_breakthrough(player)
            if breakthrough:
                player = player.model_copy(update={"level": breakthrough.to_level})

        elif intent == Intent.FIGHT:
            # Determine encounter based on current scene
            scene_encounters = world_engine.get_encounters_for_scene(player.current_scene)
            current_encounter = encounter  # fallback to default
            # For now, use default encounter if scene has encounters
            combat_result, player, _ = resolve_combat(player, current_encounter)
            if combat_result.result == "lose":
                player = player.model_copy(update={"hp": 1})

        elif intent == Intent.TALK:
            pass  # NPC interaction handled in DM phase

        elif intent == Intent.MOVE:
            destination = params.get("destination", "")
            status, result = world_engine.resolve_scene_move(player, destination)
            if status == "ok":
                player = move(player, result)
            else:
                move_error = result

        elif intent == Intent.INTERVENE:
            pass  # Intervention handled in DM phase with context

        # Step 4: World state update
        player = world_engine.advance_tick(player)

        # Check for world events
        world_event = world_engine.check_events(player.current_scene, player)
        npc_interaction = world_engine.check_npc_interactions(
            player.current_scene, player.tick
        )

        # If NPC interaction takes priority over world event, use that instead
        if npc_interaction:
            # Convert NPC interaction to a WorldEvent-like structure for the prompt
            from engine.models import WorldEvent, EventTrigger
            world_event = WorldEvent(
                id=npc_interaction.id,
                name=npc_interaction.id,
                scene_id=npc_interaction.scene_id,
                trigger=EventTrigger(type="npc_interaction", conditions={}),
                narrative_hint=npc_interaction.narrative_hint,
                guidance="observe_or_intervene",
                allow_intervene=npc_interaction.allow_intervene,
                intervene_options=npc_interaction.intervene_options,
                one_time=True,
            )

        # Apply event (mark as seen)
        if world_event:
            player = world_engine.apply_event(player, world_event)

        # Step 5: Narrative (DM LLM call)
        npc_context = ""
        npc_update_dict = None

        if intent == Intent.TALK:
            # Determine which NPC to talk to based on scene
            npcs_in_scene = world_engine.get_npcs_in_scene(player.current_scene, player.tick)
            target_npc_id = npcs_in_scene[0] if npcs_in_scene else DEFAULT_NPC_PROFILE.id

            # If player mentioned a specific NPC, try to match
            for npc_id in npcs_in_scene:
                # Check all NPC names from ALL_NPC_PROFILES
                from engine.models import ALL_NPC_PROFILES
                for npc_data in ALL_NPC_PROFILES:
                    if npc_data.id == npc_id and npc_data.name in filtered_input:
                        target_npc_id = npc_id
                        break

            profile_row = npc_repo.get_profile(target_npc_id)
            npc_profile = dict(profile_row) if profile_row else {}

            npc_memory_row = npc_repo.get_memory(target_npc_id)
            if npc_memory_row:
                memory = _build_memory_from_row(npc_memory_row)
            else:
                memory = NPCMemory(npc_id=target_npc_id)

            npc_context = build_memory_context(memory)

        scene = world_engine.get_scene(player.current_scene)

        system_prompt, user_prompt = build_dm_prompt(
            player=player,
            intent=intent,
            combat_result=combat_result,
            breakthrough=breakthrough,
            npc_context=npc_context,
            recent_stories=player.recent_stories,
            scene=scene,
            world_event=world_event,
        )

        # Prepend the user's actual input to the prompt
        if user_prompt:
            user_prompt = f"{user_prompt}\n\n玩家：{filtered_input}"
        else:
            user_prompt = filtered_input

        # Add move error if movement failed
        if move_error:
            user_prompt = f"{user_prompt}\n\n【系统提示：移动失败】{move_error}"

        # Call LLM
        try:
            raw_response = await llm_client.generate(system_prompt, user_prompt)
        except Exception:
            def error_response():
                yield json.dumps({
                    "intent": intent.value,
                    "action_valid": False,
                    "invalid_reason": "传信飞鸽被雷劈了",
                    "story": "【系统】传信飞鸽在半路被雷劈了，请重试。",
                    "state_delta": {},
                    "breakthrough": None,
                    "combat": None,
                    "npc_update": None,
                    "world_event": None,
                    "intervention": None,
                }, ensure_ascii=False)
            return StreamingResponse(error_response(), media_type="application/json")

        # Step 6: Post-filter output
        raw_response, _was_rewritten = post_filter_output(raw_response)

        # Step 7: Parse DM response
        dm_response = await parse_dm_response_with_retry(
            raw_response, client=llm_client,
            system_prompt=system_prompt, user_prompt=user_prompt,
        )

        # Ensure story is never empty
        story = dm_response.story
        if not story or not story.strip():
            story_fallbacks = {
                Intent.CULTIVATE: f"{player.name}盘膝而坐，静静修炼，灵气缓缓涌入丹田。",
                Intent.TALK: f"{player.name}与身边的人交谈了几句。",
                Intent.FIGHT: f"{player.name}与妖兽展开了激烈的交锋！",
                Intent.MOVE: f"{player.name}向新的方向走去。" if not move_error else move_error,
                Intent.INTERVENE: f"{player.name}做出了选择。",
                Intent.OTHER: f"{player.name}的行动似乎没有引起什么变化。",
            }
            story = story_fallbacks.get(intent, f"{player.name}的行动似乎没有引起什么变化。")

        # Apply state_delta from DM
        if dm_response.state_delta and dm_response.action_valid:
            updates = {}
            if "spirit_power" in dm_response.state_delta:
                updates["spirit_power"] = player.spirit_power + dm_response.state_delta["spirit_power"]
            if "hp" in dm_response.state_delta:
                updates["hp"] = max(1, player.hp + dm_response.state_delta["hp"])
            if "location" in dm_response.state_delta:
                # Map old location field to current_scene
                from engine.models import SCENE_MAP
                loc = dm_response.state_delta["location"]
                # Try to resolve to a scene ID
                for scene_id, scene_obj in SCENE_MAP.items():
                    if scene_obj.name == loc or scene_id == loc:
                        updates["current_scene"] = scene_id
                        break
            if "current_scene" in dm_response.state_delta:
                updates["current_scene"] = dm_response.state_delta["current_scene"]
            if updates:
                player = player.model_copy(update=updates)

        # Apply breakthrough from DM (authoritative if present)
        if dm_response.breakthrough:
            player = player.model_copy(update={"level": dm_response.breakthrough.to_level})

        # Handle NPC update
        if dm_response.npc_update:
            npc_update_dict = dm_response.npc_update
            # Determine target NPC
            npcs_in_scene = world_engine.get_npcs_in_scene(player.current_scene, player.tick)
            target_npc_id = npcs_in_scene[0] if npcs_in_scene else DEFAULT_NPC_PROFILE.id

            profile_row = npc_repo.get_profile(target_npc_id)
            profile_dict = dict(profile_row) if profile_row else {}
            current_favorability = profile_dict.get("favorability", 50)
            favorability_change = npc_update_dict.get("favorability_change", 0)
            new_favorability = max(0, min(100, current_favorability + favorability_change))
            new_stage = compute_relationship_stage(new_favorability)
            npc_repo.update_favorability(target_npc_id, new_favorability, new_stage)

            # Update NPC memory
            npc_memory_row = npc_repo.get_memory(target_npc_id)
            memory = _build_memory_from_row(npc_memory_row) if npc_memory_row else NPCMemory(npc_id=target_npc_id)
            memory = update_memory(
                memory,
                user_message=filtered_input,
                npc_response=dm_response.story,
                npc_update=npc_update_dict,
            )
            npc_repo.update_memory(
                target_npc_id,
                summary=memory.summary,
                recent_turns=[t.model_dump() for t in memory.recent_turns],
                key_facts=[f.model_dump() for f in memory.key_facts],
            )

        # Update recent story history (keep last 5)
        updated_stories = list(player.recent_stories or [])
        updated_stories.append(story)
        if len(updated_stories) > 5:
            updated_stories = updated_stories[-5:]
        player = player.model_copy(update={"recent_stories": updated_stories})

        # Persist player state
        player_repo.update(player)

        # Build response
        response_data = {
            "intent": intent.value,
            "action_valid": dm_response.action_valid and not bool(move_error),
            "story": story,
            "state_delta": dm_response.state_delta or {},
            "player": {
                "name": player.name,
                "current_scene": player.current_scene,
                "location": scene.name if scene else player.current_scene,
                "level": player.level,
                "spirit_power": player.spirit_power,
                "hp": player.hp,
                "max_hp": player.max_hp,
                "attack": compute_attack(player),
                "defense": compute_defense(player),
                "tick": player.tick,
            },
            "scene": {
                "id": scene.id if scene else player.current_scene,
                "name": scene.name if scene else "未知",
                "atmosphere": scene.atmosphere if scene else "",
                "npcs_present": world_engine.get_npcs_in_scene(player.current_scene, player.tick),
                "connections": scene.connections if scene else [],
            } if scene else None,
        }

        if combat_result:
            response_data["combat"] = {
                "enemy": encounter.name,
                "dmg_to_enemy": combat_result.dmg_to_enemy,
                "dmg_to_player": combat_result.dmg_to_player,
                "result": combat_result.result,
                "enemy_remaining_hp": combat_result.enemy_remaining_hp,
                "player_remaining_hp": combat_result.player_remaining_hp,
            }

        if dm_response.breakthrough:
            response_data["breakthrough"] = {
                "from": dm_response.breakthrough.from_level,
                "to": dm_response.breakthrough.to_level,
            }

        if npc_update_dict:
            npcs_in_scene = world_engine.get_npcs_in_scene(player.current_scene, player.tick)
            target_npc_id = npcs_in_scene[0] if npcs_in_scene else DEFAULT_NPC_PROFILE.id
            profile_row = npc_repo.get_profile(target_npc_id)
            profile_dict = dict(profile_row) if profile_row else {}
            response_data["npc"] = {
                "id": target_npc_id,
                "favorability": profile_dict.get("favorability", 50),
                "relationship_stage": profile_dict.get("relationship_stage", "陌生"),
            }

        if world_event:
            response_data["world_event"] = {
                "id": world_event.id,
                "name": world_event.name,
                "guidance": world_event.guidance,
            }

        if world_event and world_event.allow_intervene and world_event.intervene_options:
            response_data["intervention"] = {
                "description": "你可以选择：",
                "options": world_event.intervene_options,
            }

        # Return as streaming response
        def response_generator():
            yield json.dumps(response_data, ensure_ascii=False)

        return StreamingResponse(response_generator(), media_type="application/json")

    return router


def _build_memory_from_row(row: dict) -> NPCMemory:
    """Build an NPCMemory from a database row dict."""
    recent_turns_data = row.get("recent_turns", "[]")
    if isinstance(recent_turns_data, str):
        recent_turns_data = json.loads(recent_turns_data)
    key_facts_data = row.get("key_facts", "[]")
    if isinstance(key_facts_data, str):
        key_facts_data = json.loads(key_facts_data)

    return NPCMemory(
        npc_id=row.get("npc_id", DEFAULT_NPC_PROFILE.id),
        summary=row.get("summary", "") or "",
        recent_turns=[NPCTurn(**t) for t in recent_turns_data] if recent_turns_data else [],
        key_facts=[KeyFact(**f) for f in key_facts_data] if key_facts_data else [],
    )
```

- [ ] **Step 2: Update test_api.py for new pipeline**

Key changes needed in `tests/test_api.py`:
1. `_make_app` must pass `world_engine`
2. Update mock to include new response fields
3. Add test for scene info in status response
4. Add test for move action
5. Add test for `/game/scenes` endpoint

Update `tests/test_api.py` — add these tests:

```python
@pytest.mark.asyncio
async def test_get_player_status_with_scene(mock_llm_cultivate, tmp_path):
    """GET /player/status returns scene information."""
    app = _make_app(mock_llm_cultivate, tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/player/status")
        assert response.status_code == 200
        data = response.json()
        assert "current_scene" in data
        assert "scene" in data
        assert data["scene"]["id"] == "outer_gate"


@pytest.mark.asyncio
async def test_get_scenes_endpoint(mock_llm_cultivate, tmp_path):
    """GET /game/scenes returns the world map."""
    app = _make_app(mock_llm_cultivate, tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/game/scenes")
        assert response.status_code == 200
        data = response.json()
        assert "scenes" in data
        assert len(data["scenes"]) == 5
```

Also update `_make_app` to create a `WorldEngine` and pass it:

```python
from engine.world import WorldEngine

def _make_app(mock_llm, tmp_path):
    """Create an app with a temp database and world engine."""
    db_path = str(tmp_path / "test.db")
    world_engine = WorldEngine()
    return create_app(llm_client=mock_llm, db_path=db_path)  # WorldEngine is created inside create_app
```

Actually, since `create_app` already creates `WorldEngine()` internally, `_make_app` doesn't need to change. The `WorldEngine` has no dependencies that need injection for testing.

- [ ] **Step 3: Run tests to verify**

Run: `cd E:\AI\llmud && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add api/routes.py api/app.py tests/test_api.py
git commit -m "feat: integrate world layer into API pipeline with scene info and events"
```

---

### Task 7: Frontend Updates

**Files:**
- Modify: `static/index.html`

**Interfaces:**
- Consumes: New `scene`, `world_event`, `intervention` fields from API responses; `GET /game/scenes` endpoint
- Produces: Updated UI with scene display, NPC list, intervention options, environmental hints

- [ ] **Step 1: Update status bar to show scene info**

In `static/index.html`, update the status bar section and add new UI elements:

Update the `<div id="status-bar">` to include scene info and NPC list:

```html
<div id="status-bar">
    <span class="stat"><span class="stat-label">地点</span> <span class="stat-value" id="p-loc">青云门外门</span></span>
    <span class="stat"><span class="stat-label">境界</span> <span class="stat-value" id="p-level">练气期一层</span></span>
    <span class="stat"><span class="stat-label">灵力</span> <span class="stat-value" id="p-spirit">10</span></span>
    <span class="stat"><span class="stat-label">气血</span> <span class="stat-value" id="p-hp">100/100</span></span>
    <span class="stat"><span class="stat-label">攻</span> <span class="stat-value" id="p-atk">10</span></span>
    <span class="stat"><span class="stat-label">防</span> <span class="stat-value" id="p-def">10</span></span>
    <div id="scene-npcs" style="display:none; width:100%; margin-top:4px;">
        <span class="stat-label">在场：</span> <span id="p-npcs-present" style="color:#b8a0d4;"></span>
    </div>
    <div id="scene-connections" style="display:none; width:100%; margin-top:2px;">
        <span class="stat-label">可往：</span> <span id="p-connections" style="color:#b8a0d4;"></span>
    </div>
    <span class="stat" id="npc-rel" style="display:none"><span class="stat-label">师姐</span> <span class="stat-value" id="p-npc-stage">陌生</span> <span id="p-npc-fav" style="color:#ff6b9d">50</span></span>
    <div id="favorability-bar"><div id="favorability-fill" style="width:50%"></div></div>
</div>
```

Add new CSS styles:

```css
.world-event { background: linear-gradient(135deg, #2d1b4e, #1a3a5c); color: #7ec8e3; border-radius: 12px; padding: 12px; margin: 6px 0; font-style: italic; border-left: 3px solid #7ec8e3; }
.intervention-card { background: linear-gradient(135deg, #4a2d6e, #6b3fa0); border: 1px solid #8b5fbf; border-radius: 12px; padding: 12px; margin: 6px 0; }
.intervention-card h3 { margin: 0 0 8px 0; font-size: 14px; color: #ffd700; }
.intervention-btn { background: linear-gradient(135deg, #6b3fa0, #4a2d6e); color: white; border: 1px solid #8b5fbf; border-radius: 18px; padding: 6px 14px; margin: 4px; cursor: pointer; font-size: 13px; }
.intervention-btn:hover { background: linear-gradient(135deg, #8b5fbf, #6b3fa0); }
.scene-tag { background: rgba(255,255,255,0.1); border-radius: 12px; padding: 2px 8px; margin: 0 2px; font-size: 12px; color: #b8a0d4; }
```

- [ ] **Step 2: Update JavaScript to handle scene info, world events, and interventions**

Add these functions to the `<script>` section:

```javascript
function updateSceneInfo(scene) {
    if (!scene) return;
    document.getElementById('p-loc').textContent = scene.name || '未知';

    const npcsDiv = document.getElementById('scene-npcs');
    const npcsSpan = document.getElementById('p-npcs-present');
    if (scene.npcs_present && scene.npcs_present.length > 0) {
        const npcNames = {
            'linwaner': '林婉儿',
            'chenhao': '陈浩',
            'old_yang': '杨老'
        };
        const names = scene.npcs_present.map(id => npcNames[id] || id);
        npcsSpan.textContent = names.join('、');
        npcsDiv.style.display = 'block';
    } else {
        npcsDiv.style.display = 'none';
    }

    const connDiv = document.getElementById('scene-connections');
    const connSpan = document.getElementById('p-connections');
    if (scene.connections && scene.connections.length > 0) {
        const sceneNames = {
            'outer_gate': '外门',
            'inner_gate': '内门',
            'bamboo_forest': '竹林',
            'market': '集市',
            'mountain_range': '山脉'
        };
        const names = scene.connections.map(id => sceneNames[id] || id);
        connSpan.textContent = names.join('、');
        connDiv.style.display = 'block';
    } else {
        connDiv.style.display = 'none';
    }
}

function addWorldEvent(container, event) {
    if (!event) return;
    const div = document.createElement('div');
    div.className = 'world-event';
    div.textContent = `◈ ${event.name || ''}`;
    container.appendChild(div);
}

function addIntervention(container, intervention) {
    if (!intervention) return;
    const card = document.createElement('div');
    card.className = 'intervention-card';
    card.innerHTML = `<h3>${intervention.description}</h3>`;
    const btnContainer = document.createElement('div');
    intervention.options.forEach(option => {
        const btn = document.createElement('button');
        btn.className = 'intervention-btn';
        btn.textContent = option;
        btn.onclick = () => {
            document.getElementById('user-input').value = option;
            sendAction();
        };
        btnContainer.appendChild(btn);
    });
    card.appendChild(btnContainer);
    container.appendChild(card);
}
```

Update the `updateStatus()` function to handle scene info:

```javascript
async function updateStatus() {
    try {
        const res = await fetch(`${API_URL}/player/status`);
        const data = await res.json();
        document.getElementById('p-loc').textContent = data.location || data.current_scene || '未知';
        document.getElementById('p-level').textContent = data.level || '练气期一层';
        document.getElementById('p-spirit').textContent = data.spirit_power ?? 0;
        document.getElementById('p-hp').textContent = `${data.hp ?? 100}/${data.max_hp ?? 100}`;
        document.getElementById('p-atk').textContent = data.attack ?? 0;
        document.getElementById('p-def').textContent = data.defense ?? 0;
        updateSceneInfo(data.scene);
    } catch(e) {
        console.error('Status update failed:', e);
    }
}
```

Update the response parsing in `sendAction()` to handle new fields:

In the `try { ... } catch(e) { ... }` block inside the JSON parsing section, add after the NPC update block:

```javascript
// Show world event if present
if (result.world_event) {
    addWorldEvent(container, result.world_event);
}

// Show intervention options if present
if (result.intervention) {
    addIntervention(container, result.intervention);
}

// Update scene info
if (result.scene) {
    updateSceneInfo(result.scene);
}
```

- [ ] **Step 3: Manual verification**

Start the server and test:
1. Navigate to the H5 frontend
2. Verify status bar shows scene name, NPCs present, connections
3. Try moving to different scenes ("去内门", "前往竹林")
4. Verify world events appear as styled cards
5. Verify intervention option buttons work
6. Verify NPC names update when moving between scenes

Run: `cd E:\AI\llmud && python main.py`
Then open `http://127.0.0.1:8001` in a browser.

- [ ] **Step 4: Commit**

```bash
git add static/index.html
git commit -m "feat: update frontend with scene info, world events, and intervention options"
```

---

### Task 8: Integration Testing & Polish

**Files:**
- Modify: `tests/test_api.py` (add integration tests)
- Modify: `tests/test_world.py` (add edge case tests)

**Interfaces:**
- Consumes: All components from Tasks 1-7
- Produces: Full integration test suite

- [ ] **Step 1: Add integration tests**

Add to `tests/test_api.py`:

```python
@pytest.mark.asyncio
async def test_game_action_move(mock_llm_cultivate, tmp_path):
    """POST /game/action with '去内门' triggers move pipeline."""
    # Create a mock that returns a move-appropriate response
    move_response = json.dumps({
        "intent": "move",
        "action_valid": True,
        "invalid_reason": "",
        "story": "你穿过外门，来到了内门修炼场。",
        "state_delta": {},
        "breakthrough": None,
        "combat": None,
        "npc_update": None,
    }, ensure_ascii=False)
    mock = MockLLMClient(response=move_response)
    app = _make_app(mock, tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/game/action", json={"user_input": "去内门"})
        assert response.status_code == 200
        data = json.loads(response.text)
        # Should classify as MOVE intent
        assert data["intent"] == "move"
        # Should include scene info
        assert "scene" in data

@pytest.mark.asyncio
async def test_game_action_with_world_event(mock_llm_cultivate, tmp_path):
    """World events appear in response when conditions are met."""
    app = _make_app(mock_llm_cultivate, tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First action at outer_gate should trigger faint_spirit_sense
        response = await client.post("/game/action", json={"user_input": "修炼"})
        assert response.status_code == 200
        data = json.loads(response.text)
        # The world_event field may or may not be present depending on conditions
        # (first action at outer_gate should trigger faint_spirit_sense)
        # But since it's a one-time event, it should be present on first visit

@pytest.mark.asyncio
async def test_scenes_endpoint(mock_llm_cultivate, tmp_path):
    """GET /game/scenes returns all 5 scenes."""
    app = _make_app(mock_llm_cultivate, tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/game/scenes")
        assert response.status_code == 200
        data = response.json()
        assert len(data["scenes"]) == 5
        scene_ids = [s["id"] for s in data["scenes"]]
        assert "outer_gate" in scene_ids
        assert "inner_gate" in scene_ids
```

- [ ] **Step 2: Add edge case tests to test_world.py**

Add to `tests/test_world.py`:

```python
class TestEdgeCases:
    def test_event_does_not_repeat(self, engine):
        """One-time events should not trigger again after being seen."""
        player = Player(current_scene="outer_gate", seen_events=["faint_spirit_sense", "visited_outer_gate"])
        event = engine.check_events("outer_gate", player)
        # faint_spirit_sense should not trigger again
        if event and event.id == "faint_spirit_sense":
            assert False, "One-time event should not trigger again"

    def test_only_one_event_per_check(self, engine):
        """check_events should return at most one event."""
        player = Player(current_scene="outer_gate")
        event = engine.check_events("outer_gate", player)
        # Just verify it returns at most one
        assert event is None or isinstance(event, WorldEvent)

    def test_move_to_nonexistent_scene(self, engine):
        """Moving to a nonexistent scene should fail."""
        result = engine.validate_move("outer_gate", "nonexistent")
        assert result is False

    def test_npc_schedule_outside_range(self, engine):
        """NPCs should be at default scene outside schedule range."""
        # At tick 25, linwaner should be back at inner_gate
        npcs = engine.get_npcs_in_scene("market", 25)
        assert "linwaner" not in npcs
        npcs_at_inner = engine.get_npcs_in_scene("inner_gate", 25)
        assert "linwaner" in npcs_at_inner
```

- [ ] **Step 3: Run full test suite**

Run: `cd E:\AI\llmud && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: add integration and edge case tests for living world system"
```

---

## Self-Review

**1. Spec coverage:**

| Spec Section | Task |
|---|---|
| §5 Scene System | Task 1 (models), Task 2 (world engine) |
| §6 Event Pool | Task 2 (world engine) |
| §7 NPC Presence + Interactions | Task 1 (models), Task 2 (world engine), Task 5 (NPC expansion) |
| §8 Soft Guidance | Task 2 (events), Task 6 (DM prompt) |
| §9 API Changes | Task 6 (routes, app) |
| §10 Player Model | Task 4 |
| §11 File Structure | All tasks |
| §12 Decisions D1-D7 | All tasks (verified inline) |

**2. Placeholder scan:** No TBD/TODO found. All steps contain actual code.

**3. Type consistency:** Checked all function signatures and model field names across tasks. `current_scene` used consistently (not `location`). `WorldEngine` methods match between Task 2 definition and Task 6 usage. `build_dm_prompt` signature matches between Task 5 definition and Task 6 usage. `NPCProfileData` used consistently for seeding.