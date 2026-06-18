import sqlite3
from engine.models import Player
from db.repository import PlayerRepository
from db.connection import init_db


def _fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_save_and_get_player():
    conn = _fresh_db()
    repo = PlayerRepository(conn)
    player = Player(id="p1", name="张铁柱", level="练气期一层", spirit_power=10,
                    hp=100, max_hp=100, affinity="火", current_scene="outer_gate", inventory=[])
    repo.save(player)
    fetched = repo.get("p1")
    assert fetched is not None
    assert fetched.name == "张铁柱"
    assert fetched.spirit_power == 10
    assert fetched.level == "练气期一层"


def test_update_player():
    conn = _fresh_db()
    repo = PlayerRepository(conn)
    player = Player(id="p1", name="张铁柱", level="练气期一层", spirit_power=10,
                    hp=100, max_hp=100, affinity="火", current_scene="outer_gate", inventory=[])
    repo.save(player)
    updated = player.model_copy(update={"spirit_power": 25, "level": "练气期二层"})
    repo.update(updated)
    fetched = repo.get("p1")
    assert fetched.spirit_power == 25
    assert fetched.level == "练气期二层"


def test_get_nonexistent_player():
    conn = _fresh_db()
    repo = PlayerRepository(conn)
    result = repo.get("nonexistent")
    assert result is None


def test_save_and_get_player_with_living_world_fields():
    conn = _fresh_db()
    repo = PlayerRepository(conn)
    player = Player(
        id="p2", name="李逍遥", level="练气期二层", spirit_power=35,
        hp=90, max_hp=100, affinity="水", current_scene="inner_gate",
        inventory=["灵石"], seen_events=["faint_spirit_sense", "waner_worry"],
        tick=7,
    )
    repo.save(player)
    fetched = repo.get("p2")
    assert fetched is not None
    assert fetched.current_scene == "inner_gate"
    assert fetched.seen_events == ["faint_spirit_sense", "waner_worry"]
    assert fetched.tick == 7


def test_update_player_living_world_fields():
    conn = _fresh_db()
    repo = PlayerRepository(conn)
    player = Player(id="p3", name="王大锤", current_scene="outer_gate", seen_events=[], tick=0)
    repo.save(player)

    updated = player.model_copy(update={
        "current_scene": "market",
        "seen_events": ["market_rumor"],
        "tick": 5,
    })
    repo.update(updated)

    fetched = repo.get("p3")
    assert fetched.current_scene == "market"
    assert fetched.seen_events == ["market_rumor"]
    assert fetched.tick == 5