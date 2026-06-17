from engine.models import Intent
from engine.classify import classify_intent


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