"""World engine: scene lookups, event triggering, NPC presence, move validation, ticks."""

from __future__ import annotations

import random

from engine.models import (
    NPC_PRESENCES,
    NPC_INTERACTIONS,
    ALL_EVENTS,
    ENCOUNTERS_BY_SCENE,
    SCENE_MAP,
    NPCInteraction,
    Player,
    Scene,
    WorldEvent,
    Goal,
    GOALS,
    GOAL_BY_ID,
    QuestState,
    resolve_scene_id,
    WorldState,
    WorldBible,
    NPCRuntimeState,
    TensionRuntime,
    ResolvedTension,
)


# Priority order for event trigger types (lower = higher priority)
_TRIGGER_PRIORITY: dict[str, int] = {
    "location_enter": 1,
    "stat_threshold": 2,
    "tick_interval": 3,
    "random": 4,
}


# Completed 所务 stay visible (struck through) this many ticks, then auto-hide.
QUEST_EXPIRY_TICKS = 6


class WorldEngine:
    """Manages living-world state: scenes, NPCs, events, and tick progression."""

    # ------------------------------------------------------------------
    # Scene helpers
    # ------------------------------------------------------------------

    def get_scene(self, scene_id: str) -> Scene | None:
        """Return a Scene by id, or None if not found."""
        return SCENE_MAP.get(scene_id)

    # ------------------------------------------------------------------
    # NPC presence
    # ------------------------------------------------------------------

    def get_npcs_in_scene(self, scene_id: str, tick: int) -> list[str]:
        """Return NPC ids present in *scene_id* at the given *tick*.

        An NPC follows its schedule if the tick falls within a scheduled
        tick_range; otherwise they are at their default_scene.
        """
        result: list[str] = []
        for npc_id, presence in NPC_PRESENCES.items():
            current_scene = presence.default_scene
            for schedule in presence.schedule:
                lo, hi = schedule.tick_range
                if lo <= tick <= hi:
                    current_scene = schedule.scene_id
                    break  # first matching schedule wins
            if current_scene == scene_id:
                result.append(npc_id)
        return result

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def check_events(self, scene_id: str, player: Player) -> WorldEvent | None:
        """Return the highest-priority qualifying event for this scene, or None.

        Steps:
        1. Filter events by scene_id.
        2. Skip one_time events already in player.seen_events.
        3. Sort by trigger-type priority.
        4. Walk in priority order; return the first event whose trigger
           conditions are met and whose probability roll succeeds.
        """
        candidates = [
            e for e in ALL_EVENTS
            if e.scene_id == scene_id
        ]

        # Remove one-time events the player has already seen
        candidates = [
            e for e in candidates
            if not (e.one_time and e.id in player.seen_events)
        ]

        # Sort by trigger-type priority
        candidates.sort(key=lambda e: _TRIGGER_PRIORITY.get(e.trigger.type, 99))

        for event in candidates:
            if self._check_trigger(event, player):
                return event

        return None

    def _check_trigger(self, event: WorldEvent, player: Player) -> bool:
        """Evaluate whether *event*'s trigger fires for *player*."""
        trigger = event.trigger
        conditions = trigger.conditions
        trigger_type = trigger.type

        if trigger_type == "location_enter":
            # first_time: the event must not have been seen yet
            if conditions.get("first_time"):
                if event.id in player.seen_events:
                    return False

            # npc_present: all listed NPCs must be in the scene
            npc_ids_needed: list[str] | None = conditions.get("npc_present")
            if npc_ids_needed:
                npcs_present = self.get_npcs_in_scene(event.scene_id, player.tick)
                if not all(nid in npcs_present for nid in npc_ids_needed):
                    return False

            return True

        if trigger_type == "stat_threshold":
            min_spirit = conditions.get("min_spirit", 0)
            max_spirit = conditions.get("max_spirit", float("inf"))
            if player.spirit_power < min_spirit:
                return False
            if player.spirit_power >= max_spirit:
                return False
            return True

        if trigger_type == "tick_interval":
            min_tick = conditions.get("min_tick", 0)
            if player.tick < min_tick:
                return False
            return True

        if trigger_type == "random":
            return random.random() < trigger.probability

        # Unknown trigger type — skip
        return False

    # ------------------------------------------------------------------
    # NPC interactions
    # ------------------------------------------------------------------

    def check_npc_interactions(self, scene_id: str, tick: int) -> NPCInteraction | None:
        """Return the first qualifying NPC-to-NPC interaction, or None."""
        for interaction in NPC_INTERACTIONS:
            if interaction.scene_id != scene_id:
                continue
            # Check tick_min condition
            tick_min = interaction.trigger_conditions.get("tick_min", 0)
            if tick < tick_min:
                continue
            # Verify all NPCs are present
            npcs_in_scene = self.get_npcs_in_scene(scene_id, tick)
            if all(nid in npcs_in_scene for nid in interaction.npc_ids):
                return interaction
        return None

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def validate_move(self, from_scene: str, to_scene: str) -> bool:
        """Check whether *from_scene* connects directly to *to_scene*."""
        source = SCENE_MAP.get(from_scene)
        if source is None:
            return False
        return to_scene in source.connections

    # ------------------------------------------------------------------
    # Current objective (所务) + quest log
    # ------------------------------------------------------------------

    def current_goal(self, player: Player) -> Goal | None:
        """Return the player's current objective: the first quest that is
        unlocked but not yet satisfied (by priority order in GOALS), or None
        when the whole arc is complete. Pure function of player state."""
        for goal in GOALS:
            if self._quest_unlocked(goal.id, player) and not self._goal_satisfied(goal.id, player):
                return goal
        return None

    def _quest_unlocked(self, goal_id: str, player: Player) -> bool:
        """Deterministic unlock gate keyed on player state. A quest appears in
        the visible list only once its unlock condition is met — this is what
        makes the 所务 list 'grow as the story progresses', engine-driven."""
        visited = set(player.visited_scenes or [])
        seen = set(player.seen_events or [])
        if goal_id == "venture_bamboo":
            return True
        if goal_id == "probe_anomaly":
            return "bamboo_forest" in visited
        if goal_id == "cultivate_breakthrough":
            return "spirit_herb" in seen
        if goal_id == "venture_mountain":
            return player.level == "练气期二层"
        return False

    def _goal_satisfied(self, goal_id: str, player: Player) -> bool:
        """Deterministic satisfaction check keyed on player state only."""
        visited = set(player.visited_scenes or [])
        seen = set(player.seen_events or [])
        if goal_id == "venture_bamboo":
            return "bamboo_forest" in visited
        if goal_id == "probe_anomaly":
            return "spirit_herb" in seen
        if goal_id == "cultivate_breakthrough":
            return player.level == "练气期二层"
        if goal_id == "venture_mountain":
            return "mountain_range" in visited
        return False

    def _quest_record(self, player: Player, goal_id: str) -> QuestState | None:
        """Return the persisted record for a goal, if any."""
        for q in player.quests or []:
            if q.id == goal_id:
                return q
        return None

    def visible_quests(self, player: Player) -> list[dict]:
        """The visible 所务 list, derived purely from player state. Each entry
        is {id, label, status}. Completed quests show only until expiry
        (QUEST_EXPIRY_TICKS after their recorded completed_tick)."""
        visible: list[dict] = []
        for goal in GOALS:
            if not self._quest_unlocked(goal.id, player):
                continue
            if self._goal_satisfied(goal.id, player):
                rec = self._quest_record(player, goal.id)
                completed_tick = rec.completed_tick if rec else player.tick
                if player.tick - completed_tick < QUEST_EXPIRY_TICKS:
                    visible.append({"id": goal.id, "label": goal.label, "status": "completed"})
            else:
                visible.append({"id": goal.id, "label": goal.label, "status": "active"})
        return visible

    def next_quest(self, player: Player) -> Goal | None:
        """The first not-yet-unlocked goal (preview line '将解锁…'), or None."""
        for goal in GOALS:
            if not self._quest_unlocked(goal.id, player):
                return goal
        return None

    def update_quests(self, player: Player) -> Player:
        """Called once per action, after all state mutations + tick advance.
        Records completed_tick for newly-satisfied quests (so the visible list
        can expire them later) and prunes expired records. Returns a new Player.

        The visible list itself is derived from state, so this only maintains
        the lifecycle records — it does not change what is 'true'."""
        now = player.tick
        records: dict[str, QuestState] = {q.id: q for q in player.quests or []}
        for goal in GOALS:
            if self._quest_unlocked(goal.id, player) and self._goal_satisfied(goal.id, player):
                if goal.id not in records:
                    records[goal.id] = QuestState(
                        id=goal.id, status="completed",
                        unlocked_tick=now, completed_tick=now,
                    )
        kept = [
            q for q in records.values()
            if not (q.status == "completed"
                    and (now - (q.completed_tick if q.completed_tick is not None else now)) >= QUEST_EXPIRY_TICKS)
        ]
        return player.model_copy(update={"quests": list(kept)})

    # ------------------------------------------------------------------
    # Tick progression
    # ------------------------------------------------------------------

    def advance_tick(self, player: Player) -> Player:
        """Increment the player's tick by 1 (returns a new Player)."""
        return player.model_copy(update={"tick": player.tick + 1})

    # ------------------------------------------------------------------
    # Event application
    # ------------------------------------------------------------------

    def apply_event(self, player: Player, event: WorldEvent) -> Player:
        """Mark one-time events as seen; return updated player."""
        updates: dict = {}
        if event.one_time and event.id not in player.seen_events:
            updates["seen_events"] = [*player.seen_events, event.id]
        if updates:
            return player.model_copy(update=updates)
        return player

    # ------------------------------------------------------------------
    # Encounters
    # ------------------------------------------------------------------

    def get_encounters_for_scene(self, scene_id: str) -> list[str]:
        """Return encounter ids available in the given scene."""
        return ENCOUNTERS_BY_SCENE.get(scene_id, [])

    # ------------------------------------------------------------------
    # Scene-move resolution
    # ------------------------------------------------------------------

    def resolve_scene_move(
        self, player: Player, destination_text: str
    ) -> tuple[str, str]:
        """Try to resolve *destination_text* into a valid move.

        Accepts a scene id, the full scene name, or natural-language text
        containing a scene alias (e.g. "去内门灵泉旁修炼" → "inner_gate").

        Returns (status, scene_id_or_message):
          - ("ok", scene_id)        on success
          - ("error", msg)          on failure
        """
        target_id = resolve_scene_id(destination_text)

        if target_id is None:
            # In-world fallback — never expose a system-style "未知地点: X" message.
            return ("error", "你寻不到这般去处，只得在原地驻足片刻。")

        # A landmark/alias that lives in the player's current scene is a local
        # move (already here), not a scene transition — allow it as a no-op.
        if target_id == player.current_scene:
            return ("ok", target_id)

        if not self.validate_move(player.current_scene, target_id):
            # Use Chinese scene names in the error — never expose raw ids to the player.
            from_scene = SCENE_MAP.get(player.current_scene)
            from_name = from_scene.name if from_scene else player.current_scene
            to_name = SCENE_MAP[target_id].name
            return ("error", f"从{from_name}没有直达{to_name}的路，你只得暂且作罢。")

        return ("ok", target_id)


# ----------------------------------------------------------------------
# Condition evaluator — interprets the dict predicates on
# TensionTrigger.conditions / ResolutionPath.condition against the player
# and world state. Pure, deterministic, no LLM. AND across keys: every key
# must hold. Unknown predicate keys fail safe (False).
# ----------------------------------------------------------------------

def evaluate_condition(condition: dict, player: Player, world_state: WorldState) -> bool:
    """Return True iff every predicate in *condition* holds for (player, world_state).

    Supported keys (AND-combined; empty dict → True):
      - always: bool             — truthy → True
      - visited: scene_id         — scene_id in player.visited_scenes
      - seen_event: event_id       — event_id in player.seen_events
      - level: 境界 str            — player.level == value
      - min_spirit: int            — player.spirit_power >= value
      - min_tick: int              — player.tick >= value
      - tension_resolved: tid       — tid in world_state.resolved_tensions
    """
    if not condition:
        return True
    visited = set(player.visited_scenes or [])
    seen = set(player.seen_events or [])
    for key, val in condition.items():
        if key == "always":
            if not val:
                return False
        elif key == "visited":
            if val not in visited:
                return False
        elif key == "seen_event":
            if val not in seen:
                return False
        elif key == "level":
            if player.level != val:
                return False
        elif key == "min_spirit":
            if player.spirit_power < val:
                return False
        elif key == "min_tick":
            if player.tick < val:
                return False
        elif key == "tension_resolved":
            if not any(rt.tension_id == val for rt in world_state.resolved_tensions):
                return False
        else:
            return False  # unknown predicate — fail safe
    return True


# ----------------------------------------------------------------------
# Emergent world tick (M1 scaffold) — module-level pure functions, no LLM.
# ----------------------------------------------------------------------

def npc_step(world_state: WorldState, bible: WorldBible, tick: int) -> WorldState:
    """Rule-driven NPC step: set each NPC's scene_id from its presence
    schedule at the given tick. No LLM. Pure function — returns a new
    WorldState, leaves the input untouched.

    M1 behavior is minimal: NPCs follow their NPC_PRESENCES schedule (the
    same logic as WorldEngine.get_npcs_in_scene). Richer routine actions
    (mood shifts, goal_progress bumps, interact_npc) arrive in later
    milestones.
    """
    new_npc_state = dict(world_state.npc_state)
    for npc_model in bible.npc_models:
        presence = NPC_PRESENCES.get(npc_model.npc_id)
        scene = presence.default_scene if presence else "outer_gate"
        if presence:
            for schedule in presence.schedule:
                lo, hi = schedule.tick_range
                if lo <= tick <= hi:
                    scene = schedule.scene_id
                    break
        prev = new_npc_state.get(npc_model.npc_id)
        new_npc_state[npc_model.npc_id] = NPCRuntimeState(
            npc_id=npc_model.npc_id,
            scene_id=scene,
            mood=prev.mood if prev else "",
            goal_progress=dict(prev.goal_progress) if prev else {},
            schedule_tick=tick,
            last_autonomous_action=prev.last_autonomous_action if prev else None,
        )
    return world_state.model_copy(update={"npc_state": new_npc_state})


def tension_tick(world_state: WorldState, bible: WorldBible, player: Player) -> WorldState:
    """Tension state machine stub (M1): no-op. Returns a copy so callers
    can chain model_copy updates uniformly. M2 implements trigger /
    progress / resolve; M7 adds world_pressure accumulation."""
    return world_state.model_copy()