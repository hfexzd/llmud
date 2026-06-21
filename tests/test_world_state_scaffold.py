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