from engine.models import PHASE_0_BIBLE, WorldBible


class TestPhase0Bible:
    def test_is_world_bible_phase_0(self):
        assert isinstance(PHASE_0_BIBLE, WorldBible)
        assert PHASE_0_BIBLE.phase_id == 0
        assert PHASE_0_BIBLE.phase_title == "练气篇"

    def test_reuses_existing_five_scenes(self):
        ids = {s.id for s in PHASE_0_BIBLE.scenes}
        assert ids == {"outer_gate", "inner_gate", "bamboo_forest", "market", "mountain_range"}

    def test_has_three_npc_models_matching_profiles(self):
        ids = {m.npc_id for m in PHASE_0_BIBLE.npc_models}
        assert ids == {"linwaner", "chenhao", "old_yang"}
        # each model has a schedule-follow routine (M1 minimal behavior)
        for m in PHASE_0_BIBLE.npc_models:
            assert any(a.type == "move" and a.params.get("schedule") for a in m.routine)

    def test_has_seed_factions_items_skills(self):
        assert any(f.id == "qingyun_sect" for f in PHASE_0_BIBLE.factions)
        assert any(i.name == "灵草" for i in PHASE_0_BIBLE.items)
        assert any(s.name == "青云剑诀" for s in PHASE_0_BIBLE.skills)

    def test_tensions_empty_in_m1(self):
        # Real tension data + machine arrive in M2.
        assert PHASE_0_BIBLE.tensions == []


from engine.models import WorldState, PHASE_0_BIBLE, Player
from engine.world import npc_step, tension_tick


class TestNpcStep:
    def test_npc_at_default_scene_when_no_schedule_matches(self):
        ws = WorldState()
        out = npc_step(ws, PHASE_0_BIBLE, tick=0)
        # linwaner default inner_gate, schedule market only at tick 10-20
        assert out.npc_state["linwaner"].scene_id == "inner_gate"
        assert out.npc_state["chenhao"].scene_id == "market"
        assert out.npc_state["old_yang"].scene_id == "outer_gate"
        # schedule_tick records the tick the step ran at
        assert out.npc_state["chenhao"].schedule_tick == 0

    def test_linwaner_moves_to_market_on_schedule(self):
        ws = WorldState()
        out = npc_step(ws, PHASE_0_BIBLE, tick=15)
        assert out.npc_state["linwaner"].scene_id == "market"

    def test_pure_function_does_not_mutate_input(self):
        ws = WorldState()
        npc_step(ws, PHASE_0_BIBLE, tick=15)
        assert ws.npc_state == {}  # input untouched

    def test_preserves_existing_goal_progress_and_mood(self):
        from engine.models import NPCRuntimeState
        ws = WorldState(npc_state={
            "chenhao": NPCRuntimeState(npc_id="chenhao", scene_id="market",
                                       mood="eager", goal_progress={"grow_strong": 30}),
        })
        out = npc_step(ws, PHASE_0_BIBLE, tick=5)
        assert out.npc_state["chenhao"].mood == "eager"
        assert out.npc_state["chenhao"].goal_progress == {"grow_strong": 30}
        assert out.npc_state["chenhao"].scene_id == "market"


class TestTensionTickStub:
    def test_stub_is_noop(self):
        ws = WorldState(world_pressure=3)
        out = tension_tick(ws, PHASE_0_BIBLE, Player())
        # M1 stub: no-op, state unchanged
        assert out is not ws
        assert out.world_pressure == 3
        assert out.tensions == {}