import json
from dm.contract import parse_dm_response
from engine.models import Intent


def test_parse_valid_response():
    raw = json.dumps({
        "intent": "cultivate",
        "action_valid": True,
        "invalid_reason": "",
        "story": "你盘膝而坐，灵气如溪流般汇入丹田。",
        "state_delta": {"spirit_power": 2},
        "breakthrough": None,
        "combat": None,
        "npc_update": None,
    })
    result = parse_dm_response(raw)
    assert result.intent == Intent.CULTIVATE
    assert result.action_valid is True
    assert result.story == "你盘膝而坐，灵气如溪流般汇入丹田。"
    assert result.state_delta == {"spirit_power": 2}


def test_parse_response_with_combat():
    raw = json.dumps({
        "intent": "fight",
        "action_valid": True,
        "invalid_reason": "",
        "story": "你一剑斩出，赤眼妖狼惨嚎倒地！",
        "state_delta": {"hp": -5},
        "breakthrough": None,
        "combat": {
            "enemy": "赤眼妖狼",
            "dmg_to_enemy": 47,
            "dmg_to_player": 3,
            "result": "win"
        },
        "npc_update": None,
    })
    result = parse_dm_response(raw)
    assert result.intent == Intent.FIGHT
    assert result.combat is not None
    assert result.combat.result == "win"


def test_parse_response_with_breakthrough():
    raw = json.dumps({
        "intent": "cultivate",
        "action_valid": True,
        "invalid_reason": "",
        "story": "灵力突破瓶颈，你踏入了练气期二层！",
        "state_delta": {},
        "breakthrough": {"from": "练气期一层", "to": "练气期二层"},
        "combat": None,
        "npc_update": None,
    })
    result = parse_dm_response(raw)
    assert result.breakthrough is not None
    assert result.breakthrough.from_level == "练气期一层"


def test_parse_response_with_npc_update():
    raw = json.dumps({
        "intent": "talk",
        "action_valid": True,
        "invalid_reason": "",
        "story": "师姐微微一笑，轻轻点了点头。",
        "state_delta": {},
        "breakthrough": None,
        "combat": None,
        "npc_update": {
            "emotion": "微笑",
            "favorability_change": 3,
            "new_key_fact": "玩家提到想变强保护师姐",
            "summary_delta": "玩家表达了保护师姐的意愿"
        },
    })
    result = parse_dm_response(raw)
    assert result.npc_update is not None
    assert result.npc_update["favorability_change"] == 3


def test_parse_invalid_json_returns_other():
    raw = "This is not JSON at all, just narrative text."
    result = parse_dm_response(raw)
    assert result.intent == Intent.OTHER
    assert result.action_valid is False
    assert result.story == raw  # Fallback: show raw text


def test_parse_json_with_markdown_fences():
    """DM sometimes wraps JSON in ```json...``` — strip it."""
    inner = {
        "intent": "move",
        "action_valid": True,
        "invalid_reason": "",
        "story": "你来到了后山。",
        "state_delta": {"location": "后山"},
        "breakthrough": None,
        "combat": None,
        "npc_update": None,
    }
    raw = f"```json\n{json.dumps(inner)}\n```"
    result = parse_dm_response(raw)
    assert result.intent == Intent.MOVE