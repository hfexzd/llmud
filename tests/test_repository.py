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
                    hp=100, max_hp=100, affinity="火", location="青云门外门柴房", inventory=[])
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
                    hp=100, max_hp=100, affinity="火", location="青云门外门柴房", inventory=[])
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