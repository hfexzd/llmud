from pydantic import BaseModel, Field


class NPCProfile(BaseModel):
    id: str = "linwaner"
    name: str = "林婉儿"
    persona: str = "青云门知心师姐，温柔体贴，修炼有成，善于倾听。"
    secret: str = "她其实是宗门长老的私生女，身世不能暴露。"
    motive: str = "希望找到一个可以信赖的人，但害怕自己的秘密被发现。"
    favorability: int = 50
    relationship_stage: str = "陌生"


class NPCTurn(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class KeyFact(BaseModel):
    fact: str
    turn_number: int


class NPCMemory(BaseModel):
    npc_id: str = "linwaner"
    recent_turns: list[NPCTurn] = Field(default_factory=list)
    summary: str = ""
    key_facts: list[KeyFact] = Field(default_factory=list)


# Seed data for the 师姐
DEFAULT_NPC_PROFILE = NPCProfile()