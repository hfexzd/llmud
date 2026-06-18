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

        # Backward compat: fall back to old 'location' column if
        # 'current_scene' is missing (pre-migration DBs)
        columns = set(row.keys())
        current_scene = row["current_scene"] if "current_scene" in columns else (
            row["location"] if "location" in columns else "outer_gate"
        )
        seen_events = json.loads(row["seen_events"]) if "seen_events" in columns else []
        tick = row["tick"] if "tick" in columns else 0
        visited_scenes = json.loads(row["visited_scenes"]) if "visited_scenes" in columns else []
        # Seed with the current scene so a migrated save (no visited_scenes
        # column yet) still reflects where the player actually is.
        if current_scene not in visited_scenes:
            visited_scenes.append(current_scene)
        active_enemy = None
        if "active_enemy" in columns and row["active_enemy"]:
            active_enemy = json.loads(row["active_enemy"])

        quests_data = json.loads(row["quests"]) if "quests" in columns and row["quests"] else []
        from engine.models import QuestState
        quests = [QuestState(**q) for q in quests_data]

        return Player(
            id=row["id"],
            name=row["name"],
            level=row["level"],
            spirit_power=row["spirit_power"],
            hp=row["hp"],
            max_hp=row["max_hp"],
            affinity=row["affinity"],
            current_scene=current_scene,
            inventory=json.loads(row["inventory"]),
            recent_stories=json.loads(row["recent_stories"]) if "recent_stories" in columns else [],
            seen_events=seen_events,
            visited_scenes=visited_scenes,
            active_enemy=active_enemy,
            quests=quests,
            tick=tick,
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
        )

    def save(self, player: Player) -> None:
        self.conn.execute(
            """INSERT INTO players (id, name, level, spirit_power, hp, max_hp, affinity,
               current_scene, inventory, recent_stories, seen_events, visited_scenes,
               active_enemy, tick, quests, created_at, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (player.id, player.name, player.level, player.spirit_power,
             player.hp, player.max_hp, player.affinity, player.current_scene,
             json.dumps(player.inventory), json.dumps(player.recent_stories, ensure_ascii=False),
             json.dumps(player.seen_events, ensure_ascii=False),
             json.dumps(player.visited_scenes, ensure_ascii=False),
             json.dumps(player.active_enemy, ensure_ascii=False) if player.active_enemy else None,
             player.tick,
             json.dumps([q.model_dump() for q in player.quests], ensure_ascii=False),
             player.created_at.isoformat(), player.last_seen.isoformat()),
        )
        self.conn.commit()

    def update(self, player: Player) -> None:
        self.conn.execute(
            """UPDATE players SET name=?, level=?, spirit_power=?, hp=?, max_hp=?,
               affinity=?, current_scene=?, inventory=?, recent_stories=?,
               seen_events=?, visited_scenes=?, active_enemy=?, tick=?, quests=?, last_seen=? WHERE id=?""",
            (player.name, player.level, player.spirit_power, player.hp,
             player.max_hp, player.affinity, player.current_scene,
             json.dumps(player.inventory), json.dumps(player.recent_stories, ensure_ascii=False),
             json.dumps(player.seen_events, ensure_ascii=False),
             json.dumps(player.visited_scenes, ensure_ascii=False),
             json.dumps(player.active_enemy, ensure_ascii=False) if player.active_enemy else None,
             player.tick,
             json.dumps([q.model_dump() for q in player.quests], ensure_ascii=False),
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
                     default_scene: str = "outer_gate",
                     favorability: int = 50, relationship_stage: str = "陌生") -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO npc_profiles (id, name, persona, secret, motive,
               default_scene, favorability, relationship_stage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (npc_id, name, persona, secret, motive, default_scene,
             favorability, relationship_stage),
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