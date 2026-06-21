"""Tests for M5 worldgen — schema validation, generation, regen trigger."""
import pytest
from engine.models import (
    WorldBible, WorldState, Player, PHASE_0_BIBLE,
    TensionSpec, TensionTrigger, TensionRuntime, ResolvedTension,
)
from worldgen.validator import validate_bible
from engine.world import check_regen, merge_bible, REGEN_THRESHOLD


class TestValidateBible:
    def test_valid_bible_passes(self):
        errors = validate_bible(PHASE_0_BIBLE)
        assert errors == []

    def test_bible_with_duplicate_tension_ids_fails(self):
        bible = PHASE_0_BIBLE.model_copy(deep=True)
        bible.tensions.append(bible.tensions[0])  # duplicate
        errors = validate_bible(bible)
        assert len(errors) >= 1

    def test_bible_with_empty_tension_trigger_fails(self):
        bible = PHASE_0_BIBLE.model_copy(deep=True)
        bible.tensions.append(TensionSpec(
            id="no_trigger", name="无触发", axis=[], emotion="执念",
            trigger=TensionTrigger(type="", conditions={}),
            resolution_paths=[],
        ))
        errors = validate_bible(bible)
        assert len(errors) >= 1

    def test_bible_missing_scenes_fails(self):
        bible = PHASE_0_BIBLE.model_copy(deep=True)
        bible.scenes = []
        errors = validate_bible(bible)
        assert len(errors) >= 1

    def test_bible_missing_npc_models_fails(self):
        bible = PHASE_0_BIBLE.model_copy(deep=True)
        bible.npc_models = []
        errors = validate_bible(bible)
        assert len(errors) >= 1

    def test_bible_bad_scene_connection_fails(self):
        bible = PHASE_0_BIBLE.model_copy(deep=True)
        bible.scenes[0].connections.append("nonexistent_scene")
        errors = validate_bible(bible)
        assert len(errors) >= 1


class TestGenerateBible:
    @pytest.mark.asyncio
    async def test_generate_bible_returns_none_on_bad_json(self):
        from worldgen.generator import generate_bible
        from unittest.mock import AsyncMock

        client = AsyncMock()
        client.generate.return_value = "这不是JSON"
        result = await generate_bible([], WorldState(), Player(), PHASE_0_BIBLE, client)
        assert result is None

    @pytest.mark.asyncio
    async def test_generate_bible_returns_valid_bible(self):
        from worldgen.generator import generate_bible
        from unittest.mock import AsyncMock

        minimal = {
            "phase_title": "筑基风云",
            "scenes": [s.model_dump() for s in PHASE_0_BIBLE.scenes],
            "factions": [f.model_dump() for f in PHASE_0_BIBLE.factions],
            "items": [i.model_dump() for i in PHASE_0_BIBLE.items],
            "skills": [s.model_dump() for s in PHASE_0_BIBLE.skills],
            "tensions": [t.model_dump() for t in PHASE_0_BIBLE.tensions],
            "npc_models": [n.model_dump() for n in PHASE_0_BIBLE.npc_models],
            "ending_hints": {},
        }

        import json
        client = AsyncMock()
        client.generate.return_value = json.dumps(minimal, ensure_ascii=False)
        result = await generate_bible([], WorldState(), Player(), PHASE_0_BIBLE, client)
        assert result is not None
        assert result.phase_id == PHASE_0_BIBLE.phase_id + 1


class TestRegenTrigger:
    def test_pressure_below_threshold_returns_false(self):
        ws = WorldState(world_pressure=5)
        assert check_regen(ws, PHASE_0_BIBLE) is False

    def test_pressure_at_threshold_with_no_active_progress_returns_true(self):
        ws = WorldState(
            world_pressure=15,
            tensions={"t1": TensionRuntime(status="active", progress={})},
        )
        assert check_regen(ws, PHASE_0_BIBLE) is True

    def test_pressure_at_threshold_with_active_progress_returns_false(self):
        ws = WorldState(
            world_pressure=15,
            tensions={"t1": TensionRuntime(status="active", progress={"p1": 30})},
        )
        assert check_regen(ws, PHASE_0_BIBLE) is False

    def test_sealed_world_never_triggers_regen(self):
        ws = WorldState(world_pressure=15, sealed=True)
        assert check_regen(ws, PHASE_0_BIBLE) is False

    def test_merge_bible_preserves_resolved_tensions(self):
        ws = WorldState(
            world_pressure=20,
            resolved_tensions=[ResolvedTension(
                tension_id="old", resolved_tick=5, path_id="done",
            )],
        )
        merged = merge_bible(ws, PHASE_0_BIBLE)
        assert merged.world_pressure == 0
        assert len(merged.resolved_tensions) == 1  # preserved
        assert merged.tensions["venture_bamboo"].status == "dormant"
