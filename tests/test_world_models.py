import pytest
from engine.models import (
    Scene, EventTrigger, WorldEvent, NPCPresence, SceneSchedule,
    NPCInteraction, WorldState, Player, Intent, ENCOUNTERS_BY_SCENE,
    SCENE_MAP, ALL_EVENTS, NPC_PRESENCES, NPC_INTERACTIONS,
    NPCRuntimeState, TensionRuntime, WorldBible, FactionSpec, ItemSpec,
    SkillSpec, TensionSpec, TensionTrigger, BehaviorModel,
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
        assert len(SCENE_MAP) == 6
        assert "outer_gate" in SCENE_MAP
        assert "inner_gate" in SCENE_MAP
        assert "bamboo_forest" in SCENE_MAP
        assert "market" in SCENE_MAP
        assert "mountain_range" in SCENE_MAP
        assert "spirit_valley" in SCENE_MAP

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
        assert state.tick == 0
        assert state.npc_state == {}

    def test_intervene_intent_exists(self):
        assert Intent.INTERVENE.value == "intervene"


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