"""Ending system (M4). Pure functions — no LLM, no side effects.

Evaluates terminal archetype conditions against (world_state, player, bible)
each tick. When a condition fires, the world is sealed and the ending id is
returned for the pipeline to handle finale narration.
"""

from __future__ import annotations

from engine.models import (
    WorldState, WorldBible, Player,
    TERMINAL_ARCHETYPES,
)
from engine.world import evaluate_condition


def check_ending(
    world_state: WorldState,
    bible: WorldBible,
    player: Player,
) -> str | None:
    """Evaluate terminal archetypes against current state.

    Returns the first-matched archetype id, or None if no condition fires
    (including when world_state is already sealed).
    """
    if world_state.sealed:
        return None

    # Sort archetypes by priority descending (higher = checked first)
    sorted_archetypes = sorted(TERMINAL_ARCHETYPES, key=lambda a: -a.priority)

    for archetype in sorted_archetypes:
        if evaluate_condition(archetype.condition, player, world_state):
            return archetype.id

    return None
