"""Offline growth (M6). Rule-driven tick advance — no LLM, no breakthrough, no ending.

When the player returns after being away, the engine computes how many ticks
elapsed (capped), runs npc_step + tension_tick for each, and applies directive-
based resource accumulation. No LLM calls, no breakthrough, no ending trigger.
"""

from __future__ import annotations
from datetime import datetime
from engine.models import Player, WorldState, WorldBible
from engine.world import npc_step, tension_tick


# Max offline budget in ticks (~8h at 1 tick/min)
OFFLINE_MAX_BUDGET = 480

# 1 tick = 1 minute in real time
TICK_DURATION_MINUTES = 1

DIRECTIVE_RATES = {
    "闭关": {"spirit_per_tick": 1, "hp_per_tick": 0, "tension_progress": False},
    "历练": {"spirit_per_tick": 1, "hp_per_tick": 0, "tension_progress": True},
    "静养": {"spirit_per_tick": 0, "hp_per_tick": 2, "tension_progress": False},
}


def compute_offline_budget(
    last_seen: datetime, now: datetime, rate: float = 1.0,
) -> int:
    """Compute how many ticks the player was offline, capped at OFFLINE_MAX_BUDGET."""
    seconds_offline = (now - last_seen).total_seconds()
    ticks = int(seconds_offline / (TICK_DURATION_MINUTES * 60) * rate)
    return min(ticks, OFFLINE_MAX_BUDGET)


def advance_offline(
    player: Player,
    world_state: WorldState,
    bible: WorldBible,
    now: datetime | None = None,
    directive: str = "闭关",
) -> tuple[Player, WorldState, str]:
    """Advance the world forward while the player is offline.

    Pure function. Runs rule-driven npc_step + tension_tick for each offline
    tick. Updates player spirit power / HP based on directive. Does NOT call
    LLM, does NOT trigger breakthrough, does NOT trigger endings.

    Returns (updated_player, updated_world_state, catchup_summary).
    """
    if now is None:
        now = datetime.now()

    # Normalize timezone: both must be aware or both naive for subtraction
    from datetime import timezone
    ls = player.last_seen
    if ls.tzinfo is None and now.tzinfo is not None:
        ls = ls.replace(tzinfo=timezone.utc)
    elif ls.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    budget = compute_offline_budget(ls, now)
    if budget <= 0:
        return player, world_state, "你刚刚离开，世界还没来得及变化。"

    rates = DIRECTIVE_RATES.get(directive, DIRECTIVE_RATES["闭关"])

    new_p = player
    new_ws = world_state
    spirit_gained = 0
    hp_gained = 0

    for _ in range(budget):
        new_p = new_p.model_copy(update={"tick": new_p.tick + 1})
        new_ws = new_ws.model_copy(update={"tick": new_ws.tick + 1})

        # Rule-driven world simulation
        new_ws = npc_step(new_ws, bible, new_p.tick)
        new_ws = tension_tick(new_ws, bible, new_p)

        # Apply directive effects
        updates = {}
        if rates["spirit_per_tick"] > 0:
            new_spirit = new_p.spirit_power + rates["spirit_per_tick"]
            updates["spirit_power"] = new_spirit
            spirit_gained += rates["spirit_per_tick"]
        if rates["hp_per_tick"] > 0:
            new_hp = min(new_p.max_hp, new_p.hp + rates["hp_per_tick"])
            updates["hp"] = new_hp
            hp_gained += new_hp - new_p.hp
        if updates:
            new_p = new_p.model_copy(update=updates)

    # Build catch-up summary
    summary_parts: list[str] = []
    if spirit_gained > 0:
        summary_parts.append(f"灵力+{spirit_gained}")
    if hp_gained > 0:
        summary_parts.append(f"气血+{hp_gained}")
    summary_parts.append(f"已过{budget}回合")
    summary = f"【离线归来】{directive}期间，{'，'.join(summary_parts)}。"

    return new_p, new_ws, summary
