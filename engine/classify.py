import re
from engine.models import Intent, resolve_scene_id

# Regex patterns for fast-path classification
CULTIVATE_PATTERNS = [
    r"修炼", r"打坐", r"练功", r"冥想", r"吐纳", r"练气",
    r"吸收灵气", r"凝聚灵力", r"运功",
]

TALK_PATTERNS = [
    r"师姐", r"和.+说话", r"跟.+聊", r"对.+说", r"告诉",
    r"问.{0,2}(题|好|话|事|人)", r"问问", r"聊聊", r"搭话",
]

FIGHT_PATTERNS = [
    r"攻击", r"打", r"砍", r"杀", r"战斗", r"挑战",
    r"斩", r"击杀", r"消灭", r"对决",
]

INTERVENE_PATTERNS = [
    r"上前搭话", r"加入对话", r"介入", r"插嘴", r"打断",
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

    # Fast-path: regex matching (INTERVENE before MOVE — intervention verbs
    # like "上前搭话" should take priority over MOVE; MOVE before CULTIVATE
    # because "前往" should not alias to "练功房" cultivate)
    if _match_patterns(action_text, INTERVENE_PATTERNS):
        return Intent.INTERVENE, params

    if _match_patterns(action_text, MOVE_PATTERNS):
        # Extract a concrete target scene when the text names one (e.g.
        # "去内门灵泉旁修炼" → "inner_gate"); fall back to the raw text so the
        # world layer can still attempt alias matching or report an error.
        params["destination"] = resolve_scene_id(action_text) or action_text
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