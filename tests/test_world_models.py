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