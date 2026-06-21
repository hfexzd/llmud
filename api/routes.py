"""Game endpoints — orchestrates the full classify→engine→world→dm→npc pipeline."""
import json
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dm.client import LLMClient
from dm.contract import parse_dm_response, extract_story_so_far
from dm.prompt import build_dm_prompt
from engine.classify import classify_intent, classify_intent_llm, resolve_npc_target
from engine.models import Intent, Player, Encounter, DEFAULT_ENCOUNTER, NPCInteraction, EventTrigger, WorldEvent, SCENE_MAP, next_spirit_threshold, DMResponse, WorldState, PHASE_0_BIBLE, SHOP_ITEMS, shop_list, CRAFT_RECIPES, craft_possible
from engine.rules import cultivate, resolve_combat, check_breakthrough, compute_attack, compute_defense, move
from engine.world import WorldEngine, npc_step, tension_tick, apply_world_delta
from db.repository import PlayerRepository, NPCRepository, WorldRepository
from npc.memory import update_memory, build_memory_context, compute_relationship_stage
from npc.models import NPCMemory, NPCTurn, KeyFact, DEFAULT_NPC_PROFILE
from safety.filter import pre_filter_input, post_filter_output


class ActionRequest(BaseModel):
    user_input: str
    offline_directive: str | None = None


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

    # Simple TTL cache: caches return value for `ttl` seconds.
    _cache: dict[str, tuple[float, dict]] = {}

    def _cached(key: str, ttl: float, factory):
        now = time.time()
        entry = _cache.get(key)
        if entry and (now - entry[0]) < ttl:
            return entry[1]
        result = factory()
        _cache[key] = (now, result)
        return result

    def _invalidate_cache(key: str = ""):
        if key:
            _cache.pop(key, None)
        else:
            _cache.clear()

    # ------------------------------------------------------------------
    # GET /player/status — player status with scene info
    # ------------------------------------------------------------------
    @router.get("/player/status")
    def get_status():
        """Return current player status including scene + panel data."""
        return _cached("status", 2.0, lambda: _build_status_response())

    def _build_status_response():
        """Build the full status response dict (extracted for caching)."""
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
                "shop": shop_list(scene.id) or None,
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
            "spirit_stones": player.spirit_stones,
            "auto_loot": player.auto_loot,
            "kills": player.kills,
            "weapon": player.weapon,
            "armor": player.armor,
            "attack": compute_attack(player),
            "defense": compute_defense(player),
            "scene": scene_info,
            "goal": goal_info,
            "npcs": npcs,
            "quests": world_engine.visible_quests(player, world_state, bible),
            "next_quest": next_quest_info,
            "next_threshold": next_spirit_threshold(player.level),
            "visited_count": len(player.visited_scenes or []),
        }

    # ------------------------------------------------------------------
    # GET /game/scenes — list all scenes
    # ------------------------------------------------------------------
    @router.get("/game/scenes")
    def list_scenes():
        """Return all scenes in the world (cached indefinitely, data is static)."""
        return _cached("scenes", 9999, lambda: {"scenes": [
            {"id": s.id, "name": s.name, "atmosphere": s.atmosphere,
             "connections": s.connections, "available_actions": s.available_actions}
            for s in SCENE_MAP.values()
        ]})

    # ------------------------------------------------------------------
    # POST /game/reset — reset all game state
    # ------------------------------------------------------------------
    @router.get("/game/version")
    def get_version():
        """Return version info."""
        return {"branch": "feat/living-world", "commits": 148, "tests": 277}

    @router.post("/game/reset")
    def reset_game():
        """Reset all game state: player, NPCs, and world to defaults."""
        from engine.models import DEFAULT_PLAYER
        player_repo.delete("p1")
        player_repo.save(DEFAULT_PLAYER)
        world_repo.delete("default")
        npc_repo.delete_all_memories()
        from api.app import seed_database
        seed_database(player_repo, npc_repo)
        _cache.clear()
        return {"status": "ok", "message": "游戏已重置 — 一切从零开始。"}

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
        _response_extras = [None]  # mutable container for closure-safe extra messages

        # Auto-attack shortcut: if in combat, "继续" = next attack round
        if filtered_input in ("继续", "继续攻击", "接着打") and player.active_enemy:
            intent = Intent.FIGHT

        if intent == Intent.CULTIVATE:
            player = cultivate(player)
            breakthrough = check_breakthrough(player)
            if breakthrough:
                player = player.model_copy(update={"level": breakthrough.to_level})

        # Repeated cultivation (连续修炼 does it 5x)
        if "连续修炼" in filtered_input:
            for _ in range(4):  # already did 1 above, do 4 more
                player = cultivate(player)
                bt = check_breakthrough(player)
                if bt:
                    player = player.model_copy(update={"level": bt.to_level})
                    breakthrough = bt

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
            # Track combo
            combo_count = getattr(game_action, "_combo", 0)
            if combat_result.result in ("ongoing", "win"):
                combo_count += 1
            else:
                combo_count = 0
            game_action._combo = combo_count
            if combo_count > 1:
                combat_result.combo = combo_count
            if combat_result.result == "lose":
                # Auto-heal: try to use healing item to survive
                from engine.rules import use_item as _use_heal
                for heal_item in ["灵芝", "凝露草", "灵鱼"]:
                    if heal_item in (player.inventory or []):
                        player, _ = _use_heal(player, heal_item)
                        combat_result.result = "ongoing"
                        break
            if combat_result.result == "lose":
                stones_lost = min(20, player.spirit_stones // 2)
                player = player.model_copy(update={
                    "hp": player.max_hp // 2,
                    "current_scene": "outer_gate",
                    "spirit_stones": player.spirit_stones - stones_lost,
                    "active_enemy": None,
                })
                _response_extras[0] = f"你被击败了！在柴房醒来，损失了{stones_lost}灵石。"

            # M7: record combat outcome for flow governor
            from engine.flow import FlowGovernor
            _flow_governor = getattr(game_action, "_flow_governor", FlowGovernor())
            game_action._flow_governor = _flow_governor
            outcome_map = {"win": "win", "lose": "struggle", "flee": "struggle", "ongoing": "fair"}
            _flow_governor.record_outcome(outcome_map.get(combat_result.result, "fair"))

            # Persist the enemy's remaining HP so the next attack continues the
            # fight; clear it once the beast is slain.
            if combat_result.result == "win":
                player = player.model_copy(update={"active_enemy": None})
                # Loot: spirit stones + spirit power
                stones_gained = 5 if player.auto_loot else 0
                spirit_gained = 2
                updates = {"spirit_power": player.spirit_power + spirit_gained, "kills": player.kills + 1}
                if stones_gained > 0:
                    updates["spirit_stones"] = player.spirit_stones + stones_gained
                player = player.model_copy(update=updates)
                if not _response_extras[0]:
                    msg = f"战斗胜利！灵力+{spirit_gained}"
                    if stones_gained > 0:
                        msg += f"，获得{stones_gained}灵石"
                    _response_extras[0] = msg + "。"
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
                    player = player.model_copy(update={
                        "visited_scenes": visited,
                        "spirit_stones": player.spirit_stones + 5,
                    })
                    _response_extras[0] = "探索了新场景！获得5灵石。"
            else:
                move_error = result  # Store the error message

        elif intent == Intent.TALK:
            pass  # NPC interaction handled in DM phase

        # Rest/heal
        if "休息" in filtered_input or "疗伤" in filtered_input:
            heal = min(20, player.max_hp - player.hp)
            if heal > 0:
                player = player.model_copy(update={"hp": player.hp + heal})
                _response_extras[0] = f"你休息片刻，恢复了{heal}点气血。"
                # Auto-use healing items if HP very low
                if player.hp < player.max_hp * 0.3 and player.inventory:
                    for healing_item in ["凝露草", "灵鱼"]:
                        if healing_item in (player.inventory or []):
                            from engine.rules import use_item
                            player, msg = use_item(player, healing_item)
                            _response_extras[0] += f" 自动使用了{healing_item}。"
                            break
            else:
                _response_extras[0] = "你精神饱满，无需休息。"

        # Training dummy at outer_gate (safe practice)
        if ("练功" in filtered_input or "练习" in filtered_input) and player.current_scene == "outer_gate":
            gain = 1
            player = player.model_copy(update={"spirit_power": player.spirit_power + gain})
            _response_extras[0] = f"你在练功场上练习招式，灵力略有精进（灵力+{gain}）。"

        # NPC gift system: give item to NPC to increase favorability
        gift_message = None
        import re as _re
        item_names = "|".join(i.name for i in PHASE_0_BIBLE.items)
        gift_match = _re.match(r"(?:给|送|赠)(.+?)(" + item_names + r")", filtered_input)
        if gift_match and player.inventory:
            npc_name = gift_match.group(1)
            from engine.models import ALL_NPC_PROFILES
            target = next((p for p in ALL_NPC_PROFILES if p.name in npc_name or npc_name in p.name), None)
            if target:
                item_name = gift_match.group(2)
                if item_name in player.inventory:
                    new_inv = list(player.inventory)
                    new_inv.remove(item_name)
                    player = player.model_copy(update={"inventory": new_inv})
                    profile_row = npc_repo.get_profile(target.id)
                    if profile_row:
                        cur_fav = profile_row.get("favorability", 50)
                        rarity = next((s.rarity for s in PHASE_0_BIBLE.items if s.name == item_name), "凡")
                        gift_value = 10 if rarity == "灵" else 5
                        # NPC gift preferences
                        _item_cats = {"灵芝":"灵材","蛇胆":"灵材","洗髓丹":"丹药","灵草":"灵材","凝露草":"灵材","聚气丹":"丹药","解毒丹":"丹药","灵鱼":"灵材","湖心珠":"法器","青锋剑":"法器","布甲":"防具"}
                        npc_likes = {"medicine_elder": ["灵材", "丹药"], "linwaner": ["灵材"], "chenhao": ["法器"], "old_yang": ["丹药"]}
                        liked = [cat for cat in (npc_likes.get(target.id) or []) if cat in (_item_cats.get(item_name) or [])]
                        if liked:
                            gift_value += 3
                            gift_message = f"你将{item_name}送给了{target.name}。[好感度+{gift_value}！对方很喜欢]"
                        else:
                            gift_message = f"你将{item_name}送给了{target.name}。[好感度+{gift_value}]"
                        new_fav = min(100, cur_fav + gift_value)
                        old_stage = profile_row.get("relationship_stage", "陌生")
                        new_stage = compute_relationship_stage(new_fav)
                        if new_stage != old_stage and _response_extras:
                            _response_extras[0] = (_response_extras[0] or "") + f" 与{target.name}的关系提升为【{new_stage}】！"
                        npc_repo.update_favorability(target.id, new_fav, new_stage)

        # Bribery: give spirit stones to NPC
        if ("贿赂" in filtered_input or "打点" in filtered_input) and player.spirit_stones >= 10:
            from engine.models import ALL_NPC_PROFILES as _ALL_NPCS
            bribe_target = next((p for p in _ALL_NPCS if p.name in filtered_input), None)
            if bribe_target:
                profile_row = npc_repo.get_profile(bribe_target.id)
                if profile_row:
                    cur_fav = profile_row.get("favorability", 50)
                    new_fav = min(100, cur_fav + 5)
                    old_stage = profile_row.get("relationship_stage", "陌生")
                    new_stage = compute_relationship_stage(new_fav)
                    if new_stage != old_stage and _response_extras:
                        _response_extras[0] = (_response_extras[0] or "") + f" 与{bribe_target.name}的关系提升为【{new_stage}】！"
                    npc_repo.update_favorability(bribe_target.id, new_fav, new_stage)
                    player = player.model_copy(update={"spirit_stones": player.spirit_stones - 10})
                    _response_extras[0] = f"你给了{bribe_target.name}10灵石。[好感度+5]"

        # Item search
        if "查找" in filtered_input and player.inventory:
            search_term = filtered_input.split("查找")[-1].strip()
            if search_term:
                found = [i for i in player.inventory if search_term in i]
                if found:
                    _response_extras[0] = f"找到：{'、'.join(found)}（共{len(found)}件）"
                else:
                    _response_extras[0] = f"未找到包含「{search_term}」的物品。"

        # Auto-loot toggle
        if "自动拾取" in filtered_input or "自动收集" in filtered_input:
            player = player.model_copy(update={"auto_loot": not player.auto_loot})
            _response_extras[0] = f"自动拾取已{'开启' if player.auto_loot else '关闭'}。"

        # Help system
        help_message = None
        if filtered_input in ("帮助", "help", "？", "?"):
            # Scene-specific tip
            scene_tips = {
                "outer_gate": "💡 外门清静，适合修炼。与杨老交谈或许能获得指点。",
                "inner_gate": "💡 林婉儿师姐似有心事，试着和她聊聊。",
                "bamboo_forest": "💡 竹林深处有妖兽出没，小心战斗。",
                "market": "💡 集市可以买卖物品。试试「购买聚气丹」。",
                "mountain_range": "💡 山脉深处危险重重，准备好再探索。",
                "spirit_valley": "💡 药老精通炼丹，收集材料来找他炼制丹药。",
                "misty_lake": "💡 湖边隐士深不可测，或许能学到什么。",
            }
            scene_tip = scene_tips.get(player.current_scene, "")
            help_message = (
                (scene_tip + "\n\n") if scene_tip else "") + (
                "【基本指令】\n"
                "• 修炼 — 提升灵力\n"
                "• 探索 — 探索当前场景\n"
                "• 战斗 — 与敌人战斗\n"
                "• 去[地名] — 移动到其他场景\n"
                "• 和[人名]搭话 — 与NPC交谈\n\n"
                "【物品】\n"
                "• 使用[物品] — 使用消耗品\n"
                "• 查看[物品] — 查看物品详情\n"
                "• 装备[物品] — 装备武器/防具\n"
                "• 卸下[物品] — 卸下装备\n"
                "• 给[人名][物品] — 赠送礼物\n"
                "• 丢弃[物品] — 丢弃物品\n\n"
                "【交易/炼制】\n"
                "• 购买[物品] — 在集市购买\n"
                "• 出售[物品] — 出售物品\n"
                "• 炼制[丹药] — 在灵药谷炼丹\n\n"
                "【其他】\n"
                "• 休息/疗伤 — 恢复气血\n"
                "• 帮助 — 显示此帮助\n"
                "• 自动拾取 — 切换战斗自动拾取灵石"
            )

        # Response extras (mutable container to avoid closure scoping issues)
        _response_extras = [None]

        # Helper to set _response_extras[0]
        def _set_item_use(msg):
            _response_extras[0] = msg

        # Reset response extras for this action
        _response_extras[0] = None

        # Item/NPC inspection: if input contains "查看" + name, show description
        item_inspect_message = None
        if "查看" in filtered_input and not _response_extras[0]:
            for part in filtered_input.split("查看"):
                part = part.strip()
                if part and len(part) >= 2:
                    # Check items first
                    for spec in PHASE_0_BIBLE.items:
                        if spec.name in part:
                            rarity_cn = {"凡": "凡品", "灵": "灵品", "玄": "玄品", "天": "天品"}
                            r = rarity_cn.get(spec.rarity, spec.rarity)
                            item_inspect_message = f"【{spec.name}】（{r} {spec.kind}）{spec.lore}（效果：{spec.effect}）"
                            break
                    # Check NPCs
                    if not item_inspect_message:
                        from engine.models import ALL_NPC_PROFILES
                        for npc in ALL_NPC_PROFILES:
                            if npc.name in part:
                                item_inspect_message = f"【{npc.name}】{npc.persona}（动机：{npc.motive}）"
                                break
                    break

        # Equipment: equip/unequip items
        equip_message = None
        if "装备" in filtered_input or "佩戴" in filtered_input:
            for kw in ("装备", "佩戴"):
                if kw in filtered_input:
                    part = filtered_input.split(kw)[-1].strip()
                    if part and part in (player.inventory or []):
                        new_inv = list(player.inventory)
                        new_inv.remove(part)
                        from engine.rules import _equip_bonus, _WEAPON_BONUS, _ARMOR_BONUS
                        wep_bonus = _equip_bonus(part, _WEAPON_BONUS)
                        arm_bonus = _equip_bonus(part, _ARMOR_BONUS)
                        updates = {"inventory": new_inv}
                        if wep_bonus > 0:
                            if player.weapon:
                                new_inv.append(player.weapon)
                            updates["weapon"] = part
                            updates["inventory"] = new_inv
                            equip_message = f"装备了{part}（攻击+{wep_bonus}）"
                        elif arm_bonus > 0:
                            if player.armor:
                                new_inv.append(player.armor)
                            updates["armor"] = part
                            updates["inventory"] = new_inv
                            equip_message = f"装备了{part}（防御+{arm_bonus}）"
                        if equip_message:
                            player = player.model_copy(update=updates)
                        break
                    break
        # Unequip
        if "卸下" in filtered_input or "取下" in filtered_input:
            for slot in ("weapon", "armor"):
                current = getattr(player, slot, None)
                if current and (current in filtered_input or slot in filtered_input):
                    new_inv = list(player.inventory or []) + [current]
                    player = player.model_copy(update={"inventory": new_inv, slot: None})
                    slot_name = "武器" if slot == "weapon" else "防具"
                    equip_message = f"卸下了{current}（{slot_name}栏已空）"
                    break

        # Discard items
        if "丢弃" in filtered_input or "扔掉" in filtered_input:
            for kw in ("丢弃", "扔掉"):
                if kw in filtered_input:
                    part = filtered_input.split(kw)[-1].strip()
                    if part and part in (player.inventory or []):
                        # Rare items need confirmation (type 确认丢弃 to proceed)
                        rare_items = {"灵芝", "蛇胆", "湖心珠", "洗髓丹", "青锋剑", "布甲"}
                        if part in rare_items and "确认" not in filtered_input:
                            _response_extras[0] = f"⚠️ {part}是稀有物品，再次输入「确认丢弃{part}」以确认。"
                        else:
                            new_inv = list(player.inventory)
                            new_inv.remove(part)
                            player = player.model_copy(update={"inventory": new_inv})
                            _response_extras[0] = f"丢弃了{part}。"
                    break

        # Alchemy: craft items at spirit_valley
        craft_message = None
        if "炼制" in filtered_input and player.current_scene == "spirit_valley":
            craftable = craft_possible("spirit_valley", player.inventory or [])
            for recipe in craftable:
                if recipe["name"] in filtered_input:
                    new_inv = list(player.inventory)
                    for ing in recipe["ingredients"]:
                        new_inv.remove(ing)
                    new_inv.append(recipe["result"])
                    player = player.model_copy(update={"inventory": new_inv})
                    craft_message = f"炼制了{recipe['result']}！"
                    break
            if not craft_message:
                craft_message = "材料不足，无法炼制。"

        # Buy/sell at market
        shop_message = None
        if "购买" in filtered_input and player.current_scene == "market":
            for s in SHOP_ITEMS:
                if s["name"] in filtered_input and player.spirit_stones >= s["price"]:
                    new_inv = list(player.inventory or []) + [s["name"]]
                    player = player.model_copy(update={
                        "inventory": new_inv,
                        "spirit_stones": player.spirit_stones - s["price"],
                    })
                    shop_message = f"购买了{s['name']}（花费{s['price']}灵石）"
                    break
        if ("出售" in filtered_input or "卖掉" in filtered_input) and player.inventory:
            for name in list(player.inventory):
                if name in filtered_input:
                    sell_price = 0
                    for s in SHOP_ITEMS:
                        if s["name"] == name:
                            sell_price = s["price"] // 2
                            break
                    if sell_price > 0:
                        new_inv = list(player.inventory)
                        new_inv.remove(name)
                        player = player.model_copy(update={
                            "inventory": new_inv,
                            "spirit_stones": player.spirit_stones + sell_price,
                        })
                        shop_message = f"出售了{name}（获得{sell_price}灵石）"
                    break

        # Item usage: if input contains "使用" + item name, consume from inventory
        if "使用" in filtered_input:
            from engine.rules import use_item
            confirmed = "确认使用" in filtered_input
            for part in filtered_input.split("使用"):
                part = part.strip()
                if part and len(part) >= 2:
                    new_p, msg = use_item(player, part, confirmed=confirmed)
                    if new_p != player:  # item was consumed
                        player = new_p
                        _response_extras[0] = msg
                        break

        # Step 4: World layer — advance tick, check events, check NPC interactions
        player = world_engine.advance_tick(player)

        # World layer scaffold (M1): track emergent world state alongside the
        # player. Rule-driven npc_step (NPCs follow their schedule) + a no-op
        # tension_tick stub. Behavior is unchanged — world state is NOT yet fed
        # to the DM prompt (that arrives in M3 with the outcome resolver).
        world_state = world_repo.get("default") or WorldState()
        bible = PHASE_0_BIBLE  # M5 swaps in LLM-regenerated bibles; M1 is always phase-0

        # M6: offline catch-up — if player was away, advance world before pipeline
        from datetime import datetime, timezone
        from engine.offline import advance_offline
        now_dt = datetime.now(timezone.utc)
        last_seen = player.last_seen
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        seconds_offline = (now_dt - last_seen).total_seconds()
        offline_summary_for_response = None
        dir_from_request = getattr(request, 'offline_directive', None)
        if dir_from_request and dir_from_request in ("闭关", "历练", "静养") and dir_from_request != player.offline_directive:
            player = player.model_copy(update={"offline_directive": dir_from_request})

        if seconds_offline > 60:  # more than 1 minute offline
            player, world_state, offline_summary = advance_offline(
                player, world_state, bible, now=now_dt, directive=player.offline_directive,
            )
            player_repo.update(player)
            world_repo.save(world_state)
            offline_summary_for_response = offline_summary

        world_state = npc_step(world_state, bible, player.tick)
        world_state = tension_tick(world_state, bible, player)
        world_state = world_state.model_copy(update={"tick": player.tick})
        world_repo.save(world_state)

        # M5: check milestone regen (must run before ending check)
        from engine.world import check_regen, merge_bible, REGEN_THRESHOLD
        if check_regen(world_state, bible) and llm_client is not None:
            from worldgen.generator import generate_bible
            new_bible = await generate_bible(
                world_state.resolved_tensions, world_state, player, bible, llm_client,
            )
            if new_bible is not None:
                world_state = merge_bible(world_state, new_bible)
                bible = new_bible
                world_state = world_state.model_copy(update={"phase_id": new_bible.phase_id})
                world_repo.save(world_state)

        # M4: check ending after world tick
        from engine.ending import check_ending
        ending_id = check_ending(world_state, bible, player)
        if ending_id:
            world_state = world_state.model_copy(update={"sealed": True, "ending": ending_id})
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

        # Grant items for certain events (event rewards)
        event_id = world_event.id if world_event else None
        if event_id and player.inventory is not None:
            reward_map = {
                "elder_first_meeting": "凝露草",
                "valley_guardian": "蛇胆",
                "lake_turtle_awakening": "湖心珠",
                "spirit_herb": "灵草",
            }
            if event_id in reward_map and reward_map[event_id] not in player.inventory:
                new_inv = list(player.inventory) + [reward_map[event_id]]
                player = player.model_copy(update={"inventory": new_inv})
                if not _response_extras[0]:
                    _response_extras[0] = f"🎁 获得了{reward_map[event_id]}！"

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
            nonlocal player, world_state
            # Prefix: open the JSON object and the story string.
            yield '{"story":"'

            # M3: will be set after validator runs in the else branch
            world_delta_for_response = None

            # M4: if world is sealed, use finale prompt and skip normal LLM
            if world_state.sealed and world_state.ending:
                from dm.prompt import build_ending_prompt
                from engine.models import TERMINAL_ARCHETYPES
                ending_system, _ = build_ending_prompt(
                    world_state.ending,
                    world_state.resolved_tensions,
                    player,
                    bible,
                )
                story = ""
                if llm_client is not None:
                    try:
                        story = await llm_client.generate(ending_system, user_prompt)
                        story, _ = post_filter_output(story)
                    except Exception:
                        story = f"【终章】{player.name}的旅程走到了终点。"
                dm_response = DMResponse(
                    intent=intent, action_valid=True,
                    story=story,
                )
                yield json.dumps(story, ensure_ascii=False)[1:-1]
            elif move_error:
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

                    # --- M3: validate + retry ---
                    from engine.validator import validate_dm_proposal, scan_story_for_canon_violations

                    clamped, violations, should_retry = validate_dm_proposal(
                        dm_response, world_state, bible, player,
                    )

                    # Post-hoc story scan (log only — story was already streamed)
                    story_violations = scan_story_for_canon_violations(story, bible)
                    if story_violations:
                        print(f"[validator] story canon violations: {story_violations}")

                    if should_retry and llm_client is not None:
                        # Build retry prompt with violation context
                        violation_text = "\n".join(f"- {v}" for v in violations)
                        retry_system = (
                            system_prompt
                            + f"\n\n【校验失败·请重试】你的回复中world_delta存在以下问题，请修正后重新生成完整JSON（不要包含任何解释文字，只返回纯JSON）：\n{violation_text}"
                        )
                        try:
                            retry_raw = await llm_client.generate(retry_system, user_prompt)
                            retry_raw, _ = post_filter_output(retry_raw)
                            retry_response = parse_dm_response(retry_raw)
                            # Re-validate the retry
                            clamped, violations, _ = validate_dm_proposal(
                                retry_response, world_state, bible, player,
                            )
                            # Use the retry's story if it's non-empty
                            if retry_response.story and retry_response.story.strip():
                                story = retry_response.story
                                dm_response = retry_response.model_copy(update={"story": story})
                            else:
                                dm_response = retry_response
                            # Re-scan story
                            story_violations2 = scan_story_for_canon_violations(story, bible)
                            if story_violations2:
                                print(f"[validator] retry story canon violations: {story_violations2}")
                        except Exception:
                            # Retry failed — keep the clamped original
                            pass

                    # Apply validated + clamped world_delta to world_state
                    if clamped.world_delta:
                        world_state = apply_world_delta(world_state, clamped.world_delta)
                        # Re-run tension_tick so tension states reflect DM-proposed
                        # progress/pressure nudges (e.g. a tension might now resolve
                        # because its resolution path condition is met).
                        world_state = tension_tick(world_state, bible, player)
                        world_state = world_state.model_copy(update={"tick": player.tick})
                        world_repo.save(world_state)

                    world_delta_for_response = clamped.world_delta

                    if violations:
                        print(f"[validator] violations: {violations}")

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

            # Quest completion reward: all 4 done -> 洗髓丹
            if (player.quests and len([q for q in player.quests if q.status == "completed"]) >= 4
                    and "洗髓丹" not in (player.inventory or [])):
                new_inv = list(player.inventory or []) + ["洗髓丹"]
                player = player.model_copy(update={"inventory": new_inv})
                if not _response_extras[0]:
                    _response_extras[0] = "🎉 所有所务完成！获得洗髓丹！"

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
                    "shop": shop_list(scene.id) or None,
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
                "world_delta": world_delta_for_response,
                "player": {
                    "name": player.name,
                    "current_scene": player.current_scene,
                    "tick": player.tick,
                    "level": player.level,
                    "spirit_power": player.spirit_power,
                    "hp": player.hp,
                    "max_hp": player.max_hp,
                    "weapon": player.weapon,
                    "armor": player.armor,
                    "spirit_stones": player.spirit_stones,
                    "inventory": player.inventory,
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

            # M6: surface offline catch-up summary if player was away
            if offline_summary_for_response:
                rest["offline_summary"] = offline_summary_for_response

            # Surface item use message if an item was consumed
            if _response_extras[0]: rest["item_use"] = _response_extras[0]

            # Surface item inspect message if an item was examined
            if item_inspect_message:
                rest["item_inspect"] = item_inspect_message

            # Surface gift message if an item was given to an NPC
            if gift_message:
                rest["item_use"] = gift_message

            # Surface equip message
            if equip_message:
                rest["item_use"] = equip_message

            # Surface shop message
            if shop_message:
                rest["item_use"] = shop_message

            # Surface craft message
            if craft_message:
                rest["item_use"] = craft_message

            # Surface help message
            if help_message:
                rest["help"] = help_message

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

            # M4: surface ending info if world is sealed
            if world_state.ending:
                from engine.models import TERMINAL_ARCHETYPES
                archetype = next((a for a in TERMINAL_ARCHETYPES if a.id == world_state.ending), None)
                rest["ending"] = {
                    "id": world_state.ending,
                    "name": archetype.name if archetype else world_state.ending,
                }

            # Close the story string, then splice in the rest. rest_json begins
            # with '{' — strip it so we append into the already-opened object.
            rest_json = json.dumps(rest, ensure_ascii=False)
            yield '",' + rest_json[1:]

        # Invalidate status cache after any action
        _invalidate_cache("status")

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