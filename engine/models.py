from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, computed_field


class Intent(str, Enum):
    CULTIVATE = "cultivate"
    TALK = "talk"
    FIGHT = "fight"
    MOVE = "move"
    INTERVENE = "intervene"
    OTHER = "other"


class LevelTier(BaseModel):
    name: str
    spirit_threshold: int
    multiplier: float


LEVEL_TABLE: list[LevelTier] = [
    LevelTier(name="练气期一层", spirit_threshold=0, multiplier=1.0),
    LevelTier(name="练气期二层", spirit_threshold=30, multiplier=1.2),
    LevelTier(name="练气期三层", spirit_threshold=60, multiplier=1.5),
    LevelTier(name="筑基期一层", spirit_threshold=100, multiplier=2.0),
    LevelTier(name="筑基期二层", spirit_threshold=200, multiplier=2.5),
    LevelTier(name="筑基期三层", spirit_threshold=400, multiplier=3.0),
    LevelTier(name="金丹期一层", spirit_threshold=800, multiplier=4.0),
]


def next_spirit_threshold(level: str) -> int | None:
    """Return the spirit_power needed to reach the next 境界, or None if at the
    top of LEVEL_TABLE (or level unknown). Drives the 灵力 progress bar."""
    for i, tier in enumerate(LEVEL_TABLE):
        if tier.name == level:
            if i + 1 < len(LEVEL_TABLE):
                return LEVEL_TABLE[i + 1].spirit_threshold
            return None
    return None


# Twelve 时辰, cycled by tick for an in-world clock that never shows a raw
# number. Mirrored in static/index.html (shichenLabel) — keep them in sync.
SHICHEN_LABELS: list[str] = [
    "子时·夜半", "丑时·鸡鸣", "寅时·平旦", "卯时·日出",
    "辰时·晨光初照", "巳时·隅中", "午时·日中", "未时·日昳",
    "申时·晡时", "酉时·日入", "戌时·黄昏", "亥时·人定",
]


def shichen_label(tick: int) -> str:
    """Map a world tick to a 时辰 label (cycling every 12)."""
    return SHICHEN_LABELS[tick % 12]


class Player(BaseModel):
    id: str = "p1"
    name: str = "张铁柱"
    level: str = "练气期一层"
    spirit_power: int = 10
    hp: int = 100
    max_hp: int = 100
    affinity: str = "火"
    current_scene: str = "outer_gate"
    inventory: list[str] = Field(default_factory=list)
    recent_stories: list[str] = Field(default_factory=list)
    seen_events: list[str] = Field(default_factory=list)
    # Scenes the player has ever set foot in — drives the objective layer
    # (e.g. "到过竹林" satisfies the 竹林 goal). Seeded with the start scene.
    visited_scenes: list[str] = Field(default_factory=lambda: ["outer_gate"])
    # An in-progress fight, keyed by scene_id, so enemy HP persists across
    # rounds and the player can actually wear a beast down. None when no fight
    # is active (or the enemy was just killed).
    active_enemy: dict | None = None
    # Persistent lifecycle records for the visible 所务 (quest) list. The
    # visible list is derived from state; this only carries completed_tick for
    # strike-through + auto-expiry. See engine/world.py.
    quests: list[QuestState] = Field(default_factory=list)
    weapon: str | None = None
    armor: str | None = None
    tick: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    last_seen: datetime = Field(default_factory=datetime.now)
    offline_directive: str = "闭关"  # 闭关 | 历练 | 静养
    spirit_stones: int = 100


class Encounter(BaseModel):
    id: str = "e1"
    name: str = "赤眼妖狼"
    attack: int = 8
    defense: int = 3
    hp: int = 30
    max_hp: int = 30


class CombatResult(BaseModel):
    dmg_to_enemy: int
    dmg_to_player: int
    result: str  # "win" | "lose" | "flee"
    enemy_remaining_hp: int
    player_remaining_hp: int
    crit: bool = False
    combo: int = 1


class BreakthroughResult(BaseModel):
    from_level: str
    to_level: str


class DMResponse(BaseModel):
    """Parsed result from DM JSON contract."""
    intent: Intent = Intent.OTHER
    action_valid: bool = True
    invalid_reason: str = ""
    story: str = ""
    state_delta: dict | None = None
    breakthrough: BreakthroughResult | None = None
    combat: CombatResult | None = None
    npc_update: dict | None = None
    world_delta: dict | None = None  # M3: tension/npc/faction increments


# --- Living World Models ---

class Scene(BaseModel):
    id: str
    name: str
    description: str
    atmosphere: str
    connections: list[str]
    available_actions: list[str]
    encounter_ids: list[str]
    npc_ids: list[str]
    # Sub-locations within this scene that players and the DM narration may
    # reference by name (e.g. 祭坛/灵泉 at the inner gate). The move resolver
    # treats these as keywords pointing at this scene, and the DM prompt lists
    # them so the LLM narrates using world-known landmarks rather than
    # inventing its own.
    landmarks: list[str] = Field(default_factory=list)


class EventTrigger(BaseModel):
    type: str  # "location_enter" | "tick_interval" | "stat_threshold" | "random"
    conditions: dict = {}
    probability: float = 1.0


class WorldEvent(BaseModel):
    id: str
    name: str
    scene_id: str
    trigger: EventTrigger
    narrative_hint: str
    guidance: str
    allow_intervene: bool = False
    intervene_options: list[str] | None = None
    one_time: bool = True


class QuestState(BaseModel):
    """Persistent record of a quest's lifecycle for the visible 所务 list.

    The visible list itself is derived purely from player state (unlock +
    satisfy predicates in world.py); this record only tracks `completed_tick`
    so completed quests can be struck through and auto-expired after N ticks.
    """

    id: str
    status: str  # "active" | "completed"
    unlocked_tick: int
    completed_tick: int | None = None


class Goal(BaseModel):
    """A deterministic, in-world objective the engine tracks for the player.

    The first unsatisfied goal (by priority order in GOALS) is the player's
    current 所务, surfaced in the status bar and the DM prompt so the player
    always has a direction. Satisfaction is computed by the world engine from
    player state — the LLM only narrates toward the goal, it never decides it.
    """

    id: str
    label: str  # in-world 所务 text shown to the player
    guidance: str  # steering text injected into the DM prompt


# Priority-ordered objective arc for the slice. The engine picks the first
# goal whose satisfaction check fails; that is the player's current 所务.
# Satisfaction keys only on deterministic player state (visited_scenes,
# seen_events, level) — never on LLM-granted items.
GOALS: list[Goal] = [
    Goal(
        id="venture_bamboo",
        label="往内门寻林婉儿，同探幽竹林",
        guidance="林婉儿师姐似有心事、欲往竹林一探。叙事应推动玩家前往内门再赴幽竹林，埋下机缘与异象的钩子。",
    ),
    Goal(
        id="probe_anomaly",
        label="查探竹林中的灵草异气",
        guidance="幽竹林中现泛光灵草、似有不祥气息。叙事应引导玩家细查异象、追问缘由，而非匆匆离去。",
    ),
    Goal(
        id="cultivate_breakthrough",
        label="参悟机缘，突破练气期二层",
        guidance="玩家灵力渐丰但仍不足（需灵力满30方可突破练气期二层）。叙事应鼓励其静心修炼、积蓄灵力、参悟所得，朝突破靠近，只可描写瓶颈松动、灵力奔涌等未竟征兆，【绝不可】自行叙述突破或境界提升——突破何时发生由引擎结算决定。",
    ),
    Goal(
        id="venture_mountain",
        label="深入妖兽山脉，试炼身手",
        guidance="幽竹林通向妖兽山脉，或有更大机缘与险阻。叙事应暗示玩家整装向山脉进发。",
    ),
]


# Lookup by id for the 所务 derivation (phase-0 tensions share ids with these
# goals, so the player-visible labels/guidance stay constant when selection
# moves off the GOALS list in M2).
GOAL_BY_ID: dict[str, Goal] = {g.id: g for g in GOALS}


class SceneSchedule(BaseModel):
    tick_range: tuple[int, int]
    scene_id: str


class NPCPresence(BaseModel):
    npc_id: str
    default_scene: str
    schedule: list[SceneSchedule] = []


class NPCInteraction(BaseModel):
    id: str
    npc_ids: list[str]
    scene_id: str
    trigger_conditions: dict = {}
    narrative_hint: str
    allow_intervene: bool = False
    intervene_options: list[str] | None = None


# --- Emergent world runtime models (M1 scaffold; see design spec §5) ---

class TensionRuntime(BaseModel):
    status: str = "dormant"            # dormant | active | resolved
    pressure: int = 0
    progress: dict[str, int] = Field(default_factory=dict)
    activated_tick: int | None = None
    resolved_tick: int | None = None
    resolved_path: str | None = None


class NPCRuntimeState(BaseModel):
    npc_id: str
    scene_id: str
    mood: str = ""
    goal_progress: dict[str, int] = Field(default_factory=dict)
    schedule_tick: int = 0
    last_autonomous_action: str | None = None


class FactionRuntime(BaseModel):
    faction_id: str
    trust: int = 0
    dominance: int = 0


class ResolvedTension(BaseModel):
    tension_id: str
    resolved_tick: int
    path_id: str
    summary: str = ""


class WorldState(BaseModel):
    tick: int = 0
    phase_id: int = 0
    world_pressure: int = 0
    tensions: dict[str, TensionRuntime] = Field(default_factory=dict)
    npc_state: dict[str, NPCRuntimeState] = Field(default_factory=dict)
    faction_state: dict[str, FactionRuntime] = Field(default_factory=dict)
    resolved_tensions: list[ResolvedTension] = Field(default_factory=list)
    sealed: bool = False
    ending: str | None = None


class NPCProfileData(BaseModel):
    """Data-only container for NPC seeding (separate from the interaction model)."""
    id: str
    name: str
    persona: str
    secret: str
    motive: str
    default_scene: str
    favorability: int = 50
    relationship_stage: str = "陌生"


DEFAULT_PLAYER = Player(inventory=["凝露草", "聚气丹"])
DEFAULT_ENCOUNTER = Encounter()
VALLEY_ENCOUNTER = Encounter(
    id="e2", name="毒鳞蟒", attack=12, defense=5, hp=40, max_hp=40,
)
LAKE_ENCOUNTER = Encounter(
    id="e3", name="玄水龟", attack=8, defense=7, hp=50, max_hp=50,
)

# --- Scene Data ---

SCENE_MAP: dict[str, Scene] = {
    "outer_gate": Scene(
        id="outer_gate",
        name="青云门外门",
        description="外门柴房与练功场，灵气稀薄但清静。初来乍到的修士多在此落脚。",
        atmosphere="清幽",
        connections=["inner_gate", "market"],
        available_actions=["cultivate", "explore"],
        encounter_ids=[],
        npc_ids=["old_yang"],
        landmarks=["柴房", "练功场"],
    ),
    "inner_gate": Scene(
        id="inner_gate",
        name="青云门内门",
        description="内门修炼场，灵气浓郁。弟子们在此打坐修炼，师姐常在此处。",
        atmosphere="庄严",
        connections=["outer_gate", "bamboo_forest"],
        available_actions=["cultivate", "explore"],
        encounter_ids=[],
        npc_ids=["linwaner"],
        landmarks=["祭坛", "灵泉"],
    ),
    "bamboo_forest": Scene(
        id="bamboo_forest",
        name="幽竹林",
        description="竹林深处灵气充沛，偶有奇遇。但也传闻有妖兽出没。",
        atmosphere="神秘",
        connections=["inner_gate", "mountain_range", "spirit_valley"],
        available_actions=["cultivate", "explore", "fight"],
        encounter_ids=["e1"],
        npc_ids=[],
    ),
    "market": Scene(
        id="market",
        name="修士集市",
        description="修士们交易灵材丹药的集市，消息灵通，人来人往。",
        atmosphere="繁忙",
        connections=["outer_gate"],
        available_actions=["explore"],
        encounter_ids=[],
        npc_ids=["chenhao"],
    ),
    "mountain_range": Scene(
        id="mountain_range",
        name="妖兽山脉",
        description="危险的山脉深处，妖兽横行。只有胆大的修士才敢涉足。",
        atmosphere="危险",
        connections=["bamboo_forest", "misty_lake"],
        available_actions=["fight", "explore"],
        encounter_ids=["e1"],
        npc_ids=[],
    ),
    "spirit_valley": Scene(
        id="spirit_valley",
        name="灵药谷",
        description="竹林深处藏着一处隐秘山谷，灵气浓郁，奇花异草遍地。谷中住着一位隐居的药修。",
        atmosphere="幽静",
        connections=["bamboo_forest"],
        available_actions=["explore", "cultivate"],
        encounter_ids=["e2"],
        npc_ids=["medicine_elder"],
        landmarks=["药圃", "灵泉眼", "石洞"],
    ),
    "misty_lake": Scene(
        id="misty_lake",
        name="雾隐湖",
        description="山脉脚下的一处幽静湖泊，常年雾气弥漫。湖水清澈见底，传说湖中有灵物出没。",
        atmosphere="缥缈",
        connections=["mountain_range"],
        available_actions=["explore", "cultivate", "fight"],
        encounter_ids=["e3"],
        npc_ids=["lake_hermit"],
        landmarks=["湖畔亭", "钓鱼台", "湖心岛"],
    ),
}

# Short, natural-language keywords players use to refer to a scene.
# The full official names and scene ids are matched separately, so this only
# needs the colloquial short forms (mirrors the frontend SCENE_NAMES map).
SCENE_ALIASES: dict[str, str] = {
    "外门": "outer_gate",
    "内门": "inner_gate",
    "竹林": "bamboo_forest",
    "集市": "market",
    "山脉": "mountain_range",
    "山谷": "spirit_valley",
    "灵药谷": "spirit_valley",
    "湖": "misty_lake",
    "雾隐湖": "misty_lake",
}


def resolve_scene_id(text: str | None) -> str | None:
    """Resolve free-form destination text to a scene id.

    Matching priority:
      1. exact scene id (e.g. "inner_gate")
      2. exact full scene name (e.g. "青云门内门")
      3. keyword contained anywhere in the text — either a scene alias
         ("去内门" → inner_gate) or a scene landmark ("去祭坛看看" → inner_gate)

    Longer keywords are tried first so a more specific one wins over a shorter
    substring. Returns the scene id, or None if nothing matches.
    """
    text = (text or "").strip()
    if not text:
        return None
    if text in SCENE_MAP:
        return text
    for sid, scene in SCENE_MAP.items():
        if scene.name == text:
            return sid
    # Combine short-name aliases and per-scene landmarks into one keyword map.
    keywords: dict[str, str] = dict(SCENE_ALIASES)
    for sid, scene in SCENE_MAP.items():
        for landmark in scene.landmarks:
            keywords[landmark] = sid
    for keyword in sorted(keywords, key=len, reverse=True):
        if keyword in text:
            return keywords[keyword]
    return None


ENCOUNTERS_BY_SCENE: dict[str, list[str]] = {
    "bamboo_forest": ["e1"],
    "mountain_range": ["e1"],
    "spirit_valley": ["e2"],
    "misty_lake": ["e3"],
}

# --- NPC Presence Data ---

NPC_PRESENCES: dict[str, NPCPresence] = {
    "linwaner": NPCPresence(
        npc_id="linwaner",
        default_scene="inner_gate",
        schedule=[SceneSchedule(tick_range=(10, 20), scene_id="market")],
    ),
    "chenhao": NPCPresence(
        npc_id="chenhao",
        default_scene="market",
        schedule=[],
    ),
    "old_yang": NPCPresence(
        npc_id="old_yang",
        default_scene="outer_gate",
        schedule=[],
    ),
    "medicine_elder": NPCPresence(
        npc_id="medicine_elder",
        default_scene="spirit_valley",
        schedule=[],
    ),
    "lake_hermit": NPCPresence(
        npc_id="lake_hermit",
        default_scene="misty_lake",
        schedule=[],
    ),
}

# --- Event Pool Data ---

ALL_EVENTS: list[WorldEvent] = [
    # Environmental hints (direction guidance)
    WorldEvent(
        id="faint_spirit_sense",
        name="灵气波动感知",
        scene_id="outer_gate",
        trigger=EventTrigger(type="location_enter", conditions={"first_time": True}),
        narrative_hint="你隐约感到东方有更浓厚的灵气波动，似乎内门方向灵气更盛。",
        guidance="explore_inner_gate",
        one_time=True,
    ),
    WorldEvent(
        id="outer_gate_cultivate_hint",
        name="外门修炼提示",
        scene_id="outer_gate",
        trigger=EventTrigger(type="stat_threshold", conditions={"max_spirit": 15}),
        narrative_hint="外门虽然灵气稀薄，但胜在清静，正适合初入修途的你静心修炼。",
        guidance="cultivate",
        one_time=True,
    ),
    WorldEvent(
        id="market_hint",
        name="集市传闻",
        scene_id="outer_gate",
        trigger=EventTrigger(type="stat_threshold", conditions={"min_spirit": 14}),
        narrative_hint="一位外门弟子匆匆路过，嘀咕着'集市那边新到了一批丹药……'",
        guidance="explore_market",
        one_time=True,
    ),
    WorldEvent(
        id="bamboo_whisper",
        name="竹林沙沙声",
        scene_id="inner_gate",
        trigger=EventTrigger(type="stat_threshold", conditions={"min_spirit": 20}),
        narrative_hint="竹林方向传来奇异的沙沙声，似乎有什么不寻常的事正在发生。",
        guidance="explore_bamboo_forest",
        one_time=True,
    ),
    WorldEvent(
        id="market_rumor",
        name="集市传闻",
        scene_id="market",
        trigger=EventTrigger(type="tick_interval", conditions={"min_tick": 5}),
        narrative_hint="集市上有人在低声议论山脉方向的异动，似乎妖兽变得更加活跃了。",
        guidance="explore_mountain_range",
        one_time=True,
    ),
    # NPC-initiated hints
    WorldEvent(
        id="waner_worry",
        name="师姐心事",
        scene_id="inner_gate",
        trigger=EventTrigger(type="location_enter", conditions={"first_time": True}),
        narrative_hint="师姐似乎心事重重，不时望向竹林方向，欲言又止。",
        guidance="talk_linwaner",
        one_time=True,
    ),
    WorldEvent(
        id="merchant_gossip",
        name="商贩搭话",
        scene_id="market",
        trigger=EventTrigger(type="tick_interval", conditions={"min_tick": 3}),
        narrative_hint="一个商贩主动向你搭话：'道友，最近山里出了好东西，可惜我修为不够……'",
        guidance="explore_mountain_range",
        one_time=True,
    ),
    WorldEvent(
        id="chenhao_challenge",
        name="师兄挑战邀请",
        scene_id="market",
        trigger=EventTrigger(type="stat_threshold", conditions={"min_spirit": 25}),
        narrative_hint="陈浩朝你招手：'师弟，要不要去山脉试试身手？最近那边的妖狼似乎变强了。'",
        guidance="fight_mountain_range",
        one_time=True,
    ),
    # NPC-to-NPC interactions are handled by NPC_INTERACTIONS (see below)
    WorldEvent(
        id="elder_scolding",
        name="长老训斥弟子",
        scene_id="inner_gate",
        trigger=EventTrigger(type="tick_interval", conditions={"min_tick": 8}),
        narrative_hint="一位长老正在训斥弟子：'竹林禁地，岂是尔等可以随意涉足的！'",
        guidance="explore_bamboo_forest",
        one_time=True,
    ),
    # Random encounters
    WorldEvent(
        id="spirit_herb",
        name="灵草发现",
        scene_id="bamboo_forest",
        trigger=EventTrigger(type="random", conditions={}, probability=0.1),
        narrative_hint="你在竹林中发现了一株散发着微光的灵草，灵气从中缓缓溢出。",
        guidance="explore_bamboo_forest",
        one_time=True,
    ),
    WorldEvent(
        id="strange_traveler",
        name="神秘旅人",
        scene_id="market",
        trigger=EventTrigger(type="random", conditions={}, probability=0.15),
        narrative_hint="集市角落坐着一个神秘旅人，眼神深邃，似乎在等待着什么。",
        guidance="talk_stranger",
        one_time=True,
    ),
    # Late-stage hints
    WorldEvent(
        id="waner_secret_hint",
        name="师姐的秘密",
        scene_id="inner_gate",
        trigger=EventTrigger(type="stat_threshold", conditions={"min_spirit": 50}),
        narrative_hint="师姐不经意间说漏了嘴，提到了一个关于宗门的秘密……",
        guidance="talk_linwaner",
        one_time=True,
    ),
    # Spirit Valley events
    WorldEvent(
        id="valley_discovery",
        name="隐秘山谷",
        scene_id="bamboo_forest",
        trigger=EventTrigger(type="stat_threshold", conditions={"min_spirit": 25}),
        narrative_hint="竹林深处似有异光闪烁，隐约能闻到一股药香从某个方向飘来。",
        guidance="explore_spirit_valley",
        one_time=True,
    ),
    WorldEvent(
        id="elder_first_meeting",
        name="药老的试探",
        scene_id="spirit_valley",
        trigger=EventTrigger(type="location_enter", conditions={"first_time": True}),
        narrative_hint="一位灰袍老者正在药圃中劳作，见你到来，抬头打量了一番。'小友也是修士？可懂药理？'",
        guidance="talk_medicine_elder",
        allow_intervene=True,
        intervene_options=["恭敬请教", "展示灵草知识", "直言想寻灵药"],
        one_time=True,
    ),
    WorldEvent(
        id="valley_guardian",
        name="谷中守护兽",
        scene_id="spirit_valley",
        trigger=EventTrigger(type="stat_threshold", conditions={"min_spirit": 35}),
        narrative_hint="谷中深处传来低沉的嘶鸣声，药老神色凝重：'那条毒鳞蟒又在躁动了……你若能除去它，老夫自有重谢。'",
        guidance="fight_valley_guardian",
        one_time=True,
    ),
    # Lake events
    WorldEvent(
        id="misty_lake_discovery",
        name="雾隐湖",
        scene_id="mountain_range",
        trigger=EventTrigger(type="tick_interval", conditions={"min_tick": 15}),
        narrative_hint="山脉脚下隐约传来水声，透过雾气能看到一片波光粼粼的湖面。",
        guidance="explore_misty_lake",
        one_time=True,
    ),
    WorldEvent(
        id="hermit_first_meeting",
        name="湖隐的考验",
        scene_id="misty_lake",
        trigger=EventTrigger(type="location_enter", conditions={"first_time": True}),
        narrative_hint="湖边坐着一位白衣老者，手持钓竿，目不斜视。他似乎察觉到你，却未发一言。",
        guidance="talk_lake_hermit",
        allow_intervene=True,
        intervene_options=["恭敬行礼", "在旁静坐", "询问湖水之事"],
        one_time=True,
    ),
    WorldEvent(
        id="lake_turtle_awakening",
        name="玄水龟现世",
        scene_id="misty_lake",
        trigger=EventTrigger(type="stat_threshold", conditions={"min_spirit": 40}),
        narrative_hint="湖面突然涌起巨浪，一头巨大的玄水龟从湖心浮出，龟甲上泛着幽幽蓝光。",
        guidance="fight_turtle",
        one_time=True,
    ),
]

# --- NPC Interaction Data ---

NPC_INTERACTIONS: list[NPCInteraction] = [
    NPCInteraction(
        id="waner_chenhao_chat",
        npc_ids=["linwaner", "chenhao"],
        scene_id="market",
        trigger_conditions={"tick_min": 5},
        narrative_hint="林婉儿和陈浩正在交谈，似乎在讨论山脉方向的异动。",
        allow_intervene=True,
        intervene_options=["上前搭话", "继续偷听", "默默离开"],
    ),
]

# --- New NPC Profiles ---

ALL_NPC_PROFILES: list[NPCProfileData] = [
    NPCProfileData(
        id="linwaner",
        name="林婉儿",
        persona="青云门知心师姐，温柔体贴，修炼有成，善于倾听。",
        secret="她其实是宗门长老的私生女，身世不能暴露。",
        motive="希望找到一个可以信赖的人，但害怕自己的秘密被发现。",
        default_scene="inner_gate",
        favorability=50,
        relationship_stage="陌生",
    ),
    NPCProfileData(
        id="chenhao",
        name="陈浩",
        persona="青云门豪爽师兄，爱冒险，性格直率，武艺不凡但冲动。",
        secret="他偷偷在修炼一门禁术，一旦被发现将面临逐出宗门的危险。",
        motive="想要变强保护身边的人，但又忍不住禁术的诱惑。",
        default_scene="market",
        favorability=30,
        relationship_stage="陌生",
    ),
    NPCProfileData(
        id="old_yang",
        name="杨老",
        persona="外门守门人，沉默寡言但句句关键。看似普通老人，实则深藏不露。",
        secret="他曾是宗门最强的剑修，因故隐退至此。",
        motive="守护外门平安，偶尔点拨有缘的年轻修士。",
        default_scene="outer_gate",
        favorability=40,
        relationship_stage="陌生",
    ),
    NPCProfileData(
        id="medicine_elder",
        name="药老",
        persona="隐居灵药谷的药修，性情古怪但心地善良。精通药理与炼丹之术。",
        secret="他年轻时曾是宗门首席丹师，因炼出一枚禁丹被逐出师门，隐居至此。",
        motive="寻找值得传承衣钵的有缘人，同时守护谷中的珍稀灵药。",
        default_scene="spirit_valley",
        favorability=25,
        relationship_stage="陌生",
    ),
    NPCProfileData(
        id="lake_hermit",
        name="湖隐",
        persona="雾隐湖畔的神秘隐士，常年垂钓，不问世事。看似散漫，实则深谙天地之道。",
        secret="他曾在百年前救过一头灵兽，灵兽如今隐在湖中守护着此方水域。",
        motive="守护雾隐湖的灵气平衡，偶尔指点有缘人悟道。",
        default_scene="misty_lake",
        favorability=20,
        relationship_stage="陌生",
    ),
]


# --- Mentionable world canon ---
# The named entities the world "has". The DM prompt lists these (see
# dm/prompt.world_canon / build_dm_prompt) so the LLM narrates using
# world-known things instead of inventing its own (e.g. 断崖洞窟/三叶血兰/
# 铁背蜥 are all outside this canon). Add a string to a catalog and it
# auto-appears in the prompt's canon block — no other wiring needed.
#
# Items and skills are intentionally empty for now: the system has no
# 灵材/丹药/功法 catalog yet, so the DM is told to narrate them generically
# ("某株灵草"/"一门功法") rather than name specifics. Fill these lists when
# the world's lore is authored.
ITEM_CATALOG: list[str] = []   # 灵材/丹药/物件 — 留白待补
SKILL_CATALOG: list[str] = []  # 功法/招式/技能 — 留白待补

# Canonical 妖兽/敌人 names. The encounter pool currently holds only
# DEFAULT_ENCOUNTER (赤眼妖狼); extend here when more enemies are defined.
ENCOUNTER_CATALOG: list[str] = [DEFAULT_ENCOUNTER.name, VALLEY_ENCOUNTER.name, LAKE_ENCOUNTER.name]


def world_canon(bible: WorldBible | None = None) -> dict:
    """All mentionable named entities, for the DM prompt's canon block.

    The LLM may only reference locations/landmarks, NPCs, and enemies from
    here, and items/skills from their catalogs. Empty item/skill catalogs
    fall back to PHASE_0_BIBLE data. Pass an active *bible* (after milestone
    regen) to derive canon from it instead of the static seed data.
    """
    locations: list[str] = []
    for scene in SCENE_MAP.values():
        locations.append(scene.name)
        locations.extend(scene.landmarks)

    # When an active bible is provided, derive canon from it; otherwise fall
    # back to standalone catalogs or PHASE_0_BIBLE.
    if bible is not None:
        items = [i.name for i in bible.items]
        skills = [s.name for s in bible.skills]
        npcs = list({p.name for p in ALL_NPC_PROFILES})  # still from profiles
    else:
        items = list(ITEM_CATALOG) if ITEM_CATALOG else [i.name for i in PHASE_0_BIBLE.items]
        skills = list(SKILL_CATALOG) if SKILL_CATALOG else [s.name for s in PHASE_0_BIBLE.skills]

    return {
        "locations": locations,
        "npcs": [p.name for p in ALL_NPC_PROFILES],
        "enemies": list(ENCOUNTER_CATALOG),
        "items": items,
        "skills": skills,
    }

# --- World canon / behavior / content models (M1 scaffold; spec §4, §4.2) ---
# Leaf models first, then WorldBible (which references them). `Scene` is the
# existing scene model (reused as the scene spec — no redundant SceneSpec).

class TensionTrigger(BaseModel):
    type: str                          # stat | tick | tension_resolved | npc_state
    conditions: dict = Field(default_factory=dict)


class ResolutionPath(BaseModel):
    id: str
    label: str
    condition: dict = Field(default_factory=dict)
    outcome_state: dict = Field(default_factory=dict)
    ending_lean: str | None = None


class TensionSpec(BaseModel):
    id: str
    name: str
    axis: list[str] = Field(default_factory=list)
    emotion: str = ""
    involved_npcs: list[str] = Field(default_factory=list)
    involved_factions: list[str] = Field(default_factory=list)
    trigger: TensionTrigger
    resolution_paths: list[ResolutionPath] = Field(default_factory=list)
    pressure_weight: int = 1
    difficulty: int = 1


class NPCGoal(BaseModel):
    id: str
    label: str
    axis: str                          # 成长 / 陪伴 / 探索
    satisfy_condition: dict = Field(default_factory=dict)
    progress_driver: dict = Field(default_factory=dict)
    tragic_potential: str | None = None


class BehaviorTrigger(BaseModel):
    type: str
    conditions: dict = Field(default_factory=dict)


class BehaviorAction(BaseModel):
    type: str                           # move | mood | goal_progress | interact_npc
    params: dict = Field(default_factory=dict)
    condition: dict = Field(default_factory=dict)


class BehaviorModel(BaseModel):
    npc_id: str
    motive: str = ""
    goals: list[NPCGoal] = Field(default_factory=list)
    triggers: list[BehaviorTrigger] = Field(default_factory=list)
    routine: list[BehaviorAction] = Field(default_factory=list)
    decision_rules: list[str] = Field(default_factory=list)


class FactionSpec(BaseModel):
    id: str
    name: str
    type: str                           # 门派 | 散修组织 | 妖兽势力 | 中立方
    stance: str = ""                    # 正 | 魔 | 中立 | 野
    relations: dict[str, str] = Field(default_factory=dict)
    tensions_involved: list[str] = Field(default_factory=list)
    lore: str = ""


class ItemSpec(BaseModel):
    id: str
    name: str
    kind: str                           # 灵材 | 丹药 | 法器 | 材料 | 暗器
    rarity: str = "凡"                   # 凡 | 灵 | 玄 | 天
    effect: str = ""
    source: list[str] = Field(default_factory=list)
    axis: str = ""
    lore: str = ""


class SkillSpec(BaseModel):
    id: str
    name: str
    kind: str                           # 功法 | 招式 | 身法 | 心法
    school: str = ""                    # references a FactionSpec.id
    requirement: str = ""
    effect: str = ""
    axis: str = ""
    lore: str = ""


class WorldBible(BaseModel):
    phase_id: int = 0
    phase_title: str = ""
    scenes: list[Scene] = Field(default_factory=list)
    factions: list[FactionSpec] = Field(default_factory=list)
    items: list[ItemSpec] = Field(default_factory=list)
    skills: list[SkillSpec] = Field(default_factory=list)
    tensions: list[TensionSpec] = Field(default_factory=list)
    npc_models: list[BehaviorModel] = Field(default_factory=list)
    ending_hints: dict = Field(default_factory=dict)


# --- Phase-0 WorldBible seed (hand-authored, no LLM; LLM worldgen is M5) ---
# Translates the existing hand-authored SCENE_MAP + NPC profiles into a
# WorldBible, plus a small starter set of factions/items/skills so the canon
# (DM prompt + validator) has concrete entities to reference from turn 1.
# Tensions are empty in M1; M2 adds real tension data + the tension machine.
PHASE_0_BIBLE = WorldBible(
    phase_id=0,
    phase_title="练气篇",
    scenes=list(SCENE_MAP.values()),
    factions=[
        FactionSpec(id="qingyun_sect", name="青云门", type="门派", stance="正",
                    relations={"sanxiu_league": "疏"}, lore="主角所在宗门，门规森严。"),
        FactionSpec(id="sanxiu_league", name="散修盟", type="散修组织", stance="中立",
                    relations={"qingyun_sect": "疏"}, lore="松散的散修互助组织，消息灵通。"),
    ],
    items=[
        ItemSpec(id="spirit_herb", name="灵草", kind="灵材", rarity="凡",
                 effect="服用可缓缓增益灵力", source=["幽竹林"], axis="成长",
                 lore="竹林深处偶现的泛光灵草。"),
        ItemSpec(id="ninglu_grass", name="凝露草", kind="灵材", rarity="凡",
                 effect="服用可小幅恢复气血", source=["幽竹林", "outer_gate"], axis="成长",
                 lore="叶尖凝露，清心养气。"),
        ItemSpec(id="qi_pill", name="聚气丹", kind="丹药", rarity="凡",
                 effect="服用可增益灵力", source=["修士集市"], axis="成长",
                 lore="集市常见的入门丹药。"),
        ItemSpec(id="lingzhi", name="灵芝", kind="灵材", rarity="灵",
                 effect="服用可大幅增益灵力并恢复气血", source=["灵药谷"], axis="成长",
                 lore="灵药谷中生长的珍稀灵芝，蕴含精纯灵气。"),
        ItemSpec(id="snake_gall", name="蛇胆", kind="灵材", rarity="灵",
                 effect="服用可永久提升气血上限", source=["灵药谷"], axis="成长",
                 lore="毒鳞蟒的胆，入药可强筋健骨、拓展经脉。"),
        ItemSpec(id="antidote_pill", name="解毒丹", kind="丹药", rarity="凡",
                 effect="服用可解除多数毒素", source=["灵药谷"], axis="成长",
                 lore="药老炼制的解毒丹药，可解百毒。"),
        ItemSpec(id="spirit_fish", name="灵鱼", kind="灵材", rarity="凡",
                 effect="食用可恢复气血", source=["雾隐湖"], axis="成长",
                 lore="雾隐湖中特有的鱼类，蕴含微弱灵气。"),
        ItemSpec(id="lake_pearl", name="湖心珠", kind="法器", rarity="灵",
                 effect="佩戴可缓慢恢复灵力", source=["雾隐湖"], axis="成长",
                 lore="湖心深处的灵珠，凝聚了雾隐湖百年的灵气精华。"),
        ItemSpec(id="bronze_sword", name="青锋剑", kind="法器", rarity="凡",
                 effect="装备可提升攻击", source=["修士集市"], axis="成长",
                 lore="一柄普通的青铜长剑，锋利程度尚可。"),
        ItemSpec(id="cloth_armor", name="布甲", kind="法器", rarity="凡",
                 effect="装备可提升防御", source=["修士集市"], axis="成长",
                 lore="粗布制成的简易护甲，聊胜于无。"),
    ],
    skills=[
        SkillSpec(id="qingyun_sword_art", name="青云剑诀", kind="功法",
                  school="qingyun_sect", requirement="练气期一层",
                  effect="提升攻击", axis="成长", lore="青云门入门剑法，中正平和。"),
        SkillSpec(id="fentian_palm", name="焚天掌", kind="招式", school="",
                  requirement="灵根·火", effect="火属性攻击招式", axis="成长",
                  lore="以火灵根催动的烈掌。"),
        SkillSpec(id="herbalism", name="百草经", kind="心法", school="",
                  requirement="练气期一层", effect="提升灵力恢复速度",
                  axis="成长", lore="药老所传的草药心法，可感知天地灵草。"),
    ],
    tensions=[
        TensionSpec(
            id="venture_bamboo",
            name="同探幽竹林",
            axis=["陪伴", "探索"],
            emotion="执念",
            involved_npcs=["linwaner"],
            involved_factions=["qingyun_sect"],
            trigger=TensionTrigger(type="stat", conditions={"always": True}),
            resolution_paths=[
                ResolutionPath(
                    id="reach_bamboo",
                    label="抵达幽竹林",
                    condition={"visited": "bamboo_forest"},
                    outcome_state={},
                    ending_lean=None,
                ),
            ],
            pressure_weight=1,
            difficulty=1,
        ),
        TensionSpec(
            id="probe_anomaly",
            name="查探灵草异气",
            axis=["探索"],
            emotion="求不得",
            involved_npcs=["linwaner"],
            involved_factions=["qingyun_sect"],
            trigger=TensionTrigger(type="stat", conditions={"visited": "bamboo_forest"}),
            resolution_paths=[
                ResolutionPath(
                    id="witness_herb",
                    label="得见灵草异象",
                    condition={"seen_event": "spirit_herb"},
                    outcome_state={},
                    ending_lean=None,
                ),
            ],
            pressure_weight=1,
            difficulty=1,
        ),
        TensionSpec(
            id="cultivate_breakthrough",
            name="突破练气期二层",
            axis=["成长"],
            emotion="执念",
            involved_npcs=[],
            involved_factions=["qingyun_sect"],
            trigger=TensionTrigger(type="stat", conditions={"seen_event": "spirit_herb"}),
            resolution_paths=[
                ResolutionPath(
                    id="breakthrough",
                    label="突破至练气期二层",
                    condition={"level": "练气期二层"},
                    outcome_state={},
                    ending_lean=None,
                ),
            ],
            pressure_weight=2,
            difficulty=2,
        ),
        TensionSpec(
            id="venture_mountain",
            name="深入妖兽山脉",
            axis=["成长", "探索"],
            emotion="执念",
            involved_npcs=[],
            involved_factions=[],
            trigger=TensionTrigger(type="stat", conditions={"level": "练气期二层"}),
            resolution_paths=[
                ResolutionPath(
                    id="reach_mountain",
                    label="抵达妖兽山脉",
                    condition={"visited": "mountain_range"},
                    outcome_state={},
                    ending_lean=None,
                ),
            ],
            pressure_weight=1,
            difficulty=2,
        ),
    ],
    npc_models=[
        BehaviorModel(
            npc_id="linwaner",
            motive="希望找到一个可信赖之人，又怕身世暴露。",
            goals=[
                NPCGoal(id="seek_confidant", label="寻一可托付之人", axis="陪伴",
                        tragic_potential="身世暴露或被弃"),
                NPCGoal(id="protect_secret", label="守护身世秘密", axis="成长",
                        tragic_potential=None),
            ],
            routine=[
                BehaviorAction(type="move", params={"schedule": True}, condition={}),
                BehaviorAction(type="mood", params={"mood": "hopeful"},
                               condition={"seen_event": "waner_worry"}),
                BehaviorAction(type="mood", params={"mood": "burdened"},
                               condition={"min_tick": 20}),
            ],
            decision_rules=["信任度低时回避话题", "提到竹林时神情异常"],
        ),
        BehaviorModel(
            npc_id="chenhao",
            motive="想变强护人，又受禁术诱惑。",
            goals=[
                NPCGoal(id="grow_strong", label="变强护人", axis="成长",
                        tragic_potential="禁术败露被逐出宗门"),
                NPCGoal(id="explore_frontier", label="探索山脉深处", axis="探索",
                        tragic_potential="遭遇不测"),
            ],
            routine=[
                BehaviorAction(type="move", params={"schedule": True}, condition={}),
                BehaviorAction(type="mood", params={"mood": "eager"},
                               condition={"min_tick": 5}),
                BehaviorAction(type="goal_progress", params={"goal_id": "explore_frontier", "delta": 1},
                               condition={"min_tick": 10}),
            ],
            decision_rules=["遇强则兴奋", "提及禁术时神色慌张"],
        ),
        BehaviorModel(
            npc_id="old_yang",
            motive="守护外门，偶尔点拨有缘人。",
            goals=[
                NPCGoal(id="guard_gate", label="守护外门", axis="探索",
                        tragic_potential=None),
                NPCGoal(id="teach_worthy", label="点拨有缘弟子", axis="成长",
                        tragic_potential=None),
            ],
            routine=[
                BehaviorAction(type="move", params={"schedule": True}, condition={}),
                BehaviorAction(type="mood", params={"mood": "watchful"},
                               condition={"always": True}),
            ],
            decision_rules=["沉默寡言但句句关键", "对勤奋弟子更友善"],
        ),
        BehaviorModel(
            npc_id="lake_hermit",
            motive="守护雾隐湖灵气平衡，静待有缘人。",
            goals=[
                NPCGoal(id="maintain_balance", label="守护湖中灵气", axis="探索",
                        tragic_potential=None),
                NPCGoal(id="teach_way", label="点拨有慧根之人", axis="陪伴",
                        tragic_potential=None),
            ],
            routine=[
                BehaviorAction(type="move", params={"schedule": True}, condition={}),
                BehaviorAction(type="mood", params={"mood": "serene"},
                               condition={"always": True}),
            ],
            decision_rules=["不问世事只垂钓", "对悟性高者青眼有加"],
        ),
        BehaviorModel(
            npc_id="medicine_elder",
            motive="寻找衣钵传人，守护谷中灵药。",
            goals=[
                NPCGoal(id="find_apprentice", label="寻一可传衣钵之人", axis="陪伴",
                        tragic_potential="衣钵无人可传"),
                NPCGoal(id="protect_valley", label="守护灵药谷", axis="探索",
                        tragic_potential=None),
            ],
            routine=[
                BehaviorAction(type="move", params={"schedule": True}, condition={}),
                BehaviorAction(type="mood", params={"mood": "curious"},
                               condition={"seen_event": "elder_first_meeting"}),
                BehaviorAction(type="mood", params={"mood": "grateful"},
                               condition={"seen_event": "valley_guardian"}),
            ],
            decision_rules=["对懂药理者另眼相看", "提及宗门往事会沉默"],
        ),
    ],
    ending_hints={},
)


# Shop catalog: items available for purchase at the market
SHOP_ITEMS: list[dict] = [
    {"name": "凝露草", "price": 10, "scene": "market"},
    {"name": "聚气丹", "price": 25, "scene": "market"},
    {"name": "解毒丹", "price": 15, "scene": "market"},
    {"name": "青锋剑", "price": 50, "scene": "market"},
    {"name": "布甲", "price": 40, "scene": "market"},
]


def shop_list(scene_id: str) -> list[dict]:
    """Return items available in a given scene's shop."""
    return [s for s in SHOP_ITEMS if s["scene"] == scene_id]


# Alchemy/crafting recipes (combined at spirit_valley with medicine_elder)
CRAFT_RECIPES: list[dict] = [
    {"name": "聚气丹", "ingredients": ["凝露草", "凝露草"], "result": "聚气丹", "scene": "spirit_valley"},
    {"name": "解毒丹", "ingredients": ["灵草", "灵芝"], "result": "解毒丹", "scene": "spirit_valley"},
    {"name": "洗髓丹", "ingredients": ["蛇胆", "灵芝"], "result": "洗髓丹", "scene": "spirit_valley",
     "effect": "永久提升灵力上限", "rarity": "灵"},
]

# Add洗髓丹 to items if not already there (for the crafting result)
if not any(i.id == "marrow_pill" for i in PHASE_0_BIBLE.items):
    PHASE_0_BIBLE.items.append(ItemSpec(
        id="marrow_pill", name="洗髓丹", kind="丹药", rarity="灵",
        effect="永久提升灵力",
        source=["灵药谷（炼制）"], axis="成长",
        lore="以蛇胆与灵芝炼制的珍稀丹药，可洗筋伐髓、拓展经脉。",
    ))


def craft_possible(scene_id: str, inventory: list[str]) -> list[dict]:
    """Return craftable recipes given current scene and inventory."""
    results = []
    for r in CRAFT_RECIPES:
        if r["scene"] != scene_id:
            continue
        inv_copy = list(inventory)
        can_craft = True
        for ing in r["ingredients"]:
            if ing in inv_copy:
                inv_copy.remove(ing)
            else:
                can_craft = False
                break
        if can_craft:
            results.append(r)
    return results


# --- Terminal Archetypes (M4 ending system) ---

class TerminalArchetype(BaseModel):
    """An ending condition the world can resolve into.

    Evaluated by check_ending() each tick. When the condition fires,
    WorldState.sealed=True and WorldState.ending=archetype.id.
    """
    id: str
    name: str
    condition: dict  # predicate dict (same shape as evaluate_condition)
    finale_guidance: str  # injected into the finale LLM prompt
    priority: int  # evaluation order (higher = checked first)


TERMINAL_ARCHETYPES: list[TerminalArchetype] = [
    # Seven archetypes spanning sweet/bitter/tragic emotional spectrum.
    # Evaluated in priority order: more specific ones first, wanderer last.
    TerminalArchetype(
        id="ascension",
        name="飞升成仙",
        condition={"level": "筑基期"},
        finale_guidance="玩家最终飞升成仙，超脱尘世。结局应当壮丽超然，回顾一路修行的艰辛与成长，带着对师门与同伴的温情告别。",
        priority=10,
    ),
    TerminalArchetype(
        id="demonic",
        name="堕入魔道",
        condition={"tension_resolved": "demonic_temptation"},
        finale_guidance="玩家被心魔吞噬，堕入魔道。结局应当悲怆而决绝，曾经的同门反目，挚友痛心，玩家在力量与道义间选择了力量。",
        priority=9,
    ),
    TerminalArchetype(
        id="fall",
        name="陨落",
        condition={"tension_resolved": "ultimate_sacrifice"},
        finale_guidance="玩家在大劫中陨落，以身殉道。结局应当壮烈感人，玩家的牺牲守护了重要的人或宗门，虽死无憾。",
        priority=8,
    ),
    TerminalArchetype(
        id="unrequited",
        name="求不得",
        condition={"tension_resolved": "lost_love"},
        finale_guidance="玩家得到了力量/地位，却失去了最重要的人。结局应当怅然若失，得到与失去交织，带着淡淡的哀伤与释然。",
        priority=7,
    ),
    TerminalArchetype(
        id="unifier",
        name="一统江湖",
        condition={"tension_resolved": "sect_unified"},
        finale_guidance="玩家整合了各大势力，开创新秩序。结局应当宏大有气魄，展现玩家作为一代宗师的格局与胸怀。",
        priority=6,
    ),
    TerminalArchetype(
        id="hermit",
        name="归隐山林",
        condition={"tension_resolved": "peaceful_retreat"},
        finale_guidance="玩家功成身退，携所爱归隐山林。结局应当温馨宁静，平淡中见真意，体现返璞归真的人生境界。",
        priority=5,
    ),
    TerminalArchetype(
        id="wanderer",
        name="行遍天下",
        condition={"always": True, "min_tick": 20},  # fallback — fires if no other ending hit, after min 20 ticks
        finale_guidance="玩家没有特定的命运终点，将继续在这片大陆上游历。结局应当开放而充满希望，暗示旅途永不完结。",
        priority=1,
    ),
]
