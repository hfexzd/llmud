import json
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
        resolved = resolve_scene_id(action_text)
        params["destination"] = resolved or action_text
        # Flag whether a concrete scene was parsed — when False, the api layer
        # asks the LLM to disambiguate an elliptical move (e.g. "好啊，去走走").
        params["destination_resolved"] = resolved is not None
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


_INTENT_NAME_TO_ENUM = {
    "cultivate": Intent.CULTIVATE,
    "fight": Intent.FIGHT,
    "move": Intent.MOVE,
    "talk": Intent.TALK,
    "intervene": Intent.INTERVENE,
    "other": Intent.OTHER,
}


def _extract_json_object(text: str) -> dict | None:
    """Best-effort JSON object extraction, tolerant of code fences and prose."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(s[start : end + 1])
    except Exception:
        return None


async def classify_intent_llm(
    action_text: str,
    llm_client,
    scene_name: str,
    candidate_destinations: list[str],
    recent_stories: list[str],
) -> tuple[Intent | None, dict]:
    """LLM fallback for ambiguous / elliptical input.

    Used when the regex fast-path is uncertain — a move verb with no resolvable
    destination (e.g. "好啊，去走走"承接林婉儿的邀请→竹林), or no pattern at all
    (e.g. "好啊", "走吧"). The LLM sees the recent conversation plus the places
    the player can actually reach, so it can infer an implied destination.

    The engine still validates reachability afterwards, so the LLM cannot
    teleport the player to an unreachable scene.

    Returns (Intent, params) on success, or (None, {}) when there is no client,
    the LLM call fails, or the response cannot be parsed.
    """
    if llm_client is None:
        return None, {}

    candidates = "、".join(candidate_destinations) if candidate_destinations else "（四周无路）"
    stories = "\n".join(f"- {s}" for s in (recent_stories or [])[-5:]) or "（无）"

    system = (
        "你是修仙 MUD 的意图分类器。根据玩家这句话和最近对话上下文，判断玩家意图。\n"
        "可选意图：cultivate（修炼/打坐/练功）、fight（战斗/攻击/杀敌）、"
        "move（前往某地）、talk（与在场的人说话）、intervene（介入他人的互动）、"
        "other（其余自由行动）。\n"
        f"玩家当前所在场景：{scene_name}。\n"
        f"玩家可前往的目的地：{candidates}。\n"
        "若玩家是承接上文邀请或提议而省略了地点（如「好啊」「走吧」「去走走」"
        "「那就去吧」），请结合最近对话推断其真正想去的目的地。\n"
        "只输出严格 JSON，不要任何额外文字或 markdown 标记：\n"
        '{"intent": "意图名", "destination": "若为move则填目的地'
        '（优先从可前往目的地中选一个，或填场景内地标），否则填空字符串"}'
    )
    user = f"最近对话：\n{stories}\n\n玩家输入：{action_text}"

    try:
        raw = await llm_client.generate(system, user)
    except Exception:
        return None, {}

    data = _extract_json_object(raw)
    if not data:
        return None, {}

    intent_name = str(data.get("intent", "")).strip().lower()
    intent = _INTENT_NAME_TO_ENUM.get(intent_name)
    if intent is None:
        return None, {}

    params: dict = {}
    dest = str(data.get("destination", "") or "").strip()
    if dest:
        params["destination"] = dest
    return intent, params