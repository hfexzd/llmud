"""Game endpoints — orchestrates the full classify→engine→world→dm→npc pipeline."""
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dm.client import LLMClient
from dm.contract import parse_dm_response, extract_story_so_far
from dm.prompt import build_dm_prompt
from engine.classify import classify_intent, classify_intent_llm, resolve_npc_target
from engine.models import Intent, Player, Encounter, DEFAULT_ENCOUNTER, NPCInteraction, EventTrigger, WorldEvent, SCENE_MAP, next_spirit_threshold, DMResponse, WorldState, PHASE_0_BIBLE
from engine.rules import cultivate, resolve_combat, check_breakthrough, compute_attack, compute_defense, move
from engine.world import WorldEngine, npc_step, tension_tick
from db.repository import PlayerRepository, NPCRepository, WorldRepository
from npc.memory import update_memory, build_memory_context, compute_relationship_stage
from npc.models import NPCMemory, NPCTurn, KeyFact, DEFAULT_NPC_PROFILE
from safety.filter import pre_filter_input, post_filter_output


class ActionRequest(BaseModel):
    user_input: str


def _resolve_talk_target(player, filtered_input, world_engine, npc_repo):
    """Pick the NPC id a TALK action addresses: a named NPC present in the
    scene if the input names one, else the first present NPC, else the
    default. Mirrors resolve_scene_id's philosophy for NPC targeting."""
    npcs_in_scene = world_engine.get_npcs_in_scene(player.current_scene, player.tick)
    name_by_id = {}
    for nid in npcs_in_scene:
        profile = npc_repo.get_profile(nid)
        if profile:
            name_by_id[nid] = profile.get("name", "")
    named = resolve_npc_target(filtered_input, name_by_id)
    if named:
        return named
    return npcs_in_scene[0] if npcs_in_scene else DEFAULT_NPC_PROFILE.id


async def _stream_llm(llm_client, system_prompt: str, user_prompt: str):
    """Yield LLM output chunks for the DM narrative.

    Uses generate_stream when the client supports real token streaming; falls
    back to a single generate() call otherwise so duck-typed test clients
    (which only implement generate) keep working.
    """
    stream_fn = getattr(llm_client, "generate_stream", None)
    if stream_fn is not None:
        async for chunk in stream_fn(system_prompt, user_prompt):
            yield chunk
    else:
        yield await llm_client.generate(system_prompt, user_prompt)


def create_router(
    llm_client: LLMClient,
    player_repo: PlayerRepository,
    npc_repo: NPCRepository,
    encounter: Encounter,
    world_engine: WorldEngine,
    world_repo: WorldRepository,
) -> APIRouter:
    """Create a FastAPI router with game endpoints, wiring all subsystems."""
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET /player/status — player status with scene info
    # ------------------------------------------------------------------
    @router.get("/player/status")
    def get_status():
        """Return current player status including scene + panel data."""
        player = player_repo.get("p1")
        if player is None:
            return {"error": "Player not found"}

        scene = world_engine.get_scene(player.current_scene)
        scene_info = None
        if scene:
            npcs_present = world_engine.get_npcs_in_scene(scene.id, player.tick)
            scene_info = {
                "id": scene.id,
                "name": scene.name,
                "atmosphere": scene.atmosphere,
                "description": scene.description,
                "landmarks": scene.landmarks,
                "npcs_present": npcs_present,
                "connections": scene.connections,
            }

        # NPC cards for the 人物 panel: all NPCs, with present flag + profile data.
        present_ids = set(scene_info["npcs_present"]) if scene_info else set()
        npcs = [
            {
                "id": p["id"],
                "favorability": p.get("favorability", 50),
                "relationship_stage": p.get("relationship_stage", "陌生"),
                "default_scene": p.get("default_scene", "outer_gate"),
                "present": p["id"] in present_ids,
            }
            for p in npc_repo.get_all_profiles()
        ]

        world_state = world_repo.get("default") or WorldState()
        bible = PHASE_0_BIBLE
        # When no /game/action has run yet, the persisted world_state has no
        # tensions, so 所务 methods would return nothing. Derive tensions from
        # current player state once (pure + idempotent on already-populated
        # state) so /player/status shows the right goal before any action is
        # taken — mirrors the pre-tension behavior where goals came from player
        # state directly.
        if not world_state.tensions:
            world_state = tension_tick(world_state, bible, player)

        goal = world_engine.current_goal(player, world_state, bible)
        goal_info = {"id": goal.id, "label": goal.label} if goal else {
            "id": None, "label": "暂无要务，随心而行",
        }

        next_quest = world_engine.next_quest(player, world_state, bible)
        next_quest_info = {"label": next_quest.label} if next_quest else None

        return {
            "name": player.name,
            "current_scene": player.current_scene,
            "tick": player.tick,
            "level": player.level,
            "spirit_power": player.spirit_power,
            "hp": player.hp,
            "max_hp": player.max_hp,
            "affinity": player.affinity,
            "inventory": player.inventory,
            "attack": compute_attack(player),
            "defense": compute_defense(player),
            "scene": scene_info,
            "goal": goal_info,
            "npcs": npcs,
            "quests": world_engine.visible_quests(player, world_state, bible),
            "next_quest": next_quest_info,
            "next_threshold": next_spirit_threshold(player.level),
        }

    # ------------------------------------------------------------------
    # GET /game/scenes — list all scenes
    # ------------------------------------------------------------------
    @router.get("/game/scenes")
    def list_scenes():
        """Return all scenes in the world."""
        scenes = []
        for scene_id, scene in SCENE_MAP.items():
            scenes.append({
                "id": scene.id,
                "name": scene.name,
                "atmosphere": scene.atmosphere,
                "connections": scene.connections,
                "available_actions": scene.available_actions,
            })
        return {"scenes": scenes}

    # ------------------------------------------------------------------
    # POST /game/action — full action pipeline with world layer
    # ------------------------------------------------------------------
    @router.post("/game/action")
    async def game_action(request: ActionRequest):
        """Process a player action through the full pipeline."""
        # Step 1: Pre-filter input for safety
        filtered_input, blocked = pre_filter_input(request.user_input)
        if blocked:
            def blocked_response():
                yield json.dumps({
                    "intent": "other",
                    "action_valid": False,
                    "invalid_reason": "内容不合规",
                    "story": filtered_input,
                    "state_delta": {},
                    "breakthrough": None,
                    "combat": None,
                    "npc_update": None,
                }, ensure_ascii=False)
            return StreamingResponse(blocked_response(), media_type="application/json")

        # Load player state
        player = player_repo.get("p1")
        if player is None:
            player = Player()

        # Step 2: Classify intent — regex fast-path first.
        intent, params = classify_intent(filtered_input)

        # LLM fallback when the fast-path is uncertain: a move verb with no
        # resolvable destination (e.g. "好啊，去走走"承接林婉儿的邀请→竹林), or no
        # recognizable pattern at all (e.g. "好啊", "走吧"). The LLM sees the
        # recent conversation plus reachable places so it can infer an implied
        # destination. The engine still validates reachability, so the LLM
        # cannot teleport the player.
        move_unresolved = (
            intent == Intent.MOVE and not params.get("destination_resolved", False)
        )
        if (intent == Intent.OTHER or move_unresolved) and llm_client is not None:
            ctx_scene = world_engine.get_scene(player.current_scene)
            ctx_scene_name = ctx_scene.name if ctx_scene else player.current_scene
            candidates: list[str] = []
            if ctx_scene:
                for cid in ctx_scene.connections:
                    nxt = SCENE_MAP.get(cid)
                    if nxt:
                        candidates.append(nxt.name)
                candidates.extend(ctx_scene.landmarks)
            llm_intent, llm_params = await classify_intent_llm(
                filtered_input, llm_client, ctx_scene_name, candidates,
                player.recent_stories,
            )
            if llm_intent is not None:
                intent, params = llm_intent, llm_params

        # Step 3: Engine resolution (deterministic)
        combat_result = None
        breakthrough = None
        move_error = None

        if intent == Intent.CULTIVATE:
            player = cultivate(player)
            breakthrough = check_breakthrough(player)
            if breakthrough:
                player = player.model_copy(update={"level": breakthrough.to_level})

        elif intent == Intent.FIGHT:
            # Continue an in-progress fight in this scene from the enemy's
            # stored HP, or spawn a fresh enemy. Without persisting HP across
            # rounds the beast would reset to full every turn and never die.
            active = player.active_enemy
            if (active and active.get("scene_id") == player.current_scene
                    and active.get("hp", 0) > 0):
                enemy = Encounter(
                    id=active.get("id", encounter.id),
                    name=active.get("name", encounter.name),
                    attack=active.get("attack", encounter.attack),
                    defense=active.get("defense", encounter.defense),
                    hp=active.get("hp", encounter.hp),
                    max_hp=active.get("max_hp", encounter.max_hp),
                )
            else:
                enemy = encounter.model_copy()  # fresh, full-HP enemy

            combat_result, player, updated_enemy = resolve_combat(player, enemy)
            if combat_result.result == "lose":
                player = player.model_copy(update={"hp": 1})

            # Persist the enemy's remaining HP so the next attack continues the
            # fight; clear it once the beast is slain.
            if combat_result.result == "win":
                player = player.model_copy(update={"active_enemy": None})
            else:
                player = player.model_copy(update={
                    "active_enemy": {
                        "scene_id": player.current_scene,
                        **updated_enemy.model_dump(),
                    }
                })

        elif intent == Intent.MOVE:
            # Resolve move via world engine
            destination = params.get("destination", filtered_input)
            status, result = world_engine.resolve_scene_move(player, destination)
            if status == "ok":
                player = move(player, result)
                # Record the visit so the objective layer (所务) can mark
                # exploration goals satisfied.
                visited = list(player.visited_scenes or [])
                if result not in visited:
                    visited.append(result)
                    player = player.model_copy(update={"visited_scenes": visited})
            else:
                move_error = result  # Store the error message

        elif intent == Intent.TALK:
            pass  # NPC interaction handled in DM phase

        # Step 4: World layer — advance tick, check events, check NPC interactions
        player = world_engine.advance_tick(player)

        # World layer scaffold (M1): track emergent world state alongside the
        # player. Rule-driven npc_step (NPCs follow their schedule) + a no-op
        # tension_tick stub. Behavior is unchanged — world state is NOT yet fed
        # to the DM prompt (that arrives in M3 with the outcome resolver).
        world_state = world_repo.get("default") or WorldState()
        bible = PHASE_0_BIBLE  # M5 swaps in LLM-regenerated bibles; M1 is always phase-0
        world_state = npc_step(world_state, bible, player.tick)
        world_state = tension_tick(world_state, bible, player)
        world_state = world_state.model_copy(update={"tick": player.tick})
        world_repo.save(world_state)

        # Get current scene info
        scene = world_engine.get_scene(player.current_scene)

        # Check for world events at current scene
        world_event = None
        if scene:
            world_event = world_engine.check_events(scene.id, player)

        # Check for NPC-to-NPC interactions in the scene
        npc_interaction = world_engine.check_npc_interactions(player.current_scene, player.tick)

        # If NPC interaction has priority (allow_intervene), use it as the world event
        intervention = None
        if npc_interaction and npc_interaction.allow_intervene:
            intervention = npc_interaction
            # If no world event was found, promote the NPC interaction to a WorldEvent for the prompt
            if world_event is None:
                world_event = WorldEvent(
                    id=npc_interaction.id,
                    name=npc_interaction.narrative_hint[:20],
                    scene_id=npc_interaction.scene_id,
                    trigger=EventTrigger(type="location_enter", conditions={}),
                    narrative_hint=npc_interaction.narrative_hint,
                    guidance=npc_interaction.narrative_hint,
                    allow_intervene=npc_interaction.allow_intervene,
                    intervene_options=npc_interaction.intervene_options,
                    one_time=False,
                )

        # Apply world event to player (mark one-time events as seen)
        if world_event:
            player = world_engine.apply_event(player, world_event)

        # Step 5: Narrative (DM LLM call)
        npc_context = ""
        npc_update_dict = None

        if intent == Intent.TALK:
            # Determine target NPC: a named NPC present in the scene if the
            # input names one (e.g. "对陈浩说…"), else the first present NPC,
            # else the default. See _resolve_talk_target.
            target_npc_id = _resolve_talk_target(player, filtered_input, world_engine, npc_repo)

            profile_row = npc_repo.get_profile(target_npc_id)
            npc_profile = dict(profile_row) if profile_row else {}

            npc_memory_row = npc_repo.get_memory(target_npc_id)
            if npc_memory_row:
                memory = _build_memory_from_row(npc_memory_row)
            else:
                memory = NPCMemory(npc_id=target_npc_id)

            npc_context = build_memory_context(memory)

        # Current objective (所务) — deterministic, from player state. Computed
        # after the world layer so visited_scenes / seen_events / breakthrough
        # are up to date; used both to steer the DM and to surface in the response.
        goal = world_engine.current_goal(player, world_state, bible)

        system_prompt, user_prompt = build_dm_prompt(
            player=player,
            intent=intent,
            combat_result=combat_result,
            breakthrough=breakthrough,
            npc_context=npc_context,
            recent_stories=player.recent_stories,
            scene=scene,
            world_event=world_event,
            goal=goal,
        )

        # Prepend the user's actual input to the prompt
        if user_prompt:
            user_prompt = f"{user_prompt}\n\n玩家：{filtered_input}"
        else:
            user_prompt = filtered_input

        # Step 5: Narrative — stream the story to the client token-by-token.
        #
        # The response is a single JSON object sent in pieces so the client can
        # render the story as it arrives, while the full body still parses as
        # one JSON object (tests do json.loads(response.text)). Layout:
        #   {"story":"<streamed>", <rest>}
        # story is emitted first (prefix + escaped deltas + closing quote),
        # then the remaining engine/DM fields follow once the LLM finishes.
        #
        # Trade-off: streaming commits the story to the wire before we can
        # validate the whole JSON, so parse_dm_response_with_retry's retry is
        # disabled here — a malformed DM reply falls back to a deterministic
        # story instead of a second LLM call. The retry only ever fired on
        # already-broken output, so this costs little.
        story_fallbacks = {
            Intent.CULTIVATE: f"{player.name}盘膝而坐，静静修炼，灵气缓缓涌入丹田。",
            Intent.TALK: f"{player.name}与身边的人交谈了几句。",
            Intent.FIGHT: f"{player.name}与妖兽展开了激烈的交锋！",
            Intent.MOVE: f"{player.name}向新的方向走去。",
            Intent.INTERVENE: f"{player.name}选择了介入。",
            Intent.OTHER: f"{player.name}的行动似乎没有引起什么变化。",
        }

        async def response_generator():
            # `player` is reassigned in the tail (state_delta/breakthrough/
            # recent_stories all produce a new model_copy), so it must be
            # nonlocal — otherwise Python treats it as a generator-local and
            # the first read raises UnboundLocalError.
            nonlocal player
            # Prefix: open the JSON object and the story string.
            yield '{"story":"'

            if move_error:
                # Engine-authoritative: the move was invalid, so narrate the
                # engine's in-world error directly. No LLM story is streamed.
                dm_response = DMResponse(
                    intent=Intent.OTHER, action_valid=False,
                    invalid_reason=move_error, story=move_error,
                )
                story = move_error
                yield json.dumps(story, ensure_ascii=False)[1:-1]
            else:
                raw_response = ""
                last = ""
                try:
                    async for chunk in _stream_llm(llm_client, system_prompt, user_prompt):
                        raw_response += chunk
                        now = extract_story_so_far(raw_response)
                        if now != last:
                            # json.dumps(...)[1:-1] = the string content,
                            # JSON-escaped, without the surrounding quotes.
                            yield json.dumps(now[len(last):], ensure_ascii=False)[1:-1]
                            last = now
                except Exception:
                    # LLM failed mid-stream. Close the story with an error and
                    # fall through to the common tail so the engine/world
                    # state already computed still persists.
                    dm_response = DMResponse(
                        intent=intent, action_valid=False,
                        invalid_reason="传信飞鸽被雷劈了",
                        story="【系统】传信飞鸽在半路被雷劈了，请重试。",
                    )
                    story = dm_response.story
                    yield json.dumps(story, ensure_ascii=False)[1:-1]
                    raw_response = ""
                else:
                    # Step 6 + 7: post-filter, then parse (no retry while
                    # streaming — see the trade-off note above).
                    raw_response, _was_rewritten = post_filter_output(raw_response)
                    dm_response = parse_dm_response(raw_response)
                    story = dm_response.story
                    if not story or not story.strip():
                        story = story_fallbacks.get(intent, f"{player.name}的行动似乎没有引起什么变化。")
                    # Reconcile: emit any trailing story not yet streamed (the
                    # extractor may lag if story wasn't the first field, or if
                    # a trailing escape was withheld).
                    if story.startswith(last):
                        tail = story[len(last):]
                        if tail:
                            yield json.dumps(tail, ensure_ascii=False)[1:-1]
                    elif last:
                        # Streamed text diverged from the authoritative story
                        # (a post_filter rewrite — rare for DM output). We
                        # can't un-yield what the player already saw, so keep
                        # the streamed text as the story of record.
                        story = last
                    if dm_response.story != story:
                        dm_response = dm_response.model_copy(update={"story": story})

            # --- common tail: apply DM-derived state, persist, build the rest ---

            # Apply state_delta from DM (for move/other intents)
            if dm_response.state_delta and dm_response.action_valid:
                updates = {}
                if "spirit_power" in dm_response.state_delta:
                    updates["spirit_power"] = player.spirit_power + dm_response.state_delta["spirit_power"]
                if "hp" in dm_response.state_delta:
                    updates["hp"] = max(1, player.hp + dm_response.state_delta["hp"])
                if "location" in dm_response.state_delta:
                    updates["current_scene"] = dm_response.state_delta["location"]
                if updates:
                    player = player.model_copy(update=updates)

            # Apply breakthrough from DM (authoritative if present)
            if dm_response.breakthrough:
                player = player.model_copy(update={"level": dm_response.breakthrough.to_level})

            # Handle NPC update
            if dm_response.npc_update:
                # Use the target NPC: named NPC if the input named one, else first
                # present, else default. Same resolution as the TALK context build.
                target_npc_id = _resolve_talk_target(player, filtered_input, world_engine, npc_repo)

                npc_update_dict = dm_response.npc_update
                profile_row = npc_repo.get_profile(target_npc_id)
                profile_dict = dict(profile_row) if profile_row else {}
                current_favorability = profile_dict.get("favorability", 50)
                favorability_change = npc_update_dict.get("favorability_change", 0)
                new_favorability = max(0, min(100, current_favorability + favorability_change))
                new_stage = compute_relationship_stage(new_favorability)
                npc_repo.update_favorability(target_npc_id, new_favorability, new_stage)

                # Update NPC memory
                npc_memory_row = npc_repo.get_memory(target_npc_id)
                memory = _build_memory_from_row(npc_memory_row) if npc_memory_row else NPCMemory(npc_id=target_npc_id)
                memory = update_memory(
                    memory,
                    user_message=filtered_input,
                    npc_response=dm_response.story,
                    npc_update=npc_update_dict,
                )
                npc_repo.update_memory(
                    target_npc_id,
                    summary=memory.summary,
                    recent_turns=[t.model_dump() for t in memory.recent_turns],
                    key_facts=[f.model_dump() for f in memory.key_facts],
                )

            # Update recent story history (keep last 5)
            updated_stories = list(player.recent_stories or [])
            updated_stories.append(story)
            if len(updated_stories) > 5:
                updated_stories = updated_stories[-5:]
            player = player.model_copy(update={"recent_stories": updated_stories})

            # Update quest lifecycle records (completed_tick + prune expired) now
            # that all state mutations, the tick advance, and any breakthrough are
            # final. Runs BEFORE persistence so the records are actually saved.
            # The visible list is derived from state; this only maintains records
            # for strike-through/expiry.
            player = world_engine.update_quests(player, world_state, bible)

            # Persist player state
            player_repo.update(player)

            # Build scene info for response
            scene_response = None
            if scene:
                npcs_in_scene_now = world_engine.get_npcs_in_scene(scene.id, player.tick)
                scene_response = {
                    "id": scene.id,
                    "name": scene.name,
                    "atmosphere": scene.atmosphere,
                    "description": scene.description,
                    "landmarks": scene.landmarks,
                    "npcs_present": npcs_in_scene_now,
                    "connections": scene.connections,
                }

            # Recompute the current objective from the final player state (a
            # breakthrough applied above may have advanced it) and surface it so
            # the status bar always shows the player's direction.
            goal = world_engine.current_goal(player, world_state, bible)
            goal_info = {"id": goal.id, "label": goal.label} if goal else {
                "id": None, "label": "暂无要务，随心而行",
            }

            # Panel refresh data (mirror of /player/status panel fields).
            # Hoist the present-id set once so the comprehension below doesn't
            # rebuild it on every iteration.
            present_ids = set(scene_response["npcs_present"]) if scene_response else set()

            # Build the rest of the response — everything except `story`,
            # which was already streamed as the first field.
            rest = {
                "intent": intent.value,  # Use our classified intent, not DM's
                "action_valid": dm_response.action_valid,
                "state_delta": dm_response.state_delta or {},
                "player": {
                    "name": player.name,
                    "current_scene": player.current_scene,
                    "tick": player.tick,
                    "level": player.level,
                    "spirit_power": player.spirit_power,
                    "hp": player.hp,
                    "max_hp": player.max_hp,
                    "attack": compute_attack(player),
                    "defense": compute_defense(player),
                },
                "scene": scene_response,
                "goal": goal_info,
                "npcs": [
                    {
                        "id": p["id"],
                        "favorability": p.get("favorability", 50),
                        "relationship_stage": p.get("relationship_stage", "陌生"),
                        "default_scene": p.get("default_scene", "outer_gate"),
                        "present": p["id"] in present_ids,
                    }
                    for p in npc_repo.get_all_profiles()
                ],
                "quests": world_engine.visible_quests(player, world_state, bible),
                "next_quest": ({"label": nq.label} if (nq := world_engine.next_quest(player, world_state, bible)) else None),
            }

            # Add world event info to response
            if world_event:
                rest["world_event"] = {
                    "id": world_event.id,
                    "name": world_event.name,
                    "narrative_hint": world_event.narrative_hint,
                }

            # Add intervention info to response
            if intervention:
                rest["intervention"] = {
                    "id": intervention.id,
                    "description": intervention.narrative_hint,
                    "options": intervention.intervene_options or [],
                }

            if combat_result:
                rest["combat"] = {
                    "enemy": encounter.name,
                    "dmg_to_enemy": combat_result.dmg_to_enemy,
                    "dmg_to_player": combat_result.dmg_to_player,
                    "result": combat_result.result,
                    "enemy_remaining_hp": combat_result.enemy_remaining_hp,
                    "player_remaining_hp": combat_result.player_remaining_hp,
                }

            if dm_response.breakthrough:
                rest["breakthrough"] = {
                    "from": dm_response.breakthrough.from_level,
                    "to": dm_response.breakthrough.to_level,
                }

            if dm_response.npc_update:
                # Use the same target NPC id determined earlier (named NPC if the
                # input named one, else first present, else default).
                target_npc_id_final = _resolve_talk_target(player, filtered_input, world_engine, npc_repo)
                profile_row = npc_repo.get_profile(target_npc_id_final)
                profile_dict = dict(profile_row) if profile_row else {}
                rest["npc"] = {
                    "favorability": profile_dict.get("favorability", 50),
                    "relationship_stage": profile_dict.get("relationship_stage", "陌生"),
                }

            # Close the story string, then splice in the rest. rest_json begins
            # with '{' — strip it so we append into the already-opened object.
            rest_json = json.dumps(rest, ensure_ascii=False)
            yield '",' + rest_json[1:]

        return StreamingResponse(response_generator(), media_type="application/json")

    return router


def _build_memory_from_row(row: dict) -> NPCMemory:
    """Build an NPCMemory from a database row dict."""
    recent_turns_data = row.get("recent_turns", "[]")
    if isinstance(recent_turns_data, str):
        recent_turns_data = json.loads(recent_turns_data)
    key_facts_data = row.get("key_facts", "[]")
    if isinstance(key_facts_data, str):
        key_facts_data = json.loads(key_facts_data)

    return NPCMemory(
        npc_id=row.get("npc_id", DEFAULT_NPC_PROFILE.id),
        summary=row.get("summary", "") or "",
        recent_turns=[NPCTurn(**t) for t in recent_turns_data] if recent_turns_data else [],
        key_facts=[KeyFact(**f) for f in key_facts_data] if key_facts_data else [],
    )