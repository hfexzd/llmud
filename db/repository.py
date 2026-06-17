import json
import sqlite3
from datetime import datetime
from engine.models import Player


class PlayerRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, player_id: str) -> Player | None:
        row = self.conn.execute(
            "SELECT * FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if row is None:
            return None
        return Player(
            id=row["id"],
            name=row["name"],
            level=row["level"],
            spirit_power=row["spirit_power"],
            hp=row["hp"],
            max_hp=row["max_hp"],
            affinity=row["affinity"],
            location=row["location"],
            inventory=json.loads(row["inventory"]),
            recent_stories=json.loads(row["recent_stories"]) if "recent_stories" in row.keys() else [],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
        )

    def save(self, player: Player) -> None:
        self.conn.execute(
            """INSERT INTO players (id, name, level, spirit_power, hp, max_hp, affinity, location, inventory, recent_stories, created_at, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (player.id, player.name, player.level, player.spirit_power,
             player.hp, player.max_hp, player.affinity, player.location,
             json.dumps(player.inventory), json.dumps(player.recent_stories, ensure_ascii=False),
             player.created_at.isoformat(), player.last_seen.isoformat()),
        )
        self.conn.commit()

    def update(self, player: Player) -> None:
        self.conn.execute(
            """UPDATE players SET name=?, level=?, spirit_power=?, hp=?, max_hp=?,
               affinity=?, location=?, inventory=?, recent_stories=?, last_seen=? WHERE id=?""",
            (player.name, player.level, player.spirit_power, player.hp,
             player.max_hp, player.affinity, player.location,
             json.dumps(player.inventory), json.dumps(player.recent_stories, ensure_ascii=False),
             datetime.now().isoformat(), player.id),
        )
        self.conn.commit()


class NPCRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_profile(self, npc_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM npc_profiles WHERE id = ?", (npc_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_memory(self, npc_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM npc_memories WHERE npc_id = ?", (npc_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def save_profile(self, npc_id: str, name: str, persona: str,
                     secret: str = "", motive: str = "",
                     favorability: int = 50, relationship_stage: str = "陌生") -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO npc_profiles (id, name, persona, secret, motive, favorability, relationship_stage)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (npc_id, name, persona, secret, motive, favorability, relationship_stage),
        )
        self.conn.commit()

    def save_memory(self, npc_id: str, summary: str = "",
                    recent_turns: list | None = None, key_facts: list | None = None) -> None:
        recent_turns = recent_turns or []
        key_facts = key_facts or []
        self.conn.execute(
            """INSERT OR REPLACE INTO npc_memories (npc_id, summary, recent_turns, key_facts)
               VALUES (?, ?, ?, ?)""",
            (npc_id, summary, json.dumps(recent_turns, ensure_ascii=False),
             json.dumps(key_facts, ensure_ascii=False)),
        )
        self.conn.commit()

    def update_memory(self, npc_id: str, summary: str = "",
                      recent_turns: list | None = None, key_facts: list | None = None) -> None:
        existing = self.get_memory(npc_id) or {}
        self.save_memory(
            npc_id,
            summary=summary or existing.get("summary", ""),
            recent_turns=recent_turns or json.loads(existing.get("recent_turns", "[]")),
            key_facts=key_facts or json.loads(existing.get("key_facts", "[]")),
        )

    def update_favorability(self, npc_id: str, new_value: int, new_stage: str) -> None:
        self.conn.execute(
            "UPDATE npc_profiles SET favorability=?, relationship_stage=? WHERE id=?",
            (new_value, new_stage, npc_id),
        )
        self.conn.commit()