from npc.models import NPCProfile, NPCTurn, KeyFact, NPCMemory, DEFAULT_NPC_PROFILE

RELATIONSHIP_THRESHOLDS = [
    (81, "知己"),
    (51, "熟悉"),
    (21, "相识"),
    (0, "陌生"),
]

MAX_RECENT_TURNS = 6  # Keep ~6 recent turns (3 exchanges)
MAX_KEY_FACTS = 5  # Keep top 5 key facts by recency


def compute_relationship_stage(favorability: int) -> str:
    """Determine relationship stage from favorability score."""
    for threshold, stage in RELATIONSHIP_THRESHOLDS:
        if favorability >= threshold:
            return stage
    return "陌生"


def update_memory(
    memory: NPCMemory,
    user_message: str,
    npc_response: str,
    npc_update: dict | None = None,
    turn_number: int = 0,
) -> NPCMemory:
    """
    Update NPC memory after an interaction.
    - Append turns
    - Store key facts from npc_update
    - Update summary from npc_update
    - Trim to limits
    """
    npc_update = npc_update or {}

    # Append recent turns
    new_turns = list(memory.recent_turns)
    new_turns.append(NPCTurn(role="user", content=user_message))
    new_turns.append(NPCTurn(role="assistant", content=npc_response))

    # Keep only recent turns (last MAX_RECENT_TURNS)
    if len(new_turns) > MAX_RECENT_TURNS:
        new_turns = new_turns[-MAX_RECENT_TURNS:]

    # Store key facts
    new_facts = list(memory.key_facts)
    new_key_fact = npc_update.get("new_key_fact")
    if new_key_fact:
        new_facts.append(KeyFact(fact=new_key_fact, turn_number=turn_number))
    # Keep only most recent facts
    if len(new_facts) > MAX_KEY_FACTS:
        new_facts = sorted(new_facts, key=lambda f: f.turn_number, reverse=True)[:MAX_KEY_FACTS]

    # Update summary
    summary = memory.summary
    summary_delta = npc_update.get("summary_delta", "")
    if summary_delta:
        summary = f"{summary} {summary_delta}".strip() if summary else summary_delta

    return NPCMemory(
        npc_id=memory.npc_id,
        recent_turns=new_turns,
        summary=summary,
        key_facts=new_facts,
    )


def build_memory_context(memory: NPCMemory) -> str:
    """Build the memory context string for NPC prompts."""
    parts = []

    if memory.summary:
        parts.append(f"【前情提要】{memory.summary}")

    if memory.key_facts:
        facts_text = "、".join(f.fact for f in memory.key_facts)
        parts.append(f"【关键事实】{facts_text}")

    if memory.recent_turns:
        turns_text = "\n".join(
            f"{'玩家' if t.role == 'user' else '师姐'}：{t.content}"
            for t in memory.recent_turns
        )
        parts.append(f"【近期对话】\n{turns_text}")

    return "\n\n".join(parts)


async def summarize_turns(memory: NPCMemory, llm_client) -> str:
    """
    Use LLM to summarize recent turns when they exceed the limit.
    This is called lazily — only when recent_turns grow beyond MAX_RECENT_TURNS.
    """
    if not memory.recent_turns:
        return memory.summary

    turns_text = "\n".join(
        f"{'玩家' if t.role == 'user' else '师姐'}：{t.content}"
        for t in memory.recent_turns
    )

    system = "你是一个摘要助手。请用1-2句话概括以下对话的关键信息，保留重要的情感和事实。只输出摘要，不要其他内容。"
    user = f"请概括以下对话：\n{turns_text}"

    try:
        summary = await llm_client.generate(system, user)
        return summary.strip()
    except Exception:
        return memory.summary