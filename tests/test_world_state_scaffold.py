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

    def test_tensions_populated_in_m2(self):
        # Phase-0 tensions arrived in M2 Task 1 (4 hand-authored entries).
        ids = [t.id for t in PHASE_0_BIBLE.tensions]
        assert ids == [
            "venture_bamboo", "probe_anomaly",
            "cultivate_breakthrough", "venture_mountain",
        ]


from engine.models import WorldState, PHASE_0_BIBLE, Player
from engine.world import npc_step


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


from engine.models import NPCRuntimeState, TensionRuntime
from db.repository import WorldRepository

import json
import pytest
from httpx import AsyncClient, ASGITransport
from api.app import create_app
from dm.client import MockLLMClient


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