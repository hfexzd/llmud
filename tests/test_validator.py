"""Tests for the M3 settlement validator."""
import pytest
from engine.models import (
    DMResponse, WorldState, PHASE_0_BIBLE, Player, Intent,
    TensionRuntime,
)
from engine.validator import (
    validate_dm_proposal,
    scan_story_for_canon_violations,
)


# ---------------------------------------------------------------------------
# Canon checks
# ---------------------------------------------------------------------------

class TestCanonCheck:
    def test_valid_tension_id_passes(self):
        """A world_delta referencing a known tension id is allowed."""
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={"tension": {"venture_bamboo": {"pressure": 1}}},
        )
        clamped, violations, retry = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        assert clamped.world_delta == proposal.world_delta
        assert len(violations) == 0
        assert retry is False

    def test_unknown_tension_id_is_removed(self):
        """A world_delta referencing a non-existent tension is stripped."""
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={"tension": {"demon_invasion": {"pressure": 5}}},
        )
        clamped, violations, retry = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        assert "tension" not in (clamped.world_delta or {})
        assert len(violations) >= 1
        assert retry is True   # canon violation -> retry

    def test_unknown_npc_id_is_removed(self):
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={"npc": {"stranger_x": {"mood": "angry"}}},
        )
        clamped, violations, retry = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        assert "npc" not in (clamped.world_delta or {})
        assert len(violations) >= 1

    def test_unknown_faction_name_is_removed(self):
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={"faction": {"魔教": {"trust": 10}}},
        )
        clamped, violations, retry = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        assert "faction" not in (clamped.world_delta or {})
        assert len(violations) >= 1

    def test_mixed_valid_and_invalid_keeps_only_valid(self):
        """Valid keys survive; invalid ones are stripped."""
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={
                "tension": {
                    "venture_bamboo": {"pressure": 1},    # valid
                    "fake_tension": {"pressure": 99},     # invalid
                },
            },
        )
        clamped, violations, retry = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        wd = clamped.world_delta or {}
        assert "venture_bamboo" in wd.get("tension", {})
        assert "fake_tension" not in wd.get("tension", {})
        assert len(violations) >= 1
        assert retry is True

    def test_none_world_delta_passes(self):
        proposal = DMResponse(intent=Intent.OTHER, action_valid=True, world_delta=None)
        clamped, violations, retry = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        assert clamped.world_delta is None
        assert violations == []
        assert retry is False


# ---------------------------------------------------------------------------
# Numeric bounds
# ---------------------------------------------------------------------------

class TestNumericBounds:
    def test_progress_clamped_to_0_100(self):
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={"tension": {"venture_bamboo": {"progress": {"reach_bamboo": 150}}}},
        )
        clamped, violations, _ = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        actual = clamped.world_delta["tension"]["venture_bamboo"]["progress"]["reach_bamboo"]
        assert actual == 100
        assert len(violations) >= 1

    def test_negative_progress_clamped_to_0(self):
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={"tension": {"venture_bamboo": {"progress": {"reach_bamboo": -20}}}},
        )
        clamped, violations, _ = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        actual = clamped.world_delta["tension"]["venture_bamboo"]["progress"]["reach_bamboo"]
        assert actual == 0
        assert len(violations) >= 1

    def test_negative_pressure_clamped_to_0(self):
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={"tension": {"venture_bamboo": {"pressure": -5}}},
        )
        clamped, violations, _ = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        actual = clamped.world_delta["tension"]["venture_bamboo"]["pressure"]
        assert actual == 0
        assert len(violations) >= 1

    def test_faction_trust_clamped_to_0_100(self):
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={"faction": {"青云门": {"trust": 200}}},
        )
        clamped, violations, _ = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        actual = clamped.world_delta["faction"]["青云门"]["trust"]
        assert actual == 100
        assert len(violations) >= 1

    def test_valid_numeric_values_pass_unchanged(self):
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={
                "tension": {"venture_bamboo": {"pressure": 2, "progress": {"reach_bamboo": 30}}},
                "faction": {"青云门": {"trust": 5}},
            },
        )
        clamped, violations, _ = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        assert clamped.world_delta == proposal.world_delta
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# Causal plausibility
# ---------------------------------------------------------------------------

class TestCausalPlausibility:
    def test_active_tension_can_receive_progress(self):
        """An active tension can receive progress/pressure changes."""
        ws = WorldState(tensions={
            "venture_bamboo": TensionRuntime(status="active"),
        })
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={"tension": {"venture_bamboo": {"pressure": 1, "progress": {"reach_bamboo": 10}}}},
        )
        clamped, violations, _ = validate_dm_proposal(
            proposal, ws, PHASE_0_BIBLE, Player(),
        )
        assert clamped.world_delta == proposal.world_delta
        assert len(violations) == 0

    def test_dormant_tension_receiving_progress_is_flagged(self):
        """A dormant (not-yet-active) tension should not receive progress."""
        ws = WorldState(tensions={
            "venture_mountain": TensionRuntime(status="dormant"),
        })
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={"tension": {"venture_mountain": {"pressure": 3}}},
        )
        clamped, violations, _ = validate_dm_proposal(
            proposal, ws, PHASE_0_BIBLE, Player(),
        )
        # The tension delta should be removed -- tension isn't active yet.
        assert "venture_mountain" not in (clamped.world_delta or {}).get("tension", {})
        assert len(violations) >= 1


# ---------------------------------------------------------------------------
# Personality consistency
# ---------------------------------------------------------------------------

class TestPersonalityConsistency:
    def test_known_npc_mood_update_passes(self):
        """Updating a known NPC's mood is allowed."""
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={"npc": {"linwaner": {"mood": "hopeful"}}},
        )
        ws = WorldState()
        clamped, violations, _ = validate_dm_proposal(
            proposal, ws, PHASE_0_BIBLE, Player(),
        )
        assert clamped.world_delta == proposal.world_delta
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# validate_dm_proposal -- combined
# ---------------------------------------------------------------------------

class TestValidateDmProposal:
    def test_empty_proposal_passes(self):
        proposal = DMResponse(intent=Intent.OTHER, action_valid=True)
        clamped, violations, retry = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        assert clamped == proposal
        assert violations == []
        assert retry is False

    def test_invalid_action_skips_validation(self):
        """When action_valid=False, the validator passes through unchanged."""
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=False,
            invalid_reason="something",
            world_delta={"tension": {"fake": {"pressure": 1}}},
        )
        clamped, violations, retry = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        assert clamped == proposal   # untouched
        assert violations == []
        assert retry is False

    def test_multiple_violation_types_accumulate(self):
        """All violation types are collected in one pass."""
        proposal = DMResponse(
            intent=Intent.OTHER, action_valid=True,
            world_delta={
                "tension": {
                    "fake_tension": {"pressure": 5},              # canon
                    "venture_bamboo": {"progress": {"reach_bamboo": 999}},  # numeric
                },
            },
        )
        clamped, violations, retry = validate_dm_proposal(
            proposal, WorldState(), PHASE_0_BIBLE, Player(),
        )
        assert len(violations) >= 2
        assert retry is True  # canon violation triggers retry


# ---------------------------------------------------------------------------
# Story scanner (post-hoc, log-only)
# ---------------------------------------------------------------------------

class TestStoryScan:
    def test_story_with_known_entities_has_no_violations(self):
        violations = scan_story_for_canon_violations(
            "你来到青云门外门，看到林婉儿正在修炼。", PHASE_0_BIBLE,
        )
        assert violations == []

    def test_story_with_unknown_location_is_flagged(self):
        violations = scan_story_for_canon_violations(
            "你穿过竹林来到了断崖洞窟。", PHASE_0_BIBLE,
        )
        assert len(violations) >= 1
        assert any("断崖洞窟" in v for v in violations)

    def test_story_with_unknown_enemy_is_flagged(self):
        violations = scan_story_for_canon_violations(
            "一只铁背蜥从暗处窜出！", PHASE_0_BIBLE,
        )
        assert len(violations) >= 1
        assert any("铁背蜥" in v for v in violations)

    def test_empty_story_has_no_violations(self):
        assert scan_story_for_canon_violations("", PHASE_0_BIBLE) == []
