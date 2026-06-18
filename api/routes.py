"""Game endpoints — orchestrates the full classify→engine→world→dm→npc pipeline."""
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dm.client import LLMClient
from dm.contract import parse_dm_response_with_retry
from dm.prompt import build_dm_prompt
from engine.classify import classify_intent, classify_intent_llm
from engine.models import Intent, Player, Encounter, DEFAULT_ENCOUNTER, NPCInteraction, EventTrigger, WorldEvent, SCENE_MAP
from engine.rules import cultivate, resolve_combat, check_breakthrough, compute_attack, compute_defense, move
from engine.world import WorldEngine
from db.repository import PlayerRepository, NPCRepository
from npc.memory import update_memory, build_memory_context, compute_relationship_stage
from npc.models import NPCMemory, NPCTurn, KeyFact, DEFAULT_NPC_PROFILE
from safety.filter import pre_filter_input, post_filter_output


class ActionRequest(BaseModel):
    user_input: str


def create_router(
    llm_client: LLMClient,
    player_repo: PlayerRepository,
    npc_repo: NPCRepository,
    encounter: Encounter,
    world_engine: WorldEngine,
) -> APIRouter:
    """Create a FastAPI router with game endpoints, wiring all subsystems."""
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET /player/status — player status with scene info
    # ------------------------------------------------------------------
    @router.get("/player/status")
    def get_status():
        """Return current player status including scene information."""
        player = player_repo.get("p1")
        if player is None:
            return {"error": "Player not found"}

        # Enrich with scene details
        scene = world_engine.get_scene(player.current_scene)
        scene_info = None
        if scene:
            npcs_present = world_engine.get_npcs_in_scene(scene.id, player.tick)
            scene_info = {
                "id": scene.id,
                "name": scene.name,
                "atmosphere": scene.atmosphere,
                "npcs_present": npcs_present,
                "connections": scene.connections,
            }

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
            # Look up encounters for current scene
            encounter_ids = world_engine.get_encounters_for_scene(player.current_scene)
            if encounter_ids:
                # Use the first encounter available in this scene
                combat_result, player, _ = resolve_combat(player, encounter)
                if combat_result.result == "lose":
                    player = player.model_copy(update={"hp": 1})
            else:
                # No encounters in this scene — still resolve with default
                combat_result, player, _ = resolve_combat(player, encounter)
                if combat_result.result == "lose":
                    player = player.model_copy(update={"hp": 1})

        elif intent == Intent.MOVE:
            # Resolve move via world engine
            destination = params.get("destination", filtered_input)
            status, result = world_engine.resolve_scene_move(player, destination)
            if status == "ok":
                player = move(player, result)
            else:
                move_error = result  # Store the error message

        elif intent == Intent.TALK:
            pass  # NPC interaction handled in DM phase

        # Step 4: World layer — advance tick, check events, check NPC interactions
        player = world_engine.advance_tick(player)

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
            # Determine target NPC from scene rather than hardcoding
            npcs_in_scene = world_engine.get_npcs_in_scene(player.current_scene, player.tick)
            target_npc_id = npcs_in_scene[0] if npcs_in_scene else DEFAULT_NPC_PROFILE.id

            profile_row = npc_repo.get_profile(target_npc_id)
            npc_profile = dict(profile_row) if profile_row else {}

            npc_memory_row = npc_repo.get_memory(target_npc_id)
            if npc_memory_row:
                memory = _build_memory_from_row(npc_memory_row)
            else:
                memory = NPCMemory(npc_id=target_npc_id)

            npc_context = build_memory_context(memory)

        system_prompt, user_prompt = build_dm_prompt(
            player=player,
            intent=intent,
            combat_result=combat_result,
            breakthrough=breakthrough,
            npc_context=npc_context,
            recent_stories=player.recent_stories,
            scene=scene,
            world_event=world_event,
        )

        # Prepend the user's actual input to the prompt
        if user_prompt:
            user_prompt = f"{user_prompt}\n\n玩家：{filtered_input}"
        else:
            user_prompt = filtered_input

        # Call LLM
        try:
            raw_response = await llm_client.generate(system_prompt, user_prompt)
        except Exception:
            def error_response():
                yield json.dumps({
                    "intent": intent.value,
                    "action_valid": False,
                    "invalid_reason": "传信飞鸽被雷劈了",
                    "story": "【系统】传信飞鸽在半路被雷劈了，请重试。",
                    "state_delta": {},
                    "breakthrough": None,
                    "combat": None,
                    "npc_update": None,
                }, ensure_ascii=False)
            return StreamingResponse(error_response(), media_type="application/json")

        # Step 6: Post-filter output
        raw_response, _was_rewritten = post_filter_output(raw_response)

        # Step 7: Parse DM response
        dm_response = await parse_dm_response_with_retry(
            raw_response, client=llm_client,
            system_prompt=system_prompt, user_prompt=user_prompt,
        )

        # Ensure story is never empty — provide a fallback based on intent
        story = dm_response.story
        if not story or not story.strip():
            story_fallbacks = {
                Intent.CULTIVATE: f"{player.name}盘膝而坐，静静修炼，灵气缓缓涌入丹田。",
                Intent.TALK: f"{player.name}与身边的人交谈了几句。",
                Intent.FIGHT: f"{player.name}与妖兽展开了激烈的交锋！",
                Intent.MOVE: f"{player.name}向新的方向走去。",
                Intent.INTERVENE: f"{player.name}选择了介入。",
                Intent.OTHER: f"{player.name}的行动似乎没有引起什么变化。",
            }
            story = story_fallbacks.get(intent, f"{player.name}的行动似乎没有引起什么变化。")

        # Handle move error — if move was invalid, override the story
        if move_error:
            story = move_error
            dm_response = dm_response.model_copy(update={"action_valid": False, "invalid_reason": move_error})

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
            # Use the target NPC determined from the scene, or fallback
            npcs_in_scene = world_engine.get_npcs_in_scene(player.current_scene, player.tick)
            target_npc_id = npcs_in_scene[0] if npcs_in_scene else DEFAULT_NPC_PROFILE.id

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
                "npcs_present": npcs_in_scene_now,
                "connections": scene.connections,
            }

        # Build response
        response_data = {
            "intent": intent.value,  # Use our classified intent, not DM's
            "action_valid": dm_response.action_valid,
            "story": story,
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
        }

        # Add world event info to response
        if world_event:
            response_data["world_event"] = {
                "id": world_event.id,
                "name": world_event.name,
                "narrative_hint": world_event.narrative_hint,
            }

        # Add intervention info to response
        if intervention:
            response_data["intervention"] = {
                "id": intervention.id,
                "description": intervention.narrative_hint,
                "options": intervention.intervene_options or [],
            }

        if combat_result:
            response_data["combat"] = {
                "enemy": encounter.name,
                "dmg_to_enemy": combat_result.dmg_to_enemy,
                "dmg_to_player": combat_result.dmg_to_player,
                "result": combat_result.result,
                "enemy_remaining_hp": combat_result.enemy_remaining_hp,
                "player_remaining_hp": combat_result.player_remaining_hp,
            }

        if dm_response.breakthrough:
            response_data["breakthrough"] = {
                "from": dm_response.breakthrough.from_level,
                "to": dm_response.breakthrough.to_level,
            }

        if npc_update_dict:
            # Use the same target NPC id determined earlier
            npcs_in_scene_final = world_engine.get_npcs_in_scene(player.current_scene, player.tick)
            target_npc_id_final = npcs_in_scene_final[0] if npcs_in_scene_final else DEFAULT_NPC_PROFILE.id
            profile_row = npc_repo.get_profile(target_npc_id_final)
            profile_dict = dict(profile_row) if profile_row else {}
            response_data["npc"] = {
                "favorability": profile_dict.get("favorability", 50),
                "relationship_stage": profile_dict.get("relationship_stage", "陌生"),
            }

        # Return as streaming response
        def response_generator():
            yield json.dumps(response_data, ensure_ascii=False)

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