"""Tests for M5 worldgen — schema validation, generation, regen trigger."""
import pytest
from engine.models import (
    WorldBible, WorldState, Player, PHASE_0_BIBLE,
    TensionSpec, TensionTrigger, TensionRuntime,
)
from worldgen.validator import validate_bible


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
