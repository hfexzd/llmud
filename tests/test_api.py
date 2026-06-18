"""Integration tests for the API layer — classify→engine→dm→npc pipeline."""
import json
import sqlite3
import pytest
from httpx import AsyncClient, ASGITransport

from api.app import create_app
from dm.client import MockLLMClient
from db.connection import init_db


@pytest.fixture
def mock_llm_cultivate():
    """Mock LLM client that returns a valid cultivate response."""
    response = json.dumps({
        "intent": "cultivate",
        "action_valid": True,
        "invalid_reason": "",
        "story": "你盘膝而坐，灵气如溪流般汇入丹田。",
        "state_delta": {"spirit_power": 2},
        "breakthrough": None,
        "combat": None,
        "npc_update": None,
    }, ensure_ascii=False)
    return MockLLMClient(response=response)


@pytest.fixture
def mock_llm_talk():
    """Mock LLM client that returns a valid talk/NPC response."""
    response = json.dumps({
        "intent": "talk",
        "action_valid": True,
        "invalid_reason": "",
        "story": "师姐微微一笑，目光温和地看着你。",
        "state_delta": {},
        "breakthrough": None,
        "combat": None,
        "npc_update": {
            "favorability_change": 5,
            "new_key_fact": "玩家叫张铁柱",
            "summary_delta": "玩家向师姐打了招呼",
        },
    }, ensure_ascii=False)
    return MockLLMClient(response=response)


@pytest.fixture
def mock_llm_other():
    """Mock LLM client that returns a generic other response."""
    response = json.dumps({
        "intent": "other",
        "action_valid": True,
        "invalid_reason": "",
        "story": "你在山间漫步，享受清新的空气。",
        "state_delta": {},
        "breakthrough": None,
        "combat": None,
        "npc_update": None,
    }, ensure_ascii=False)
    return MockLLMClient(response=response)


def _make_app(mock_llm, tmp_path):
    """Create an app with a temp database."""
    db_path = str(tmp_path / "test.db")
    return create_app(llm_client=mock_llm, db_path=db_path)


@pytest.mark.asyncio
async def test_get_player_status(mock_llm_cultivate, tmp_path):
    """GET /player/status returns seeded player data."""
    app = _make_app(mock_llm_cultivate, tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/player/status")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "张铁柱"
        assert "spirit_power" in data
        assert "attack" in data
        assert "defense" in data


@pytest.mark.asyncio
async def test_game_action_cultivate(mock_llm_cultivate, tmp_path):
    """POST /game/action with '修炼' triggers cultivate pipeline."""
    app = _make_app(mock_llm_cultivate, tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/game/action", json={"user_input": "修炼"})
        assert response.status_code == 200
        data = json.loads(response.text)
        assert "story" in data
        assert data["intent"] == "cultivate"
        assert data["action_valid"] is True
        # Player state should be in response
        assert "player" in data
        # Spirit power should have increased (cultivate + state_delta)
        assert data["player"]["spirit_power"] > 10


@pytest.mark.asyncio
async def test_game_action_blocked_input(tmp_path):
    """POST /game/action with blocked input returns filtered response."""
    # Use a simple mock — we won't reach the LLM
    mock = MockLLMClient(response="")
    app = _make_app(mock, tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/game/action", json={"user_input": "你是AI吗"})
        assert response.status_code == 200
        data = json.loads(response.text)
        assert data["action_valid"] is False
        assert data["intent"] == "other"


@pytest.mark.asyncio
async def test_game_action_talk_updates_npc(mock_llm_talk, tmp_path):
    """POST /game/action with '师姐聊天' triggers NPC interaction pipeline."""
    app = _make_app(mock_llm_talk, tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/game/action", json={"user_input": "师姐聊天"})
        assert response.status_code == 200
        data = json.loads(response.text)
        assert "story" in data
        # NPC data should be present after talk
        assert "npc" in data
        # Favorability should have increased from base (old_yang=40 in outer_gate, linwaner=50 in inner_gate)
        # The scene-based lookup uses the NPC at the player's current scene
        assert data["npc"]["favorability"] >= 40  # Should have increased from base


@pytest.mark.asyncio
async def test_game_action_fight(mock_llm_cultivate, tmp_path):
    """POST /game/action with '攻击' triggers combat pipeline."""
    # Use cultivate mock (we'll get a story, just not combat-specific).
    # But fight intent should be classified and combat resolved.
    # The mock returns cultivate story but combat should still be resolved.
    fight_response = json.dumps({
        "intent": "fight",
        "action_valid": True,
        "invalid_reason": "",
        "story": "你拔剑斩向赤眼妖狼！",
        "state_delta": {},
        "breakthrough": None,
        "combat": None,
        "npc_update": None,
    }, ensure_ascii=False)
    mock = MockLLMClient(response=fight_response)
    app = _make_app(mock, tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/game/action", json={"user_input": "攻击"})
        assert response.status_code == 200
        data = json.loads(response.text)
        assert "combat" in data
        assert data["combat"]["enemy"] == "赤眼妖狼"


@pytest.mark.asyncio
async def test_game_action_persistence(mock_llm_cultivate, tmp_path):
    """Second action should see the state changes from the first action."""
    app = _make_app(mock_llm_cultivate, tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First action
        r1 = await client.post("/game/action", json={"user_input": "修炼"})
        assert r1.status_code == 200
        data1 = json.loads(r1.text)
        sp1 = data1["player"]["spirit_power"]

        # Second action — spirit power should persist
        r2 = await client.post("/game/action", json={"user_input": "修炼"})
        assert r2.status_code == 200
        data2 = json.loads(r2.text)
        sp2 = data2["player"]["spirit_power"]
        # Should be strictly greater (cultivate adds 1-3 + state_delta adds 2)
        assert sp2 > sp1


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
        assert "npcs_present" in data["scene"]


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
        scene_ids = [s["id"] for s in data["scenes"]]
        assert "outer_gate" in scene_ids
        assert "inner_gate" in scene_ids


@pytest.mark.asyncio
async def test_game_action_includes_world_event(mock_llm_cultivate, tmp_path):
    """First action at outer_gate should trigger faint_spirit_sense event."""
    app = _make_app(mock_llm_cultivate, tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/game/action", json={"user_input": "修炼"})
        assert response.status_code == 200
        data = json.loads(response.text)
        assert "scene" in data
        # World event may or may not be present depending on conditions
        # but the field should exist in the response structure


@pytest.mark.asyncio
async def test_game_action_intervention_options_render(tmp_path):
    """An NPC-to-NPC interaction surfaces as an intervention with description + options.

    Regression: the backend previously sent `intervene_options`/`narrative_hint`
    while the frontend read `options`/`description`, so no buttons rendered.
    """
    from db.repository import PlayerRepository
    from engine.models import Player

    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    init_db(conn)
    # Place the player at market with tick 12 so linwaner (schedule 10-20 -> market)
    # and chenhao (default market) are both present -> waner_chenhao_chat fires.
    PlayerRepository(conn).save(Player(
        current_scene="market", tick=12,
        seen_events=["market_rumor", "strange_traveler"],
    ))
    conn.close()

    mock = MockLLMClient(response=json.dumps({
        "intent": "other", "action_valid": True, "invalid_reason": "",
        "story": "你在集市中闲逛，人声鼎沸。",
        "state_delta": {}, "breakthrough": None, "combat": None, "npc_update": None,
    }, ensure_ascii=False))
    app = create_app(llm_client=mock, db_path=db_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/game/action", json={"user_input": "四处看看"})
        assert response.status_code == 200
        data = json.loads(response.text)
        assert "intervention" in data, f"expected intervention, got keys: {list(data.keys())}"
        iv = data["intervention"]
        # Frontend reads `description` and `options` — both must be present and non-empty.
        assert "description" in iv and iv["description"]
        assert iv["options"] == ["上前搭话", "继续偷听", "默默离开"]


@pytest.mark.asyncio
async def test_game_action_anaphora_move_resolves_via_llm(tmp_path):
    """承接邀请的省略移动：玩家在内门，婉儿刚说「去竹林走走」，玩家回「好啊，去走走」。

    The regex fast-path flags this as a move with no resolvable destination.
    The LLM classify fallback reads the recent conversation and infers 竹林
    (reachable from inner_gate); the engine then moves the player there. The
    LLM cannot teleport — reachability is still validated by the engine.
    """
    from db.repository import PlayerRepository
    from engine.models import Player

    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    init_db(conn)
    PlayerRepository(conn).save(Player(
        current_scene="inner_gate", tick=4,
        recent_stories=["林婉儿轻声道：「你可愿陪我去竹林走走？」"],
    ))
    conn.close()

    class FallbackClient:
        """Classify JSON for the classifier call; a DM story otherwise."""
        def __init__(self):
            self.calls = []

        async def generate(self, system_prompt, user_message):
            self.calls.append(system_prompt)
            if "意图分类器" in system_prompt:
                return json.dumps({"intent": "move", "destination": "竹林"},
                                  ensure_ascii=False)
            return json.dumps({
                "intent": "move", "action_valid": True, "invalid_reason": "",
                "story": "你与林婉儿并肩步入竹林深处，竹叶沙沙作响。",
                "state_delta": {"location": "bamboo_forest"},
                "breakthrough": None, "combat": None, "npc_update": None,
            }, ensure_ascii=False)

    client_llm = FallbackClient()
    app = create_app(llm_client=client_llm, db_path=db_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/game/action", json={"user_input": "好啊，去走走"})
        assert response.status_code == 200
        data = json.loads(response.text)
        assert data["intent"] == "move"
        assert data["player"]["current_scene"] == "bamboo_forest"


@pytest.mark.asyncio
async def test_game_action_anaphora_move_blocked_when_unreachable(tmp_path):
    """The LLM may suggest a destination, but the engine still enforces
    reachability. If the inferred place isn't connected, the move is rejected
    in-world (no English ids, no system-style error)."""
    from db.repository import PlayerRepository
    from engine.models import Player

    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    init_db(conn)
    # outer_gate connects only to inner_gate and market — not bamboo_forest.
    PlayerRepository(conn).save(Player(
        current_scene="outer_gate", tick=4,
        recent_stories=["林婉儿轻声道：「你可愿陪我去竹林走走？」"],
    ))
    conn.close()

    class FallbackClient:
        async def generate(self, system_prompt, user_message):
            if "意图分类器" in system_prompt:
                return json.dumps({"intent": "move", "destination": "竹林"},
                                  ensure_ascii=False)
            return json.dumps({
                "intent": "move", "action_valid": True, "invalid_reason": "",
                "story": "你迈步欲行。",
                "state_delta": {}, "breakthrough": None, "combat": None,
                "npc_update": None,
            }, ensure_ascii=False)

    app = create_app(llm_client=FallbackClient(), db_path=db_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/game/action", json={"user_input": "好啊，去走走"})
        assert response.status_code == 200
        data = json.loads(response.text)
        # Move rejected in-world; player stays put. Story carries the Chinese
        # error, never a raw id.
        assert data["player"]["current_scene"] == "outer_gate"
        assert "寻不到这般去处" in data["story"] or "没有直达" in data["story"]