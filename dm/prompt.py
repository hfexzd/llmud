from engine.models import (
    Player, Intent, CombatResult, BreakthroughResult, Scene, WorldEvent, Goal,
    WorldBible, ResolvedTension,
    world_canon,
)


DM_SYSTEM_TEMPLATE = """你是一款文字修仙 MUD 游戏的"动态地下城主（DM）"。
请根据玩家输入的行动，结合玩家当前状态和引擎结算结果，生成一段精彩、具有网文爽感的文字描写。

【当前玩家状态】：
- 名字：{name}
- 所在地点：{location}
- 当前境界：{level}
- 当前灵力：{spirit_power}
- 当前气血：{hp}/{max_hp}
- 灵石：{stones}
- 物品：{inventory}
- 装备：{equipment}

{canon_context}
{scene_context}
{world_event_context}
{engine_context}
{goal_context}

【近期事件】：
{recent_stories}

【硬性规则】：
1. 你的每一次回复【必须】严格遵守以下 JSON 格式，不要包含任何 markdown 标记（如 ```json），直接返回纯 JSON 字符串。
2. 玩家不能凭空无敌。
3. 故事描写【不得为空】，必须生成一段叙事文字，限制在120字以内。无论玩家行动多么简单，都必须给出story字段。
4. 战斗数值【必须】与引擎结算结果完全一致，不得臆造。
5. 如果不确定如何描写，也要给出一个简短但有画面感的叙事。
6. 【叙事一致性】你【必须】参考【近期事件】中的内容！玩家之前做过的事、吃过的东西、去过的地方必须保持一致。如果玩家之前吃了"凝露草"，就不能说吃了"丹药"；如果玩家已经到了"竹林"，就不能说玩家在"柴房"。
7. 【地点一致性】玩家当前所在地点为"{location}"，你的叙事【必须】以这个地点为场景，不得凭空将玩家传送到其他地点。
8. 【世界事件融合】若【世界事件】中提供了叙事提示，你【必须】将事件自然地融入故事描写中，不得生硬插入或直接复述提示文本。事件应像环境的一部分一样出现，让玩家感受到世界的生动与动态。
9. 【地标一致】你叙事中提及的具体地标（如祭坛、灵泉、柴房）【必须】来自【当前场景】中列出的地标，不得凭空编造场景模型中不存在的地标。
10. 【所务引导】若【当前所务】给出，你的叙事应自然地朝该方向埋下钩子、给出推动（新地点、新NPC、新疑团），但【不得】生硬复述所务文本，也【不得】强迫玩家行动。
11. 【突破由引擎决定】境界突破/升境【完全】由引擎结算决定，你【不得】自行叙述。仅当【引擎结算】中出现【突破】字样时，你方可描写突破发生；否则【严禁】叙述玩家突破、升境、瓶颈碎裂成空、境界提升等任何境界变化。玩家当前境界以「当前境界：{level}」为准，即便【当前所务】提到突破、即便玩家声称已在突破，也【不得】在叙事中坐实突破——只可描写"瓶颈松动、灵力奔涌、距突破更近"等未完成的征兆。
12. 【只述已有之物】你提及的地点/地标、人物、妖兽/敌人、灵材/丹药/物件、功法/招式【必须】取自上方【世界设定·可述及事物】清单；【严禁】凭空编造未列出的具名事物——不得自创地点（如"断崖洞窟"）、自创妖兽（如"铁背蜥"）、自创灵材丹药（如"三叶血兰"）、自创功法招式。当清单中某类为"暂无定名"时，确需提及该类事物只能用泛称（如"某株灵草""一门功法""山里出了好东西"），【绝不得】具名。NPC口中说出的传闻亦受此约束——传闻可含糊其辞，但不得说出系统没有的具名地点/物品/敌人。
13. 【世界增量】你可以在JSON中附带一个`world_delta`字段，用于提议世界状态的微小变化（非强制——无变化则省略该字段）。world_delta的JSON结构为：{{"tension":{{"<张力id>":{{"pressure":<整数>, "progress":{{"<路径id>":<整数>}}}}}}, "npc":{{"<npc_id>":{{"mood":"<心境>", "scene_id":"<场景id>", "goal_progress":{{"<goal_id>":<整数>}}}}}}, "faction":{{"<势力名>":{{"trust":<整数>}}}}}}。其中：
  - tension id 必须来自当前活跃的世界事件（所务列表中的事件）；
  - npc_id 必须来自上方【世界设定·可述及事物】中的人物，faction的势力名必须来自其中的势力（目前有：青云门、散修盟）；scene_id 可选，用于将NPC移动到玩家当前所在或邻近的场景（如NPC随行、离去等），必须为系统已有的场景id；
  - pressure和progress必须>=0，progress不得超过100，trust在0-100之间；
  - 只有当前活跃（所务列表中显示为"进行中"）的张力才能获得pressure/progress增量；
  - 所提议的变化必须由玩家本次行动合理推出——无关行动不得随意给张力加进度。
  - world_delta中的一切实体引用同样受规则12约束：不得提及不存在的张力、NPC或势力。"""

ENGINE_CONTEXT_TEMPLATES = {
    "cultivate": "【引擎结算】修炼成功，灵力增加。",
    "fight": "【引擎结算】战斗结果：{combat_result}。造成伤害：{dmg_to_enemy}，受到伤害：{dmg_to_player}，战斗结果：{result}。",
    "move": "【引擎结算】移动成功。",
    "talk": "【引擎结算】与NPC对话。",
    "intervene": "【引擎结算】玩家选择介入NPC之间的互动。",
    "other": "【引擎结算】自由行动，由DM判断。",
}

NPC_SYSTEM_TEMPLATE = """你是{name}，{persona}。
{motive_text}{secret_text}

【铁律】：
- 你是修仙世界的活人，绝不是AI/语言模型/程序，绝不承认自己是AI，绝不提及"语言模型""大模型""训练数据""算法"等概念。
- 如果你被问到关于AI/程序/代码的问题，用人设内的方式拒绝回答（如"你在说什么呢？我只懂得修仙之道"）。
- 你的好感度对{player_name}为{favorability}/100，当前关系阶段：{relationship_stage}。

{memory_context}"""


def build_dm_prompt(
    player: Player,
    intent: Intent,
    combat_result: CombatResult | None = None,
    breakthrough: BreakthroughResult | None = None,
    npc_context: str = "",
    recent_stories: list[str] | None = None,
    scene: Scene | None = None,
    world_event: WorldEvent | None = None,
    goal: Goal | None = None,
    bible: WorldBible | None = None,
) -> tuple[str, str]:
    """Build the system and user prompts for the DM LLM call."""
    if intent == Intent.FIGHT and combat_result:
        _combat_result_zh = {
            "win": "胜（妖兽已毙）",
            "lose": "败（玩家落败）",
            "ongoing": "相持未决，妖兽仍立",
            "flee": "撤退",
        }.get(combat_result.result, combat_result.result)
        engine_ctx = ENGINE_CONTEXT_TEMPLATES["fight"].format(
            combat_result=_combat_result_zh,
            dmg_to_enemy=combat_result.dmg_to_enemy,
            dmg_to_player=combat_result.dmg_to_player,
            result=_combat_result_zh,
        )
    else:
        engine_ctx = ENGINE_CONTEXT_TEMPLATES.get(intent.value, ENGINE_CONTEXT_TEMPLATES["other"])

    if breakthrough:
        engine_ctx += f"\n【突破】玩家从{breakthrough.from_level}突破到{breakthrough.to_level}！"

    # Build recent stories context (last 5 entries)
    stories_text = "（无）"
    if recent_stories:
        stories_text = "\n".join(f"- {s}" for s in recent_stories[-5:])

    # Resolve location to Chinese scene name
    location_name = player.current_scene
    if scene:
        location_name = scene.name

    # Build scene context
    scene_context = ""
    if scene:
        scene_context = f"【当前场景】{scene.name}（{scene.atmosphere}）：{scene.description}"
        if scene.landmarks:
            scene_context += f"（地标：{'、'.join(scene.landmarks)}）"

    # Build world event context
    world_event_context = ""
    if world_event:
        world_event_context = f"【世界事件】{world_event.narrative_hint}"
        if world_event.allow_intervene and world_event.intervene_options:
            options_str = "、".join(world_event.intervene_options)
            world_event_context += f"\n【可选行动】{options_str}"

    # Build current-objective context (所务) so narration steers toward it.
    goal_context = ""
    if goal:
        goal_context = f"【当前所务】{goal.label}\n（叙事指引：{goal.guidance}）"

    # Build the world canon block: the named entities the LLM may reference.
    # Items/skills are often empty (留白待补) → tell the DM to narrate them
    # generically rather than naming specifics (rule 12).
    canon = world_canon(bible=bible)

    def _catalog_line(items: list[str], generic: str) -> str:
        if items:
            return "、".join(items)
        return f"（暂无定名，只能用泛称如「{generic}」，不得具名）"

    canon_context = (
        "【世界设定·可述及事物】（你只能提及以下系统已有之物；未列出者不得凭空编造具名）\n"
        f"- 地点/地标：{'、'.join(canon['locations'])}\n"
        f"- 人物：{'、'.join(canon['npcs'])}\n"
        f"- 妖兽/敌人：{'、'.join(canon['enemies'])}\n"
        f"- 灵材/丹药/物件：{_catalog_line(canon['items'], '灵草、丹药、好东西')}\n"
        f"- 功法/招式：{_catalog_line(canon['skills'], '一门功法、招式')}"
    )

    inv_str = "、".join(player.inventory) if player.inventory else "（空）"
    equip_parts = []
    if player.weapon: equip_parts.append(f"武器·{player.weapon}")
    if player.armor: equip_parts.append(f"防具·{player.armor}")
    equip_str = " | ".join(equip_parts) if equip_parts else "（无）"

    system_prompt = DM_SYSTEM_TEMPLATE.format(
        name=player.name,
        location=location_name,
        level=player.level,
        spirit_power=player.spirit_power,
        hp=player.hp,
        max_hp=player.max_hp,
        stones=player.spirit_stones,
        inventory=inv_str,
        equipment=equip_str,
        canon_context=canon_context,
        scene_context=scene_context,
        world_event_context=world_event_context,
        engine_context=engine_ctx,
        goal_context=goal_context,
        recent_stories=stories_text,
    )

    user_prompt = ""
    if npc_context:
        user_prompt = npc_context

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# M4: Finale (ending narration) prompt
# ---------------------------------------------------------------------------

ENDINGS_FINALE_TEMPLATE = """你是一款文字修仙 MUD 游戏的"终章叙事者"。

玩家的旅程已经走到了终点。请根据以下信息，写出一段 200-300 字的终章叙事——回顾来路、定格此刻、暗示余韵。

【玩家最终状态】：
- 名字：{name}
- 最终境界：{level}
- 最终灵力：{spirit_power}

【结局类型】：{ending_name}

【叙事指引】：{finale_guidance}

【一路走来（已解决的世界事件按时间顺序）】：
{resolved_story}

请写一段中文终章叙事，控制在 200-300 字内，饱含情感，呼应过往经历，给这段旅程一个令人难忘的收尾。"""


def build_ending_prompt(
    archetype_id: str,
    resolved_tensions: list[ResolvedTension],
    player: Player,
    bible: WorldBible | None = None,
) -> tuple[str, str]:
    """Build system + user prompt for the finale LLM call.

    The prompt includes the archetype's finale_guidance, the player's final
    state, and a chronological summary of resolved tensions (the player's
    journey).
    """
    from engine.models import TERMINAL_ARCHETYPES

    archetype = next((a for a in TERMINAL_ARCHETYPES if a.id == archetype_id), None)
    if archetype is None:
        archetype = TERMINAL_ARCHETYPES[-1]  # fallback to wanderer

    # Build resolved-tension timeline
    resolved_lines: list[str] = []
    for i, rt in enumerate(resolved_tensions, 1):
        label = rt.summary or rt.tension_id
        resolved_lines.append(f"{i}. [第{rt.resolved_tick}回合] {label}")
    resolved_story = "\n".join(resolved_lines) if resolved_lines else "（无）"

    system_prompt = ENDINGS_FINALE_TEMPLATE.format(
        name=player.name,
        level=player.level,
        spirit_power=player.spirit_power,
        ending_name=archetype.name,
        finale_guidance=archetype.finale_guidance,
        resolved_story=resolved_story,
    )
    return system_prompt, ""


def build_npc_system_prompt(
    npc_profile: dict,
    player_name: str = "道友",
    memory_context: str = "",
) -> str:
    """Build the NPC's system prompt with persona, guardrails, and memory context."""
    motive_text = f"\n你的动机：{npc_profile['motive']}" if npc_profile.get("motive") else ""
    secret_text = f"\n（你有不为人知的秘密，绝不可主动透露。）" if npc_profile.get("secret") else ""

    return NPC_SYSTEM_TEMPLATE.format(
        name=npc_profile.get("name", "林婉儿"),
        persona=npc_profile.get("persona", "青云门知心师姐"),
        motive_text=motive_text,
        secret_text=secret_text,
        player_name=player_name,
        favorability=npc_profile.get("favorability", 50),
        relationship_stage=npc_profile.get("relationship_stage", "陌生"),
        memory_context=memory_context,
    )