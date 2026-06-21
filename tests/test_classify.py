import json

import pytest

from engine.models import Intent
from engine.classify import classify_intent, classify_intent_llm


def test_classify_cultivate():
    intent, params = classify_intent("修炼")
    assert intent == Intent.CULTIVATE

def test_classify_cultivate_variant():
    intent, params = classify_intent("我要打坐修炼灵力")
    assert intent == Intent.CULTIVATE

def test_classify_talk():
    intent, params = classify_intent("和师姐说话")
    assert intent == Intent.TALK

def test_classify_talk_variant():
    intent, params = classify_intent("师姐，你好啊")
    assert intent == Intent.TALK

def test_classify_fight():
    intent, params = classify_intent("攻击妖兽")
    assert intent == Intent.FIGHT

def test_classify_fight_variant():
    intent, params = classify_intent("砍那只野狼")
    assert intent == Intent.FIGHT

def test_classify_move():
    intent, params = classify_intent("去后山")
    assert intent == Intent.MOVE

def test_classify_move_variant():
    intent, params = classify_intent("前往练功房")
    assert intent == Intent.MOVE

def test_classify_other_no_llm():
    """Without LLM client, unrecognized input defaults to OTHER."""
    intent, params = classify_intent("我想看月亮")
    assert intent == Intent.OTHER


def test_classify_intervene():
    intent, params = classify_intent("上前搭话")
    assert intent == Intent.INTERVENE

    intent, params = classify_intent("介入对话")
    assert intent == Intent.INTERVENE


class _StubClient:
    """Minimal async LLM client stub returning a preset response."""

    def __init__(self, response: str):
        self.response = response
        self.last_system = ""

    async def generate(self, system_prompt: str, user_message: str) -> str:
        self.last_system = system_prompt
        return self.response


def test_classify_move_flags_unresolved_destination():
    """A move verb with no parseable scene must flag destination_resolved=False
    so the api layer knows to ask the LLM to disambiguate."""
    intent, params = classify_intent("好啊，去走走")
    assert intent == Intent.MOVE
    assert params["destination_resolved"] is False
    assert params["destination"] == "好啊，去走走"


def test_classify_move_flags_resolved_destination():
    intent, params = classify_intent("去内门灵泉旁修炼")
    assert intent == Intent.MOVE
    assert params["destination_resolved"] is True
    assert params["destination"] == "inner_gate"


@pytest.mark.asyncio
async def test_classify_llm_resolves_anaphora_move():
    """'好啊，去走走' alone resolves to no destination, but given 婉儿's
    invitation in recent context the LLM infers the move target."""
    resp = json.dumps({"intent": "move", "destination": "竹林"}, ensure_ascii=False)
    client = _StubClient(resp)
    intent, params = await classify_intent_llm(
        "好啊，去走走", client, "青云门内门",
        ["青云门外门", "幽竹林", "祭坛", "灵泉"],
        ["林婉儿轻声道：「你可愿陪我去竹林走走？」"],
    )
    assert intent == Intent.MOVE
    assert params["destination"] == "竹林"


@pytest.mark.asyncio
async def test_classify_llm_returns_none_without_client():
    intent, params = await classify_intent_llm("好啊", None, "内门", [], [])
    assert intent is None
    assert params == {}


@pytest.mark.asyncio
async def test_classify_llm_returns_none_on_unparseable():
    client = _StubClient("这不是JSON")
    intent, params = await classify_intent_llm("好啊", client, "内门", [], [])
    assert intent is None
    assert params == {}


@pytest.mark.asyncio
async def test_classify_llm_returns_none_on_unknown_intent_name():
    client = _StubClient(json.dumps({"intent": "fly", "destination": ""}))
    intent, params = await classify_intent_llm("飞", client, "内门", [], [])
    assert intent is None


def test_resolve_npc_target_matches_name_in_text():
    from engine.classify import resolve_npc_target
    names = {"linwaner": "林婉儿", "chenhao": "陈浩"}
    assert resolve_npc_target("对林婉儿说：最近可好", names) == "linwaner"


def test_resolve_npc_target_no_match_returns_none():
    from engine.classify import resolve_npc_target
    names = {"linwaner": "林婉儿", "chenhao": "陈浩"}
    assert resolve_npc_target("随便聊聊", names) is None


def test_resolve_npc_target_empty_names_returns_none():
    from engine.classify import resolve_npc_target
    assert resolve_npc_target("对林婉儿说", {}) is None


def test_resolve_npc_target_first_match_wins_on_ambiguous():
    """If text mentions two NPCs, the first by dict order wins (stable)."""
    from engine.classify import resolve_npc_target
    names = {"linwaner": "林婉儿", "chenhao": "陈浩"}
    # Both names present; dict insertion order -> linwaner first
    assert resolve_npc_target("林婉儿和陈浩都在", names) == "linwaner"