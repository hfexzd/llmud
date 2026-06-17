from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, computed_field


class Intent(str, Enum):
    CULTIVATE = "cultivate"
    TALK = "talk"
    FIGHT = "fight"
    MOVE = "move"
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
    location: str = "青云门外门柴房"
    inventory: list[str] = Field(default_factory=list)
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


DEFAULT_PLAYER = Player()
DEFAULT_ENCOUNTER = Encounter()