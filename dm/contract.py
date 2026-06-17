import json
import re
from engine.models import DMResponse, Intent, BreakthroughResult, CombatResult


def parse_dm_response(raw_text: str) -> DMResponse:
    """
    Parse the DM's raw LLM output into a structured DMResponse.
    Handles: markdown fences, malformed JSON, missing fields.
    Returns a fallback DMResponse with intent=OTHER if parsing fails.
    """
    # Strip markdown code fences if present
    cleaned = raw_text.strip()
    fence_match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?\s*```$", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # Try to extract JSON from text
    json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not json_match:
        return DMResponse(
            intent=Intent.OTHER,
            action_valid=False,
            invalid_reason="无法解析模型输出",
            story=raw_text,
        )

    json_str = json_match.group(0)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return DMResponse(
            intent=Intent.OTHER,
            action_valid=False,
            invalid_reason="JSON解析失败",
            story=raw_text,
        )

    # Parse intent
    try:
        intent = Intent(data.get("intent", "other"))
    except ValueError:
        intent = Intent.OTHER

    # Parse breakthrough
    breakthrough = None
    if data.get("breakthrough"):
        bt = data["breakthrough"]
        breakthrough = BreakthroughResult(
            from_level=bt.get("from", ""),
            to_level=bt.get("to", ""),
        )

    # Parse combat
    combat = None
    if data.get("combat"):
        cb = data["combat"]
        combat = CombatResult(
            dmg_to_enemy=cb.get("dmg_to_enemy", 0),
            dmg_to_player=cb.get("dmg_to_player", 0),
            result=cb.get("result", "flee"),
            enemy_remaining_hp=cb.get("enemy_remaining_hp", 0),
            player_remaining_hp=cb.get("player_remaining_hp", 0),
        )

    return DMResponse(
        intent=intent,
        action_valid=data.get("action_valid", True),
        invalid_reason=data.get("invalid_reason", ""),
        story=data.get("story", ""),
        state_delta=data.get("state_delta"),
        breakthrough=breakthrough,
        combat=combat,
        npc_update=data.get("npc_update"),
    )


async def parse_dm_response_with_retry(
    raw_text: str,
    client=None,
    system_prompt: str = "",
    user_prompt: str = "",
    max_retries: int = 1,
) -> DMResponse:
    """
    Parse DM response with retry logic.
    If initial parse fails (intent=OTHER + action_valid=False), retry once with stricter prompt.
    """
    result = parse_dm_response(raw_text)

    if result.action_valid or max_retries <= 0 or client is None:
        return result

    # Retry with stricter instruction
    retry_system = system_prompt + "\n\n【警告】你上次的回复格式不正确，请务必只返回纯JSON，不要包含任何其他文字。"
    try:
        retry_raw = await client.generate(retry_system, user_prompt)
        retry_result = parse_dm_response(retry_raw)
        if retry_result.action_valid:
            return retry_result
    except Exception:
        pass

    return result