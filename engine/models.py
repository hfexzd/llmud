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
    tick: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    last_seen: datetime = Field(default_factory=datetime.now)


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


class WorldState(BaseModel):
    current_tick: int = 0
    npc_locations: dict[str, str] = {}


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


DEFAULT_PLAYER = Player()
DEFAULT_ENCOUNTER = Encounter()

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
        connections=["inner_gate", "mountain_range"],
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
        connections=["bamboo_forest"],
        available_actions=["fight", "explore"],
        encounter_ids=["e1"],
        npc_ids=[],
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
ENCOUNTER_CATALOG: list[str] = [DEFAULT_ENCOUNTER.name]


def world_canon() -> dict:
    """All mentionable named entities, for the DM prompt's canon block.

    The LLM may only reference locations/landmarks, NPCs, and enemies from
    here, and items/skills from their catalogs. Empty item/skill catalogs
    mean "narrate generically, do not name specifics".
    """
    locations: list[str] = []
    for scene in SCENE_MAP.values():
        locations.append(scene.name)
        locations.extend(scene.landmarks)
    return {
        "locations": locations,
        "npcs": [p.name for p in ALL_NPC_PROFILES],
        "enemies": list(ENCOUNTER_CATALOG),
        "items": list(ITEM_CATALOG),
        "skills": list(SKILL_CATALOG),
    }