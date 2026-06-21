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
