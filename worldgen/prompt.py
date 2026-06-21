"""Prompt templates for LLM world generation (M5).

Built from resolved_tensions history + current world state + player state.
The LLM produces a new WorldBible JSON for the next milestone phase.
"""

from engine.models import WorldState, Player, ResolvedTension, WorldBible


WORLDGEN_SYSTEM_TEMPLATE = """你是一个修仙世界生成器。你的任务是根据"本轮世界历史"生成下一阶段的世界圣经（WorldBible）。

世界圣经是一份JSON，包含以下字段：
- phase_title: str — 本阶段的标题（如"筑基风云"）
- scenes: list[SceneSpec] — 场景列表。每个场景有：id, name, description, atmosphere, connections, available_actions, encounter_ids, npc_ids, landmarks
- factions: list[FactionSpec] — 势力列表。每个势力有：id, name, type(门派/散修组织/妖兽势力/中立方), stance(正/魔/中立/野), relations(与其他势力的关系字典), lore
- items: list[ItemSpec] — 灵材/丹药/法器/物件。每个有：id, name, kind(灵材/丹药/法器/材料/暗器), rarity(凡/灵/玄/天), effect, source, lore
- skills: list[SkillSpec] — 功法/招式。每个有：id, name, kind(功法/招式/身法/心法), school, requirement, effect, lore
- tensions: list[TensionSpec] — 下一阶段的张力（世界事件）。每个张力有：id, name, axis(标签数组), emotion(求不得/爱离别/怨憎会/失所有/得而复失/背叛/牺牲/执念), involved_npcs, involved_factions, trigger(激活条件), resolution_paths(多条解决方向), pressure_weight, difficulty
- npc_models: list[BehaviorModel] — NPC行为模型。每个有：npc_id, motive, goals, routine, decision_rules

【硬性规则】：
1. 新阶段场景数不得少于3个。
2. 张力必须有触发条件（trigger.type 不能为空），张力数量至少1个。
3. NPC行为模型至少1个。
4. 场景的connections必须在场景列表中存在，不能指向不存在的场景。
5. 张力id、场景id、npc_id都必须唯一，不能重复。
6. 所有id必须使用英文小写+下划线（如"beast_tide"），name用中文。
7. 新阶段的张力应从已解决张力的因果链自然生长出来——不要凭空创造全新的世界事件。

请直接返回JSON，不要包含任何markdown标记或解释文字。
"""


def build_worldgen_context(
    resolved_tensions: list[ResolvedTension],
    world_state: WorldState,
    player: Player,
    old_bible: WorldBible,
) -> tuple[str, str]:
    """Build system + user prompt for worldgen LLM call."""
    # Build resolved-tension timeline (last 20)
    resolved_lines: list[str] = []
    for i, rt in enumerate(resolved_tensions[-20:], 1):
        label = rt.summary or rt.tension_id
        resolved_lines.append(f"{i}. [第{rt.resolved_tick}回合] {label} ({rt.path_id})")
    resolved_story = "\n".join(resolved_lines) if resolved_lines else "（无已解决张力）"

    # Current world state summary
    active_tensions = [
        tid for tid, rt in world_state.tensions.items()
        if rt.status == "active"
    ]

    user_prompt = (
        f"【玩家状态】\n"
        f"- 当前境界：{player.level}\n"
        f"- 当前灵力：{player.spirit_power}\n"
        f"- 已行动回合：{player.tick}\n\n"
        f"【已解决张力（按时间顺序）】\n{resolved_story}\n\n"
        f"【当前活跃张力】\n"
        f"{'、'.join(active_tensions) if active_tensions else '无'}\n\n"
        f"【当前世界压力】{world_state.world_pressure}\n\n"
        f"【上一阶段设定摘要】\n"
        f"- 阶段：{old_bible.phase_title} (phase {old_bible.phase_id})\n"
        f"- 场景数：{len(old_bible.scenes)}\n"
        f"- 势力数：{len(old_bible.factions)}\n"
        f"- 物品数：{len(old_bible.items)}\n"
        f"- 功法数：{len(old_bible.skills)}\n"
        f"- 张力数：{len(old_bible.tensions)}\n\n"
        f"请生成下一阶段的WorldBible JSON。"
    )

    return WORLDGEN_SYSTEM_TEMPLATE, user_prompt
