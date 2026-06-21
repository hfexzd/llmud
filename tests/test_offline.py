"""Tests for M6 offline growth."""
from datetime import datetime, timedelta, timezone
from engine.models import Player, WorldState, PHASE_0_BIBLE
from engine.offline import advance_offline, compute_offline_budget, OFFLINE_MAX_BUDGET


def test_compute_offline_budget_basic():
    """1 hour offline at 1x rate = 60 ticks."""
    now = datetime(2026, 6, 22, 12, 0, 0)
    last = datetime(2026, 6, 22, 11, 0, 0)
    budget = compute_offline_budget(last, now, rate=1.0)
    assert budget == 60


def test_compute_offline_budget_capped():
    """100 hours offline should be capped."""
    now = datetime(2026, 6, 26, 12, 0, 0)
    last = datetime(2026, 6, 22, 11, 0, 0)
    budget = compute_offline_budget(last, now, rate=1.0)
    assert budget <= OFFLINE_MAX_BUDGET


_NOW = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
_ONE_HOUR_AGO = datetime(2026, 6, 22, 11, 0, 0, tzinfo=timezone.utc)


def _past_player(**kwargs) -> Player:
    """Player with last_seen set to 1 hour ago."""
    return Player(last_seen=_ONE_HOUR_AGO, **kwargs)


def test_advance_offline_preserves_player_identity():
    """Player id and name remain unchanged after offline advance."""
    p = _past_player(id="p1", name="张铁柱", tick=10)
    ws = WorldState(tick=10)
    new_p, new_ws, summary = advance_offline(p, ws, PHASE_0_BIBLE, now=_NOW, directive="闭关")
    assert new_p.id == "p1"
    assert new_p.name == "张铁柱"


def test_advance_offline_increases_tick():
    p = _past_player(tick=10)
    ws = WorldState(tick=10)
    new_p, new_ws, _ = advance_offline(p, ws, PHASE_0_BIBLE, now=_NOW, directive="闭关")
    assert new_p.tick > 10
    assert new_ws.tick > 10


def test_advance_offline_cultivate_directive_increases_spirit():
    """闭关 should give more spirit power per tick."""
    p = _past_player(tick=10, spirit_power=10)
    ws = WorldState(tick=10)
    new_p, _, _ = advance_offline(p, ws, PHASE_0_BIBLE, now=_NOW, directive="闭关")
    assert new_p.spirit_power > 10


def test_advance_offline_does_not_trigger_ending():
    """Offline advance should not seal the world."""
    p = _past_player(tick=10)
    ws = WorldState(tick=10)
    _, new_ws, _ = advance_offline(p, ws, PHASE_0_BIBLE, now=_NOW, directive="闭关")
    assert new_ws.sealed is False


def test_advance_offline_does_not_breakthrough():
    """Offline advance should not change player level."""
    p = _past_player(tick=10, level="练气期一层", spirit_power=50)
    ws = WorldState(tick=10)
    new_p, _, _ = advance_offline(p, ws, PHASE_0_BIBLE, now=_NOW, directive="闭关")
    assert new_p.level == "练气期一层"


def test_advance_offline_returns_summary():
    p = _past_player(tick=10)
    ws = WorldState(tick=10)
    _, _, summary = advance_offline(p, ws, PHASE_0_BIBLE, now=_NOW, directive="闭关")
    assert len(summary) > 0
    assert "灵力" in summary or "闭关" in summary
