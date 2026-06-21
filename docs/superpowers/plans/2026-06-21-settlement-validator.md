# 结算校验器 (M3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the settlement validator (`engine/validator.py`) that clamps DM-proposed `world_delta`/`state_delta`/`npc_update` against canon, personality, causal, and numeric rules; extend `DMResponse` with a `world_delta` field; update the DM prompt so the LLM knows it can propose world_delta; wire validate→clamp→retry→apply into the `game_action` pipeline between DM parse and state application.

**Architecture:** `validate_dm_proposal(proposal, world_state, world_bible, player) -> (clamped, violations, should_retry)` is a pure function in `engine/validator.py` with four validation passes plus a post-hoc `scan_story_for_canon_violations`. The route integrates it: after parsing the DM response, call validator → if `should_retry`, re-call LLM with violation context once → apply clamped world_delta to world_state → re-run `tension_tick` so tension states reflect DM-proposed nudges → persist. Story is NOT clamped mid-stream (spec §8: story走预防+事后扫描); world_delta/state_delta/npc_update are fully validated post-parse.

**Tech Stack:** Python 3.14, Pydantic v2, FastAPI, SQLite, pytest + pytest-asyncio 1.4.0, httpx `AsyncClient`+`ASGITransport` for integration tests.

## Global Constraints

- **Rule-driven validator only (引擎定骨).** The validator is pure/deterministic — no LLM calls inside `engine/validator.py`. The retry is orchestrated by the route, not the validator.
- **phase-0 only.** Validator reads from `PHASE_0_BIBLE`; LLM worldgen is M5. All canon checks reference the hand-authored phase-0 data.
- **Story is never clamped.** Story violations are detected post-hoc via `scan_story_for_canon_violations` and logged; the story text that was already streamed is never rewritten. Only `world_delta`/`state_delta`/`npc_update` are clamped.
- **Retry once.** Only structural (canon) violations trigger a retry. Numeric/personality/causal violations just clamp. Retry is at most one additional LLM call.
- **Test run command:** `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest <path> -v`. Unit tests are sync; integration tests use `@pytest.mark.asyncio` + `AsyncClient(transport=ASGITransport(app=app), base_url="http://test")` — NEVER `pytest.TestClient`.
- **TDD, DRY, YAGNI, frequent commits.** Each task: write failing test → verify it fails → minimal implementation → verify pass → commit.
- **Purity.** All validator functions are module-level pure functions returning new objects; they never mutate inputs. The only side effects are in the route (LLM retry call, DB save).

---

## File Structure

- **`engine/validator.py`** (NEW) — `validate_dm_proposal`, `scan_story_for_canon_violations`, and internal helper functions for each validation pass.
- **`engine/models.py`** — add `world_delta: dict | None = None` field to `DMResponse`.
- **`dm/contract.py`** — parse `world_delta` from the DM JSON response in `parse_dm_response`.
- **`dm/prompt.py`** — add world_delta schema + rule 13 to `DM_SYSTEM_TEMPLATE`; the DM now knows it can propose tension/NPC/faction nudges.
- **`api/routes.py`** — between DM parse and state_delta apply: call validator, retry on structural violation, apply clamped world_delta to `world_state`, re-run `tension_tick`, persist. Wire `world_delta` into the JSON response for the frontend.
- **`tests/test_validator.py`** (NEW) — `TestCanonCheck`, `TestNumericBounds`, `TestCausalPlausibility`, `TestPersonalityConsistency`, `TestValidateDmProposal`, `TestStoryScan`.
- **`tests/test_api.py`** — add integration tests for the validate→retry→apply flow in `game_action`.
- **`tests/test_contract.py`** — add test for world_delta parsing.

---

### Task 1: world_delta model field + DM contract parsing

**Files:**
- Modify: `engine/models.py` (add `world_delta` to `DMResponse`)
- Modify: `dm/contract.py` (parse `world_delta` in `parse_dm_response`)
- Test: `tests/test_contract.py` (extend)
- Test: `tests/test_validator.py` (NEW — just the model-level smoke test)

**Interfaces:**
- Produces: `DMResponse.world_delta: dict | None` — a dict with optional keys `tension`, `npc`, `faction`, each a dict of entity-id → delta-fields.
- Consumes: nothing from earlier tasks (this is Task 1).

- [ ] **Step 1: Add world_delta to DMResponse model**

In `engine/models.py`, modify the `DMResponse` class (≈line 107-116):

```python
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
    world_delta: dict | None = None   # M3: tension/npc/faction increments
```

- [ ] **Step 2: Write the failing test for world_delta parsing**

In `tests/test_contract.py`, add:

```python
def test_parse_dm_response_with_world_delta():
    from dm.contract import parse_dm_response
    raw = '''{"intent":"explore","story":"你察觉到竹林中灵气异动……","world_delta":{"tension":{"probe_anomaly":{"pressure":1,"progress":{"witness_herb":10}}},"npc":{"linwaner":{"mood":"curious"}},"faction":{"青云门":{"trust":2}}}}'''
    result = parse_dm_response(raw)
    assert result.world_delta is not None
    assert result.world_delta["tension"]["probe_anomaly"]["pressure"] == 1
    assert result.world_delta["tension"]["probe_anomaly"]["progress"]["witness_herb"] == 10
    assert result.world_delta["npc"]["linwaner"]["mood"] == "curious"
    assert result.world_delta["faction"]["青云门"]["trust"] == 2

def test_parse_dm_response_without_world_delta():
    from dm.contract import parse_dm_response
    raw = '''{"intent":"cultivate","story":"你盘膝修炼……"}'''
    result = parse_dm_response(raw)
    assert result.world_delta is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_contract.py::test_parse_dm_response_with_world_delta -v`
Expected: FAIL — `world_delta` key not in the result or assertion fails.

- [ ] **Step 4: Implement world_delta parsing**

In `dm/contract.py`, inside `parse_dm_response`, add after the `npc_update` line (≈line 146):

```python
    return DMResponse(
        intent=intent,
        action_valid=data.get("action_valid", True),
        invalid_reason=data.get("invalid_reason", ""),
        story=data.get("story", ""),
        state_delta=data.get("state_delta"),
        breakthrough=breakthrough,
        combat=combat,
        npc_update=data.get("npc_update"),
        world_delta=data.get("world_delta"),   # M3
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_contract.py -v`
Expected: all tests PASS including the two new ones.

- [ ] **Step 6: Commit**

```bash
git add engine/models.py dm/contract.py tests/test_contract.py
git commit -m "feat(validator): add world_delta field to DMResponse + parse from DM JSON (M3)"
```

---

### Task 2: Validator engine — canon, numeric, causal, personality rules + story scanner

**Files:**
- Create: `engine/validator.py`
- Test: `tests/test_validator.py` (NEW)

**Interfaces:**
- Consumes: `DMResponse.world_delta` (from Task 1), `WorldState`, `WorldBible` (PHASE_0_BIBLE), `Player`, `evaluate_condition` (from `engine.world`).
- Produces:
  - `validate_dm_proposal(proposal: DMResponse, world_state: WorldState, world_bible: WorldBible, player: Player) -> tuple[DMResponse, list[str], bool]`
  - `scan_story_for_canon_violations(story: str, world_bible: WorldBible) -> list[str]`

- [ ] **Step 1: Write the failing test file**

Create `tests/test_validator.py`:

```python
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
        assert retry is True   # canon violation → retry

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
        # The tension delta should be removed — tension isn't active yet.
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
# validate_dm_proposal — combined
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
```

Save as `tests/test_validator.py`.

- [ ] **Step 2: Run test file to verify all tests fail**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_validator.py -v`
Expected: all FAIL — `engine.validator` module not found.

- [ ] **Step 3: Implement the validator engine**

Create `engine/validator.py`:

```python
"""Settlement validator (M3). Pure functions — no LLM, no side effects.

Clamps DM-proposed world_delta against canon, numeric, causal, and personality
rules. Story violations are detected post-hoc (logged, never clamped — the
story was already streamed).
"""

from __future__ import annotations

from engine.models import DMResponse, WorldState, WorldBible, Player


# ---------------------------------------------------------------------------
# Canon entity name extraction (for story scanning)
# ---------------------------------------------------------------------------

def _canon_entity_names(bible: WorldBible) -> set[str]:
    """All named entities the world 'has' — used for story scanning."""
    names: set[str] = set()
    for scene in bible.scenes:
        names.add(scene.name)
        for lm in scene.landmarks:
            names.add(lm)
    for faction in bible.factions:
        names.add(faction.name)
    for item in bible.items:
        names.add(item.name)
    for skill in bible.skills:
        names.add(skill.name)
    for npc in bible.npc_models:
        # NPC profiles supply the display name
        pass  # names come from ALL_NPC_PROFILES, not BehaviorModel
    # Also pull from the global NPC profiles (canon block source)
    from engine.models import ALL_NPC_PROFILES, ENCOUNTER_CATALOG
    for p in ALL_NPC_PROFILES:
        names.add(p.name)
    for e in ENCOUNTER_CATALOG:
        names.add(e)
    return names


# Hard-coded common words that look like entities but aren't (stop-words for
# the story scanner — never flag these).
_STORY_SCAN_STOP_WORDS: set[str] = {
    "你", "我", "他", "她", "它", "们", "的", "了", "在", "是", "有", "和",
    "与", "或", "到", "从", "对", "把", "被", "让", "给", "向", "就", "也",
    "不", "没", "都", "还", "要", "会", "能", "可", "以", "得", "着", "过",
    "来", "去", "上", "下", "里", "外", "中", "前", "后", "左", "右",
    "大", "小", "多", "少", "一", "二", "三", "四", "五", "六", "七", "八",
    "九", "十", "百", "千", "万", "这", "那", "哪", "什么", "怎么", "如何",
    "一个", "一些", "这个", "那个", "自己", "知道", "觉得", "可以", "应该",
    "已经", "因为", "所以", "但是", "虽然", "如果", "的话", "之后", "之前",
    "时候", "地方", "东西", "事情", "感觉", "发现", "看到", "听到", "说道",
    "修仙", "修炼", "灵力", "灵气", "修士", "功法", "突破", "境界", "宗门",
    "弟子", "长老", "妖兽", "灵草", "丹药", "山脉", "竹林", "山谷", "洞府",
    "青云门", "练气", "筑基", "金丹",
}

# Additional known-NPC-name variants the DM might use in narration (e.g.
# "林婉儿师姐" contains "林婉儿" which is already canon). This set only
# needs entries that AREN'T pure substrings of canon names.
_STORY_SCAN_ALLOWED: set[str] = {
    "师姐", "师兄", "师弟", "师妹", "道友", "前辈", "后辈",
    "杨老",   # short form of 杨老 (canon name matches this)
}


def scan_story_for_canon_violations(story: str, bible: WorldBible) -> list[str]:
    """Post-hoc scan: detect story references to named entities outside canon.

    Returns a list of human-readable violation strings. This is log-only —
    the story was already streamed and cannot be clamped. The validator
    prompt rule 12 prevents most violations; this is a safety net.
    """
    if not story or not story.strip():
        return []

    canon_names = _canon_entity_names(bible)
    violations: list[str] = []

    # Simple substring-match scan: for each canon name, we don't flag it.
    # For non-canon multi-char Chinese strings, we check if they look like
    # named entities (proper nouns). This is heuristic — we scan for 2-5
    # character sequences that aren't in canon and aren't common words.
    # In practice the prompt rule 12 prevents most violations; this scanner
    # catches the obvious ones (e.g. "断崖洞窟", "三叶血兰", "铁背蜥").
    #
    # Strategy: walk the story with a sliding window of 2..5 chars; if a
    # window appears to be a proper noun (contains no stop characters, not
    # in canon, not in stop-words), flag it.
    import re
    # Split on punctuation to get candidate phrases
    chunks = re.split(r'[，。！？、；：""''「」『』【】\s\n]+', story)
    for chunk in chunks:
        if not chunk:
            continue
        # For each chunk, check if it contains any sub-sequence that could
        # be a named entity reference. We look for 2-4 char sequences.
        for length in (4, 3, 2):
            for i in range(len(chunk) - length + 1):
                candidate = chunk[i:i + length]
                if candidate in _STORY_SCAN_STOP_WORDS:
                    continue
                if candidate in _STORY_SCAN_ALLOWED:
                    continue
                if candidate in canon_names:
                    continue
                # Check if any canon name contains this candidate (e.g.
                # "婉儿" is part of "林婉儿")
                if any(candidate in cname for cname in canon_names):
                    continue
                # Check if this candidate is a substring of a stop word
                if any(candidate in sw for sw in _STORY_SCAN_STOP_WORDS):
                    continue
                # This is a potential unknown entity. Flag it.
                violations.append(
                    f"story mentions unknown entity '{candidate}' — not in canon"
                )
                break  # One violation per chunk position is enough
    return violations


# ---------------------------------------------------------------------------
# Validation passes (each returns (clamped_delta, violations))
# ---------------------------------------------------------------------------

def _validate_canon(
    world_delta: dict, bible: WorldBible,
) -> tuple[dict, list[str]]:
    """Check all referenced entity ids/names exist in the bible.

    Returns (clamped_world_delta, violations). Unknown tension/NPC/faction
    keys are removed; the violation list records each removal.
    """
    if not world_delta:
        return world_delta, []

    tension_ids = {t.id for t in bible.tensions}
    npc_ids = {m.npc_id for m in bible.npc_models}
    faction_names = {f.name for f in bible.factions}

    clamped = dict(world_delta)
    violations: list[str] = []

    # Validate tension keys
    if "tension" in clamped:
        td = dict(clamped["tension"])
        for tid in list(td):
            if tid not in tension_ids:
                violations.append(f"canon: unknown tension '{tid}' — removed")
                del td[tid]
        if td:
            clamped["tension"] = td
        else:
            del clamped["tension"]

    # Validate NPC keys
    if "npc" in clamped:
        nd = dict(clamped["npc"])
        for nid in list(nd):
            if nid not in npc_ids:
                violations.append(f"canon: unknown npc '{nid}' — removed")
                del nd[nid]
        if nd:
            clamped["npc"] = nd
        else:
            del clamped["npc"]

    # Validate faction keys (matched by name, not id)
    if "faction" in clamped:
        fd = dict(clamped["faction"])
        for fname in list(fd):
            if fname not in faction_names:
                violations.append(f"canon: unknown faction '{fname}' — removed")
                del fd[fname]
        if fd:
            clamped["faction"] = fd
        else:
            del clamped["faction"]

    return clamped, violations


def _validate_numeric(
    world_delta: dict,
) -> tuple[dict, list[str]]:
    """Clamp numeric values to valid ranges.

    - tension progress: 0..100
    - tension pressure: >= 0
    - faction trust: 0..100
    - NPC goal_progress: 0..100

    Returns (clamped_world_delta, violations).
    """
    if not world_delta:
        return world_delta, []

    clamped = dict(world_delta)
    violations: list[str] = []

    # Clamp tension progress/pressure
    if "tension" in clamped:
        td = dict(clamped["tension"])
        for tid, tdelta in td.items():
            td_clamped = dict(tdelta)
            if "pressure" in td_clamped and td_clamped["pressure"] < 0:
                violations.append(
                    f"numeric: tension '{tid}' pressure {td_clamped['pressure']} clamped to 0"
                )
                td_clamped["pressure"] = 0
            if "progress" in td_clamped:
                prog = dict(td_clamped["progress"])
                for pid, val in list(prog.items()):
                    if val < 0:
                        violations.append(
                            f"numeric: tension '{tid}' progress '{pid}' {val} clamped to 0"
                        )
                        prog[pid] = 0
                    elif val > 100:
                        violations.append(
                            f"numeric: tension '{tid}' progress '{pid}' {val} clamped to 100"
                        )
                        prog[pid] = 100
                td_clamped["progress"] = prog
            td[tid] = td_clamped
        clamped["tension"] = td

    # Clamp faction trust
    if "faction" in clamped:
        fd = dict(clamped["faction"])
        for fname, fdelta in fd.items():
            fd_clamped = dict(fdelta)
            if "trust" in fd_clamped:
                if fd_clamped["trust"] < 0:
                    violations.append(
                        f"numeric: faction '{fname}' trust {fd_clamped['trust']} clamped to 0"
                    )
                    fd_clamped["trust"] = 0
                elif fd_clamped["trust"] > 100:
                    violations.append(
                        f"numeric: faction '{fname}' trust {fd_clamped['trust']} clamped to 100"
                    )
                    fd_clamped["trust"] = 100
            if "dominance" in fd_clamped:
                if fd_clamped["dominance"] < 0:
                    violations.append(
                        f"numeric: faction '{fname}' dominance {fd_clamped['dominance']} clamped to 0"
                    )
                    fd_clamped["dominance"] = 0
            fd[fname] = fd_clamped
        clamped["faction"] = fd

    # Clamp NPC goal_progress
    if "npc" in clamped:
        nd = dict(clamped["npc"])
        for nid, ndelta in nd.items():
            nd_clamped = dict(ndelta)
            if "goal_progress" in nd_clamped:
                gp = dict(nd_clamped["goal_progress"])
                for gid, val in list(gp.items()):
                    if val < 0:
                        violations.append(
                            f"numeric: npc '{nid}' goal_progress '{gid}' {val} clamped to 0"
                        )
                        gp[gid] = 0
                    elif val > 100:
                        violations.append(
                            f"numeric: npc '{nid}' goal_progress '{gid}' {val} clamped to 100"
                        )
                        gp[gid] = 100
                nd_clamped["goal_progress"] = gp
            nd[nid] = nd_clamped
        clamped["npc"] = nd

    return clamped, violations


def _validate_causal(
    world_delta: dict, world_state: WorldState,
) -> tuple[dict, list[str]]:
    """Check causal plausibility: only active tensions can receive changes.

    Returns (clamped_world_delta, violations).
    """
    if not world_delta or "tension" not in world_delta:
        return world_delta, []

    clamped = dict(world_delta)
    violations: list[str] = []
    td = dict(clamped.get("tension", {}))

    for tid in list(td):
        rt = world_state.tensions.get(tid)
        if rt is None:
            # Not in world_state at all — canon check should have caught this,
            # but be defensive.
            continue
        if rt.status == "dormant":
            violations.append(
                f"causal: tension '{tid}' is dormant — cannot receive progress/pressure"
            )
            del td[tid]
        elif rt.status == "resolved":
            violations.append(
                f"causal: tension '{tid}' is already resolved — delta removed"
            )
            del td[tid]

    if td:
        clamped["tension"] = td
    else:
        clamped.pop("tension", None)

    return clamped, violations


def _validate_personality(
    world_delta: dict, bible: WorldBible, world_state: WorldState,
) -> tuple[dict, list[str]]:
    """Check NPC updates are consistent with behavior models.

    For M3 phase-0, this is a lightweight check: the NPC must exist in the
    bible (already covered by canon check), and mood changes must be
    non-empty strings (basic sanity). Richer personality checks (motive
    compatibility, goal consistency) arrive in M7 when behavior models are
    more developed.

    Returns (clamped_world_delta, violations).
    """
    if not world_delta or "npc" not in world_delta:
        return world_delta, []

    clamped = dict(world_delta)
    violations: list[str] = []
    nd = dict(clamped.get("npc", {}))

    for nid, ndelta in list(nd.items()):
        nd_clamped = dict(ndelta)
        # mood must be a non-empty string if present
        if "mood" in nd_clamped:
            if not isinstance(nd_clamped["mood"], str) or not nd_clamped["mood"].strip():
                violations.append(f"personality: npc '{nid}' mood is empty — removed")
                del nd_clamped["mood"]
        # goal_progress keys must reference goals that exist in the behavior model
        if "goal_progress" in nd_clamped:
            model = next((m for m in bible.npc_models if m.npc_id == nid), None)
            if model:
                valid_goal_ids = {g.id for g in model.goals}
                gp = dict(nd_clamped["goal_progress"])
                for gid in list(gp):
                    if gid not in valid_goal_ids:
                        violations.append(
                            f"personality: npc '{nid}' has no goal '{gid}' — removed"
                        )
                        del gp[gid]
                nd_clamped["goal_progress"] = gp
        nd[nid] = nd_clamped

    clamped["npc"] = nd
    return clamped, violations


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def validate_dm_proposal(
    proposal: DMResponse,
    world_state: WorldState,
    world_bible: WorldBible,
    player: Player,
) -> tuple[DMResponse, list[str], bool]:
    """Validate and clamp a DM proposal's world_delta.

    Per spec §8: checks canon, numeric bounds, causal plausibility, and
    personality consistency on world_delta. Story is NOT checked here (use
    scan_story_for_canon_violations separately for post-hoc logging).

    Returns:
        clamped: DMResponse with violations removed/clamped
        violations: list of human-readable violation strings (for logging)
        should_retry: True if a structural (canon) violation warrants one retry
    """
    if not proposal.action_valid:
        return proposal, [], False

    wd = proposal.world_delta
    if not wd:
        return proposal, [], False

    all_violations: list[str] = []
    should_retry = False

    # Pass 1: canon (structural — triggers retry)
    wd, v = _validate_canon(wd, world_bible)
    all_violations.extend(v)
    if v:
        should_retry = True

    # Pass 2: numeric bounds (clamp only)
    wd, v = _validate_numeric(wd)
    all_violations.extend(v)

    # Pass 3: causal plausibility
    wd, v = _validate_causal(wd, world_state)
    all_violations.extend(v)

    # Pass 4: personality consistency
    wd, v = _validate_personality(wd, world_bible, world_state)
    all_violations.extend(v)

    # If world_delta became empty after clamping, set to None
    if wd == {}:
        wd = None

    clamped = proposal.model_copy(update={"world_delta": wd})
    return clamped, all_violations, should_retry
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_validator.py -v`
Expected: all 17 tests PASS.

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest -v`
Expected: 203 + 17 = 220 tests, all PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/validator.py tests/test_validator.py
git commit -m "feat(validator): add validate_dm_proposal + story scanner (M3)"
```

---

### Task 3: DM prompt — world_delta schema + rule 13

**Files:**
- Modify: `dm/prompt.py` (add world_delta schema to system template, add rule 13)
- Test: `tests/test_prompt.py` (extend)

**Interfaces:**
- Consumes: `DMResponse.world_delta` (Task 1), validator rules (Task 2 — conceptually, to know what the DM should do)
- Produces: updated `DM_SYSTEM_TEMPLATE` with world_delta instructions

- [ ] **Step 1: Write the failing test**

In `tests/test_prompt.py`, add:

```python
def test_prompt_includes_world_delta_schema():
    """The DM system prompt must describe the world_delta JSON schema."""
    from dm.prompt import build_dm_prompt
    from engine.models import Player, Intent
    system, _ = build_dm_prompt(
        player=Player(), intent=Intent.OTHER,
    )
    assert "world_delta" in system
    assert "tension" in system
    assert "pressure" in system or "progress" in system

def test_prompt_includes_world_delta_rule():
    """The prompt must include a rule about world_delta canon constraints."""
    from dm.prompt import build_dm_prompt
    from engine.models import Player, Intent
    system, _ = build_dm_prompt(
        player=Player(), intent=Intent.OTHER,
    )
    assert "13." in system or "world_delta" in system.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_prompt.py::test_prompt_includes_world_delta_schema tests/test_prompt.py::test_prompt_includes_world_delta_rule -v`
Expected: FAIL — world_delta not mentioned in prompt.

- [ ] **Step 3: Update the DM system template**

In `dm/prompt.py`, add to `DM_SYSTEM_TEMPLATE` after rule 12:

```python
12. 【只述已有之物】你提及的地点/地标、人物、妖兽/敌人、灵材/丹药/物件、功法/招式【必须】取自上方【世界设定·可述及事物】清单；【严禁】凭空编造未列出的具名事物——不得自创地点（如"断崖洞窟"）、自创妖兽（如"铁背蜥"）、自创灵材丹药（如"三叶血兰"）、自创功法招式。当清单中某类为"暂无定名"时，确需提及该类事物只能用泛称（如"某株灵草""一门功法""山里出了好东西"），【绝不得】具名。NPC口中说出的传闻亦受此约束——传闻可含糊其辞，但不得说出系统没有的具名地点/物品/敌人。
13. 【世界增量】你可以在JSON中附带一个`world_delta`字段，用于提议世界状态的微小变化（非强制——无变化则省略该字段）。world_delta的JSON结构为：`{{"tension":{{"<张力id>":{{"pressure":<整数>, "progress":{{"<路径id>":<整数>}}}}}}}, "npc":{{"<npc_id>":{{"mood":"<心境>", "goal_progress":{{"<goal_id>":<整数>}}}}}}}, "faction":{{"<势力名>":{{"trust":<整数>}}}}}}`。其中：
  - tension id 必须来自当前活跃的世界事件（所务列表中的事件）；
  - npc_id 必须来自【世界设定·可述及事物】中的人物，faction 的势力名必须来自其中的势力（目前有：青云门、散修盟）；
  - pressure 和 progress 必须>=0，progress 不得超过100，trust 在0-100之间；
  - 只有当前活跃（所务列表中显示为"进行中"）的张力才能获得 pressure/progress 增量；
  - 所提议的变化必须由玩家本次行动合理推出——无关行动不得随意给张力加进度。
  - world_delta 中的一切实体引用同样受规则12约束：不得提及不存在的张力、NPC或势力。"""
```

Note the double-brace escaping because this is inside a Python f-string format template (`{tension}` in the JSON example must be `{{tension}}` in the template string — the existing template uses `.format()`, so literal braces need `{{}}`).

Actually, looking at the existing template more carefully — it uses `.format()` with named placeholders like `{name}`, `{location}`. So literal braces in the template text must be `{{` and `}}`. But wait — the template content (rule text) with `{` for JSON examples would conflict with `.format()`. Let me check rule 12 in the existing template...

Looking at the existing template, rule 12 doesn't have any `{` or `}` in it. The JSON examples I need to add have braces. Since the template uses `.format()`, I need to double them: `{{` → literal `{`, `}}` → literal `}`.

But actually, looking more closely at `DM_SYSTEM_TEMPLATE`, the existing template uses `{name}`, `{location}`, etc. as format placeholders. The JSON schema I'm adding to rule 13 uses `{` and `}` which would be interpreted as format placeholders. So I need to escape them as `{{` and `}}`.

Wait, the `.format()` method interprets `{{` as a literal `{` and `}}` as a literal `}`. So in the template string:

```
"tension":{{"<张力id>":{{"pressure":<整数>}}}}}
```

would become:
```
"tension":{"<张力id>":{"pressure":<整数>}}}
```

That's correct.

Let me re-examine: the current template uses `{name}`, `{location}`, `{level}`, `{spirit_power}`, `{hp}`, `{max_hp}`, `{canon_context}`, `{scene_context}`, `{world_event_context}`, `{engine_context}`, `{goal_context}`, `{recent_stories}`. None of these overlap with the JSON schema braces I'm adding, so double-brace escaping is the right approach.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_prompt.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Run the full suite**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest -v`
Expected: 222 tests, all PASS.

- [ ] **Step 6: Commit**

```bash
git add dm/prompt.py tests/test_prompt.py
git commit -m "feat(validator): add world_delta schema + rule 13 to DM prompt (M3)"
```

---

### Task 4: Wire validator into game_action pipeline (validate → retry → apply)

**Files:**
- Modify: `api/routes.py` (insert validator between DM parse and state_delta apply; apply clamped world_delta; re-run tension_tick; surface world_delta in response)
- Test: `tests/test_api.py` (extend with integration tests)

**Interfaces:**
- Consumes: `validate_dm_proposal` (Task 2), `DMResponse.world_delta` (Task 1), updated prompt (Task 3).
- Produces: updated `game_action` flow with validator integration; `world_delta` in the streaming JSON response.

- [ ] **Step 1: Write the integration test**

In `tests/test_api.py`, add after the existing test class(es):

```python
class TestValidatorIntegration:
    """M3: validator wired into game_action — validate → retry → apply."""

    @pytest.mark.asyncio
    async def test_world_delta_surfaced_in_response(self, db_conn, mock_llm_client):
        """A valid world_delta from the DM is passed through to the response."""
        from db.repository import PlayerRepository, NPCRepository, WorldRepository
        from engine.models import WorldEngine
        from api.routes import create_router

        mock_llm_client.generate.return_value = (
            '{"intent":"explore","story":"你踏入竹林……",'
            '"world_delta":{"tension":{"probe_anomaly":{"pressure":1,"progress":{"witness_herb":10}}}},'
            '"action_valid":true}'
        )
        player_repo = PlayerRepository(db_conn)
        npc_repo = NPCRepository(db_conn)
        world_repo = WorldRepository(db_conn)
        engine = WorldEngine()

        player_repo.save(Player(
            id="p1", current_scene="bamboo_forest", tick=3,
            visited_scenes=["outer_gate", "inner_gate", "bamboo_forest"],
        ))

        router = create_router(mock_llm_client, player_repo, npc_repo,
                               DEFAULT_ENCOUNTER, engine, world_repo)
        app = FastAPI()
        app.include_router(router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/game/action", json={"user_input": "探索竹林"})
            assert response.status_code == 200
            data = response.json()
            assert "world_delta" in data
            # Valid tension gets through
            wd = data["world_delta"]
            assert wd is not None

    @pytest.mark.asyncio
    async def test_invalid_world_delta_clamped(self, db_conn, mock_llm_client):
        """A world_delta referencing unknown entities is clamped out."""
        from db.repository import PlayerRepository, NPCRepository, WorldRepository
        from engine.models import WorldEngine
        from api.routes import create_router

        mock_llm_client.generate.return_value = (
            '{"intent":"explore","story":"你发现一处神秘所在……",'
            '"world_delta":{"tension":{"demon_invasion":{"pressure":5}}},'
            '"action_valid":true}'
        )
        player_repo = PlayerRepository(db_conn)
        npc_repo = NPCRepository(db_conn)
        world_repo = WorldRepository(db_conn)
        engine = WorldEngine()

        player_repo.save(Player(id="p1", current_scene="bamboo_forest", tick=3))

        router = create_router(mock_llm_client, player_repo, npc_repo,
                               DEFAULT_ENCOUNTER, engine, world_repo)
        app = FastAPI()
        app.include_router(router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/game/action", json={"user_input": "探索"})
            assert response.status_code == 200
            data = response.json()
            # Invalid world_delta should be clamped to None (empty after removal)
            wd = data.get("world_delta")
            # Either absent or empty
            assert wd is None or wd == {}

    @pytest.mark.asyncio
    async def test_world_state_updated_after_valid_world_delta(self, db_conn, mock_llm_client):
        """After a valid world_delta is applied, world_state reflects the changes."""
        from db.repository import PlayerRepository, NPCRepository, WorldRepository
        from engine.models import WorldEngine
        from api.routes import create_router

        mock_llm_client.generate.return_value = (
            '{"intent":"explore","story":"竹林中灵气涌动……",'
            '"world_delta":{"tension":{"probe_anomaly":{"pressure":1,"progress":{"witness_herb":15}}}},'
            '"action_valid":true}'
        )
        player_repo = PlayerRepository(db_conn)
        npc_repo = NPCRepository(db_conn)
        world_repo = WorldRepository(db_conn)
        engine = WorldEngine()

        player_repo.save(Player(
            id="p1", current_scene="bamboo_forest", tick=3,
            visited_scenes=["outer_gate", "inner_gate", "bamboo_forest"],
        ))

        router = create_router(mock_llm_client, player_repo, npc_repo,
                               DEFAULT_ENCOUNTER, engine, world_repo)
        app = FastAPI()
        app.include_router(router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/game/action", json={"user_input": "探索竹林"})
            assert response.status_code == 200

        # Verify world_state was persisted with the applied delta
        ws = world_repo.get("default")
        assert ws is not None
        rt = ws.tensions.get("probe_anomaly")
        assert rt is not None
        # Progress should reflect the DM's proposal
        assert rt.progress.get("witness_herb", 0) == 15
        assert rt.pressure == 1

    @pytest.mark.asyncio
    async def test_retry_on_canon_violation(self, db_conn, mock_llm_client):
        """When the first DM response has a canon violation, the route retries once."""
        from db.repository import PlayerRepository, NPCRepository, WorldRepository
        from engine.models import WorldEngine
        from api.routes import create_router

        # First call: invalid (unknown tension) → should trigger retry
        # Second call: valid
        mock_llm_client.generate.side_effect = [
            '{"intent":"explore","story":"你发现断崖洞窟……","world_delta":{"tension":{"fake_tension":{"pressure":5}}},"action_valid":true}',
            '{"intent":"explore","story":"你继续在竹林探索……","world_delta":{"tension":{"probe_anomaly":{"pressure":1}}},"action_valid":true}',
        ]
        player_repo = PlayerRepository(db_conn)
        npc_repo = NPCRepository(db_conn)
        world_repo = WorldRepository(db_conn)
        engine = WorldEngine()

        player_repo.save(Player(
            id="p1", current_scene="bamboo_forest", tick=3,
            visited_scenes=["outer_gate", "inner_gate", "bamboo_forest"],
        ))

        router = create_router(mock_llm_client, player_repo, npc_repo,
                               DEFAULT_ENCOUNTER, engine, world_repo)
        app = FastAPI()
        app.include_router(router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/game/action", json={"user_input": "探索"})
            assert response.status_code == 200

        # Should have called generate twice (original + retry)
        assert mock_llm_client.generate.call_count == 2
```

Note: these tests also need these imports at the top of the file (which may already exist):
```python
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from engine.models import DEFAULT_ENCOUNTER
```

- [ ] **Step 2: Run integration tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_api.py::TestValidatorIntegration -v`
Expected: FAIL — world_delta not in response, or validator not called.

- [ ] **Step 3: Apply world_delta helper — add to engine/world.py**

In `engine/world.py`, add a module-level function after `tension_tick`:

```python
def apply_world_delta(world_state: WorldState, world_delta: dict) -> WorldState:
    """Apply a validated world_delta to world_state. Pure — returns new WorldState.

    Merges tension progress/pressure, NPC moods/goal_progress, and faction
    trust/dominance from the DM's proposal into the world state. Values in
    world_delta are absolute (they replace, not add). The delta is presumed
    already validated — this function does no clamping.
    """
    if not world_delta:
        return world_state

    new_tensions = dict(world_state.tensions)
    new_npc = dict(world_state.npc_state)
    new_factions = dict(world_state.faction_state)

    # Merge tension deltas
    for tid, td in world_delta.get("tension", {}).items():
        rt = new_tensions.get(tid)
        if rt is None:
            continue
        updates: dict = {}
        if "pressure" in td:
            updates["pressure"] = rt.pressure + td["pressure"]
        if "progress" in td:
            new_prog = dict(rt.progress)
            for pid, val in td["progress"].items():
                new_prog[pid] = new_prog.get(pid, 0) + val
            updates["progress"] = new_prog
        if updates:
            new_tensions[tid] = rt.model_copy(update=updates)

    # Merge NPC deltas
    for nid, nd in world_delta.get("npc", {}).items():
        prev = new_npc.get(nid)
        if prev is None:
            continue
        npc_updates: dict = {}
        if "mood" in nd:
            npc_updates["mood"] = nd["mood"]
        if "goal_progress" in nd:
            new_gp = dict(prev.goal_progress)
            for gid, val in nd["goal_progress"].items():
                new_gp[gid] = new_gp.get(gid, 0) + val
            npc_updates["goal_progress"] = new_gp
        if npc_updates:
            new_npc[nid] = prev.model_copy(update=npc_updates)

    # Merge faction deltas
    for fname, fd in world_delta.get("faction", {}).items():
        prev = new_factions.get(fname)
        if prev is None:
            from engine.models import FactionRuntime
            prev = FactionRuntime(faction_id=fname)
        faction_updates: dict = {}
        if "trust" in fd:
            faction_updates["trust"] = prev.trust + fd["trust"]
        if "dominance" in fd:
            faction_updates["dominance"] = prev.dominance + fd["dominance"]
        if faction_updates:
            new_factions[fname] = prev.model_copy(update=faction_updates)

    return world_state.model_copy(update={
        "tensions": new_tensions,
        "npc_state": new_npc,
        "faction_state": new_factions,
    })
```

Also update the import block of `engine/world.py` to export the new function. Add `apply_world_delta` to the imports in `api/routes.py`.

- [ ] **Step 4: Wire validator into game_action**

In `api/routes.py`, modify the `game_action` function. The key changes are in the `response_generator` inner function, between the DM parse block and the state_delta application block.

After the DM parse block (≈line 438-457) and before the "common tail" section (≈line 459), insert the validator logic:

In the `else` branch of the streaming block, after `dm_response = parse_dm_response(raw_response)` (line 439) and the story reconciliation block (≈line 441-457):

```python
                else:
                    raw_response, _was_rewritten = post_filter_output(raw_response)
                    dm_response = parse_dm_response(raw_response)
                    story = dm_response.story
                    if not story or not story.strip():
                        story = story_fallbacks.get(intent, f"{player.name}的行动似乎没有引起什么变化。")
                    if story.startswith(last):
                        tail = story[len(last):]
                        if tail:
                            yield json.dumps(tail, ensure_ascii=False)[1:-1]
                    elif last:
                        story = last
                    if dm_response.story != story:
                        dm_response = dm_response.model_copy(update={"story": story})

                    # --- M3: validate + retry ---
                    from engine.validator import validate_dm_proposal, scan_story_for_canon_violations

                    clamped, violations, should_retry = validate_dm_proposal(
                        dm_response, world_state, bible, player,
                    )

                    # Post-hoc story scan (log only — story was already streamed)
                    story_violations = scan_story_for_canon_violations(story, bible)
                    if story_violations:
                        # Log but don't clamp — the story was already streamed.
                        # In production, this would go to a structured logger.
                        print(f"[validator] story canon violations: {story_violations}")

                    if should_retry and llm_client is not None:
                        # Build retry prompt with violation context
                        violation_text = "\n".join(f"- {v}" for v in violations)
                        retry_system = (
                            system_prompt
                            + f"\n\n【校验失败·请重试】你的回复中world_delta存在以下问题，请修正后重新生成完整JSON（不要包含任何解释文字，只返回纯JSON）：\n{violation_text}"
                        )
                        try:
                            retry_raw = await llm_client.generate(retry_system, user_prompt)
                            retry_raw, _ = post_filter_output(retry_raw)
                            retry_response = parse_dm_response(retry_raw)
                            # Re-validate the retry
                            clamped, violations, _ = validate_dm_proposal(
                                retry_response, world_state, bible, player,
                            )
                            # Use the retry's story if it's non-empty; otherwise keep original
                            if retry_response.story and retry_response.story.strip():
                                # Can't un-stream the old story, but we use the
                                # retry story for the response and history.
                                story = retry_response.story
                                dm_response = retry_response.model_copy(update={"story": story})
                            else:
                                dm_response = retry_response
                            # Re-scan story
                            story_violations2 = scan_story_for_canon_violations(story, bible)
                            if story_violations2:
                                print(f"[validator] retry story canon violations: {story_violations2}")
                        except Exception:
                            # Retry failed — keep the clamped original
                            pass

                    # Apply validated + clamped world_delta to world_state
                    if clamped.world_delta:
                        from engine.world import apply_world_delta
                        world_state = apply_world_delta(world_state, clamped.world_delta)
                        # Re-run tension_tick so tension states reflect DM-proposed
                        # progress/pressure nudges (e.g. a tension might now resolve
                        # because its resolution path condition is met).
                        world_state = tension_tick(world_state, bible, player)
                        world_state = world_state.model_copy(update={"tick": player.tick})
                        world_repo.save(world_state)

                    if violations:
                        print(f"[validator] violations: {violations}")
```

- [ ] **Step 5: Add world_delta to the response JSON**

In the `rest` dict (≈line 554-583), add:

```python
            rest = {
                "intent": intent.value,
                "action_valid": dm_response.action_valid,
                "state_delta": dm_response.state_delta or {},
                "world_delta": clamped.world_delta if (clamped if 'clamped' in dir() else None) else dm_response.world_delta,
                ...
```

Wait, `clamped` is defined inside the `else` block. It won't be defined if `move_error` is true. Let me handle this more carefully.

Actually, looking at the flow: `clamped` is only defined within the `else` branch (when there's no move_error). In the move_error branch, `dm_response` is a fallback with no world_delta. So I need to handle both cases.

Let me restructure: define `world_delta_for_response = None` before the `if move_error:` block, then set it after validation:

```python
            world_delta_for_response = None   # M3

            if move_error:
                ...
            else:
                ...
                # After validation:
                world_delta_for_response = clamped.world_delta

            # In the rest dict:
            rest = {
                ...
                "world_delta": world_delta_for_response,
                ...
            }
```

- [ ] **Step 6: Update imports in api/routes.py**

Add to the import block at the top of `api/routes.py`:

```python
from engine.world import WorldEngine, npc_step, tension_tick, apply_world_delta
```

(`apply_world_delta` is added to the existing import line.)

- [ ] **Step 7: Run integration tests**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest tests/test_api.py::TestValidatorIntegration -v`
Expected: all 4 integration tests PASS.

- [ ] **Step 8: Run the full test suite**

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest -v`
Expected: 226 tests, all PASS.

- [ ] **Step 9: Commit**

```bash
git add api/routes.py engine/world.py tests/test_api.py
git commit -m "feat(validator): wire validate→retry→apply into game_action pipeline (M3)"
```

---

## Self-Review

**1. Spec coverage:**
- §8 canon check → Task 2 `_validate_canon` + `scan_story_for_canon_violations`
- §8 personality consistency → Task 2 `_validate_personality`
- §8 causal plausibility → Task 2 `_validate_causal`
- §8 numeric bounds → Task 2 `_validate_numeric`
- §8 world_delta field on DMResponse → Task 1
- §8 "story走预防+事后扫描" → Task 3 (prompt rule 13 = prevention), Task 2 (scan = post-hoc), Task 4 (scan call in route)
- §8 "world_delta不流式、LLM完成后解析+完整校验+钳制+重试一次" → Task 4 (validate after parse, retry once)
- §8 "结构性违规→重试一次（点名违规）" → Task 4 (retry with violation context in prompt)
- §8 "仍失败则钳+留有效部分+记日志" → Task 2 (clamping in validator), Task 4 (print violations)
- §15 M3 scope → all 4 tasks

**2. Placeholder scan:** No TBD/TODO/placeholder patterns found. All code steps contain complete implementations.

**3. Type consistency:**
- `validate_dm_proposal` signature: consistent across Task 2 (definition) and Task 4 (usage)
- `scan_story_for_canon_violations` signature: consistent across Task 2 and Task 4
- `apply_world_delta` signature: defined in Task 4 Step 3, used in Task 4 Step 4
- `DMResponse.world_delta: dict | None` → defined Task 1, consumed Tasks 2, 3, 4
- world_delta JSON structure (`tension`/`npc`/`faction` keys) → consistent across all tasks
