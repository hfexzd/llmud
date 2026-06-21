# M6 挂机离线成长 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the world keep running while the player is away. Rule-driven tick advance (no LLM) with budget caps, no breakthrough, no ending trigger. Catch-up card on return.

**Architecture:** `engine/offline.py::advance_offline(player, world_state, now, directive)` pure function. Calculates offline tick budget from `last_seen` to `now` with a max cap. Runs `npc_step` + `tension_tick` for each tick (no DM/LLM). Updates player spirit power based on directive (闭关/历练/静养). Returns catch-up summary. Player gets `offline_directive` field. Frontend: strategy selector + offline card.

**Tech Stack:** Python 3.14, Pydantic v2, FastAPI, SQLite, pytest.

---

## File Structure

- **`engine/offline.py`** (NEW) — `advance_offline()`, catch-up summary builder
- **`engine/models.py`** — add `offline_directive` to `Player`
- **`api/routes.py`** — wire offline catch-up on player load
- **`static/index.html`** — offline directive selector + offline card
- **`tests/test_offline.py`** (NEW) — unit tests
- **`tests/test_api.py`** — integration test

---

### Task 1: Player model — offline_directive field

Add to `Player` model:

```python
offline_directive: str = "闭关"  # 闭关 | 历练 | 静养
```

And a helper dict in `engine/offline.py` for directive rates.

**Step 1: Add field to Player**

In `engine/models.py`, add `offline_directive` to the `Player` class.

**Step 2: Verify it compiles**

```bash
python -c "from engine.models import Player; p=Player(); print(p.offline_directive)"
```

**Step 3: Commit**

---

### Task 2: advance_offline — pure function

**Files:**
- Create: `engine/offline.py`
- Test: `tests/test_offline.py`

**Interfaces:**
- `advance_offline(player, world_state, bible, now: datetime, directive: str) -> (Player, WorldState, str)` — returns (updated_player, updated_world_state, catchup_text)
- `compute_offline_budget(last_seen: datetime, now: datetime, rate: float = 1.0) -> int` — returns capped tick count
- Directive rates: 闭关=1.5x spirit gain, 历练=1.0x spirit + tension progress, 静养=0.5x spirit + hp recovery

**Step 1: Write failing tests**

```python
"""Tests for M6 offline growth."""
from datetime import datetime, timedelta
from engine.models import Player, WorldState, PHASE_0_BIBLE
from engine.offline import advance_offline, compute_offline_budget, OFFLINE_MAX_BUDGET, DIRECTIVE_RATES


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


def test_advance_offline_preserves_player_identity():
    """Player id and name remain unchanged after offline advance."""
    p = Player(id="p1", name="张铁柱", tick=10)
    ws = WorldState(tick=10)
    new_p, new_ws, summary = advance_offline(p, ws, PHASE_0_BIBLE, directive="闭关")
    assert new_p.id == "p1"
    assert new_p.name == "张铁柱"


def test_advance_offline_increases_tick():
    p = Player(tick=10)
    ws = WorldState(tick=10)
    new_p, new_ws, _ = advance_offline(p, ws, PHASE_0_BIBLE, directive="闭关")
    assert new_p.tick > 10
    assert new_ws.tick > 10


def test_advance_offline_cultivate_directive_increases_spirit():
    """闭关 should give more spirit power per tick."""
    p = Player(tick=10, spirit_power=10)
    ws = WorldState(tick=10)
    new_p, _, _ = advance_offline(p, ws, PHASE_0_BIBLE, directive="闭关")
    assert new_p.spirit_power > 10


def test_advance_offline_does_not_trigger_ending():
    """Offline advance should not seal the world."""
    p = Player(tick=10)
    ws = WorldState(tick=10)
    _, new_ws, _ = advance_offline(p, ws, PHASE_0_BIBLE, directive="闭关")
    assert new_ws.sealed is False


def test_advance_offline_does_not_breakthrough():
    """Offline advance should not change player level."""
    p = Player(tick=10, level="练气期一层", spirit_power=50)
    ws = WorldState(tick=10)
    new_p, _, _ = advance_offline(p, ws, PHASE_0_BIBLE, directive="闭关")
    assert new_p.level == "练气期一层"


def test_advance_offline_returns_summary():
    p = Player(tick=10)
    ws = WorldState(tick=10)
    _, _, summary = advance_offline(p, ws, PHASE_0_BIBLE, directive="闭关")
    assert len(summary) > 0
    assert "灵力" in summary or "闭关" in summary
```

**Step 2: Implement advance_offline**

```python
"""Offline growth (M6). Rule-driven tick advance — no LLM, no breakthrough, no ending."""

from __future__ import annotations
from datetime import datetime
from engine.models import Player, WorldState, WorldBible
from engine.world import npc_step, tension_tick


# Max offline budget in ticks (~8h at 1 tick/min)
OFFLINE_MAX_BUDGET = 480

# 1 tick = 1 minute in real time
TICK_DURATION_MINUTES = 1

DIRECTIVE_RATES = {
    "闭关": {"spirit_per_tick": 2, "hp_per_tick": 0, "tension_progress": False},
    "历练": {"spirit_per_tick": 1, "hp_per_tick": 0, "tension_progress": True},
    "静养": {"spirit_per_tick": 0, "hp_per_tick": 2, "tension_progress": False},
}


def compute_offline_budget(
    last_seen: datetime, now: datetime, rate: float = 1.0
) -> int:
    """Compute how many ticks the player was offline, capped at OFFLINE_MAX_BUDGET."""
    seconds_offline = (now - last_seen).total_seconds()
    ticks = int(seconds_offline / (TICK_DURATION_MINUTES * 60) * rate)
    return min(ticks, OFFLINE_MAX_BUDGET)


def advance_offline(
    player: Player,
    world_state: WorldState,
    bible: WorldBible,
    now: datetime | None = None,
    directive: str = "闭关",
) -> tuple[Player, WorldState, str]:
    """Advance the world forward while the player is offline.

    Pure function. Runs rule-driven npc_step + tension_tick for each offline
    tick. Updates player spirit power / HP based on directive. Does NOT call
    LLM, does NOT trigger breakthrough, does NOT trigger endings.

    Returns (updated_player, updated_world_state, catchup_summary).
    """
    if now is None:
        now = datetime.now()

    budget = compute_offline_budget(player.last_seen, now)
    if budget <= 0:
        return player, world_state, "你刚刚离开，世界还没来得及变化。"

    rates = DIRECTIVE_RATES.get(directive, DIRECTIVE_RATES["闭关"])

    new_p = player
    new_ws = world_state
    spirit_gained = 0
    hp_gained = 0
    tensions_resolved: list[str] = []

    for _ in range(budget):
        new_p = new_p.model_copy(update={"tick": new_p.tick + 1})
        new_ws = new_ws.model_copy(update={"tick": new_ws.tick})

        # Rule-driven world simulation
        new_ws = npc_step(new_ws, bible, new_p.tick)
        new_ws = tension_tick(new_ws, bible, new_p)

        # Apply directive effects
        updates = {}
        if rates["spirit_per_tick"] > 0:
            updates["spirit_power"] = new_p.spirit_power + rates["spirit_per_tick"]
            spirit_gained += rates["spirit_per_tick"]
        if rates["hp_per_tick"] > 0:
            new_hp = min(new_p.max_hp, new_p.hp + rates["hp_per_tick"])
            updates["hp"] = new_hp
            hp_gained += new_hp - new_p.hp
        if updates:
            new_p = new_p.model_copy(update=updates)

    # Build catch-up summary
    summary_parts: list[str] = []
    if spirit_gained > 0:
        summary_parts.append(f"灵力+{spirit_gained}")
    if hp_gained > 0:
        summary_parts.append(f"气血+{hp_gained}")
    summary_parts.append(f"已过{budget}回合")
    summary = f"【离线归来】{directive}期间，{'，'.join(summary_parts)}。"

    return new_p, new_ws, summary
```

**Step 3: Run tests, verify pass**

**Step 4: Commit**

---

### Task 3: Wire offline catch-up into API

**Files:**
- Modify: `api/routes.py` — on player load, if offline, call advance_offline, persist, build response

**Step 1: Wire into player load**

In `api/routes.py`, in `game_action`, after loading the player and before the pipeline:

```python
# M6: offline catch-up
from datetime import datetime, timezone
from engine.offline import advance_offline
now = datetime.now(timezone.utc)
if player.last_seen.tzinfo is None:
    last_seen = player.last_seen.replace(tzinfo=timezone.utc)
else:
    last_seen = player.last_seen
seconds_offline = (now - last_seen).total_seconds()
if seconds_offline > 60:  # more than 1 minute offline
    player, world_state, offline_summary = advance_offline(
        player, world_state, bible, now=now, directive=player.offline_directive,
    )
    # Persist
    player_repo.update(player)
    world_repo.save(world_state)
    # Surface in response
    offline_summary_for_response = offline_summary
```

**Step 2: Add integration test**

```python
@pytest.mark.asyncio
async def test_offline_catchup_advances_state(db_conn, mock_llm_client):
    """Loading an offline player advances world state."""
    from datetime import datetime, timedelta
    from engine.offline import OFFLINE_MAX_BUDGET

    mock_llm_client.generate_stream = None
    mock_llm_client.generate.return_value = (
        '{"intent":"cultivate","story":"你回到修炼中。","action_valid":true}'
    )

    player_repo = PlayerRepository(db_conn)
    npc_repo = NPCRepository(db_conn)
    world_repo = WorldRepository(db_conn)
    engine = WorldEngine()

    # Player was last seen 2 hours ago
    last_seen = datetime.now() - timedelta(hours=2)
    player_repo.save(Player(
        id="p1", current_scene="outer_gate", tick=10,
        last_seen=last_seen,
    ))

    router = create_router(mock_llm_client, player_repo, npc_repo,
                           DEFAULT_ENCOUNTER, engine, world_repo)
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/game/action", json={"user_input": "修炼"})
        assert response.status_code == 200
        data = response.json()
        # Player tick should have advanced beyond 10
        assert data["player"]["tick"] > 10
```

**Step 3: Run tests, verify pass**

**Step 4: Commit**

---

### Task 4: Frontend — offline directive selector

**File:**
- Modify: `static/index.html`

Add a directive selector dropdown or toggle in the status bar area.

**Step 1: Add directive selector UI + JS**

In `static/index.html`, add to the status bar:

```html
<select id="offline-directive" style="background:rgba(255,255,255,0.1);color:#fff;border:1px solid #6b3fa0;border-radius:8px;padding:2px 8px;font-size:11px;">
    <option value="闭关">闭关</option>
    <option value="历练">历练</option>
    <option value="静养">静养</option>
</select>
```

Add in the `sendAction()` response handler:

```javascript
// Show offline catch-up card if present
if (result.offline_summary) {
    const card = document.createElement('div');
    card.className = 'world-event';
    card.textContent = result.offline_summary;
    container.insertBefore(card, container.firstChild);
}
```

Add the `offline_directive` field to the action request:

```javascript
async function sendAction() {
    const input = document.getElementById('user-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    const directive = document.getElementById('offline-directive')?.value || '闭关';
    // ... existing code ...
    const body = { user_input: text, offline_directive: directive };
    // ... rest of request ...
}
```

**Step 2: Commit**

---

## Self-Review

- Pure function: `advance_offline` takes state in, returns state out (no side effects)
- Safety: no LLM calls, no breakthrough, no ending trigger
- Budget cap: `OFFLINE_MAX_BUDGET = 480` (8h at 1 tick/min)
- Directive rates balanced for phase-0 values (spirit caps at 100)
- No combat simulation offline (tensions progress but don't resolve via combat)
