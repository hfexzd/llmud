"""LLM world generation orchestration.

Calls the LLM with worldgen context, parses the response into a WorldBible,
validates it, and returns it if valid.
"""

from __future__ import annotations

import json
import re

from dm.client import LLMClient
from engine.models import WorldBible, WorldState, Player, ResolvedTension
from worldgen.prompt import build_worldgen_context
from worldgen.validator import validate_bible


async def generate_bible(
    resolved_tensions: list[ResolvedTension],
    world_state: WorldState,
    player: Player,
    old_bible: WorldBible,
    llm_client: LLMClient,
) -> WorldBible | None:
    """Generate a new WorldBible for the next phase.

    Returns None if parsing or validation fails (old bible is preserved).
    """
    system_prompt, user_prompt = build_worldgen_context(
        resolved_tensions, world_state, player, old_bible,
    )

    try:
        raw = await llm_client.generate(system_prompt, user_prompt)
    except Exception:
        return None

    # Extract JSON from response
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        return None

    try:
        data = json.loads(json_match.group(0))
    except json.JSONDecodeError:
        return None

    try:
        new_bible = WorldBible(**data)
    except Exception:
        return None

    # Schema validation
    errors = validate_bible(new_bible)
    if errors:
        return None

    # Ensure phase_id is incremented
    new_bible.phase_id = old_bible.phase_id + 1

    return new_bible
