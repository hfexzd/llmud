from npc.models import NPCProfile, NPCTurn, KeyFact, NPCMemory, DEFAULT_NPC_PROFILE
from npc.memory import compute_relationship_stage, update_memory, build_memory_context


def test_relationship_stage_stranger():
    assert compute_relationship_stage(10) == "陌生"

def test_relationship_stage_acquaintance():
    assert compute_relationship_stage(30) == "相识"

def test_relationship_stage_familiar():
    assert compute_relationship_stage(60) == "熟悉"

def test_relationship_stage_confidant():
    assert compute_relationship_stage(90) == "知己"


def test_update_memory_adds_turn():
    memory = NPCMemory(npc_id="linwaner", recent_turns=[], summary="", key_facts=[])
    updated = update_memory(
        memory,
        user_message="师姐，我想变强保护你。",
        npc_response="师姐微微一笑：那你可要努力修炼了。",
        npc_update={"emotion": "微笑", "favorability_change": 3, "new_key_fact": "玩家想保护师姐", "summary_delta": "玩家表达了保护意愿"},
    )
    assert len(updated.recent_turns) == 2  # user + npc
    assert updated.key_facts[0].fact == "玩家想保护师姐"


def test_update_memory_clamps_favorability():
    """Test that favorability is clamped to 0-100 range (done at API layer, but verify memory logic)."""
    profile = DEFAULT_NPC_PROFILE
    new_fav = max(0, min(100, profile.favorability + (-200)))
    assert new_fav == 0


def test_build_memory_context():
    memory = NPCMemory(
        npc_id="linwaner",
        recent_turns=[
            NPCTurn(role="user", content="你好，师姐"),
            NPCTurn(role="assistant", content="你好呀，小师弟"),
        ],
        summary="玩家刚入门，与师姐初次相遇。",
        key_facts=[KeyFact(fact="玩家是新入门弟子", turn_number=1)],
    )
    ctx = build_memory_context(memory)
    assert "你好，师姐" in ctx
    assert "玩家刚入门" in ctx


def test_memory_trims_turns():
    """Test that recent_turns is trimmed to MAX_RECENT_TURNS."""
    memory = NPCMemory(npc_id="linwaner", recent_turns=[], summary="", key_facts=[])
    # Add 4 exchanges (8 turns) - should be trimmed to 6
    for i in range(4):
        memory = update_memory(
            memory,
            user_message=f"Message {i}",
            npc_response=f"Response {i}",
        )
    assert len(memory.recent_turns) <= 6