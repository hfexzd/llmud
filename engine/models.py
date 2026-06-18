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
      3. alias keyword contained anywhere in the text (e.g. "去内门灵泉旁修炼" → "inner_gate")

    Longer aliases are tried first so a more specific keyword wins over a
    shorter substring. Returns the scene id, or None if nothing matches.
    """
    text = (text or "").strip()
    if not text:
        return None
    if text in SCENE_MAP:
        return text
    for sid, scene in SCENE_MAP.items():
        if scene.name == text:
            return sid
    for alias in sorted(SCENE_ALIASES, key=len, reverse=True):
        if alias in text:
            return SCENE_ALIASES[alias]
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