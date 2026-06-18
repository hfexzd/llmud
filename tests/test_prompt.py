"""Invariants for the DM prompt and the objective-layer guidance text."""
from dm.prompt import build_dm_prompt
from engine.models import Player, Intent, GOALS


def test_dm_prompt_forbids_engine_only_breakthrough():
    """The DM must not narrate a breakthrough the engine did not grant — that
    breaks the bones/skin contract (the engine is the sole source of truth for
   境界). Regression: the DM used to narrate '练气期二层，成了' while the
    engine still had the player at 练气期一层."""
    system_prompt, _ = build_dm_prompt(Player(), Intent.CULTIVATE)
    assert "突破由引擎决定" in system_prompt
    # The level placeholder must be filled, never leaked as a literal.
    assert "{level}" not in system_prompt


def test_dm_prompt_only_narrates_breakthrough_when_engine_reports_it():
    """Without an engine breakthrough, the prompt carries no engine 【突破】
    event marker, so rule 11 leaves the DM nothing to hang a breakthrough
    narration on. (Rule 11's own text mentions 【突破】 — we check the engine's
    event marker 【突破】玩家从, which only appears when breakthrough is set.)"""
    system_prompt, _ = build_dm_prompt(Player(), Intent.CULTIVATE)
    assert "【突破】玩家从" not in system_prompt


def test_cultivate_breakthrough_guidance_forbids_narrating_breakthrough():
    """The 所务 guidance must steer toward the goal without inviting the DM to
    fabricate the breakthrough itself."""
    goal = next(g for g in GOALS if g.id == "cultivate_breakthrough")
    assert "绝不可" in goal.guidance or "不得" in goal.guidance
    assert "引擎结算决定" in goal.guidance