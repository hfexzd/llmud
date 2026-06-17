import re
from engine.models import Intent

# Regex patterns for fast-path classification
CULTIVATE_PATTERNS = [
    r"修炼", r"打坐", r"练功", r"冥想", r"吐纳", r"练气",
    r"吸收灵气", r"凝聚灵力", r"运功",
]

TALK_PATTERNS = [
    r"师姐", r"和.+说话", r"跟.+聊", r"对.+说", r"告诉",
    r"问", r"聊聊", r"搭话",
]

FIGHT_PATTERNS = [
    r"攻击", r"打", r"砍", r"杀", r"战斗", r"挑战",
    r"斩", r"击杀", r"消灭", r"对决",
]

MOVE_PATTERNS = [
    r"去", r"前往", r"到", r"来到", r"走到", r"移动到",
    r"进入", r"离开", r"回",
]


def _match_patterns(text: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if re.search(pattern, text):
            return True
    return False


def classify_intent(action_text: str, llm_client=None) -> tuple[Intent, dict]:
    """
    Classify player action into an intent using regex fast-path first.
    Falls back to LLM classification if no pattern matches and a client is provided.
    Returns (Intent, parsed_params) where parsed_params carries extra info.
    """
    params = {}

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