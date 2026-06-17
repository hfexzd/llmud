from engine.models import Player, Intent, CombatResult, BreakthroughResult


DM_SYSTEM_TEMPLATE = """你是一款文字修仙 MUD 游戏的"动态地下城主（DM）"。
请根据玩家输入的行动，结合玩家当前状态和引擎结算结果，生成一段精彩、具有网文爽感的文字描写。

【当前玩家状态】：
- 名字：{name}
- 所在地点：{location}
- 当前境界：{level}
- 当前灵力：{spirit_power}
- 当前气血：{hp}/{max_hp}

{engine_context}

【硬性规则】：
1. 你的每一次回复【必须】严格遵守以下 JSON 格式，不要包含任何 markdown 标记（如 ```json），直接返回纯 JSON 字符串。
2. 玩家不能凭空无敌。
3. 故事描写【不得为空】，必须生成一段叙事文字，限制在120字以内。无论玩家行动多么简单，都必须给出story字段。
4. 战斗数值【必须】与引擎结算结果完全一致，不得臆造。
5. 如果不确定如何描写，也要给出一个简短但有画面感的叙事。"""

ENGINE_CONTEXT_TEMPLATES = {
    "cultivate": "【引擎结算】修炼成功，灵力增加。",
    "fight": "【引擎结算】战斗结果：{combat_result}。造成伤害：{dmg_to_enemy}，受到伤害：{dmg_to_player}，战斗结果：{result}。",
    "move": "【引擎结算】移动成功。",
    "talk": "【引擎结算】与NPC对话。",
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
) -> tuple[str, str]:
    """Build the system and user prompts for the DM LLM call."""
    if intent == Intent.FIGHT and combat_result:
        engine_ctx = ENGINE_CONTEXT_TEMPLATES["fight"].format(
            combat_result=f"{combat_result.result}",
            dmg_to_enemy=combat_result.dmg_to_enemy,
            dmg_to_player=combat_result.dmg_to_player,
            result=combat_result.result,
        )
    else:
        engine_ctx = ENGINE_CONTEXT_TEMPLATES.get(intent.value, ENGINE_CONTEXT_TEMPLATES["other"])

    if breakthrough:
        engine_ctx += f"\n【突破】玩家从{breakthrough.from_level}突破到{breakthrough.to_level}！"

    system_prompt = DM_SYSTEM_TEMPLATE.format(
        name=player.name,
        location=player.location,
        level=player.level,
        spirit_power=player.spirit_power,
        hp=player.hp,
        max_hp=player.max_hp,
        engine_context=engine_ctx,
    )

    user_prompt = ""
    if npc_context:
        user_prompt = npc_context

    return system_prompt, user_prompt


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