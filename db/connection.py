import sqlite3


def init_db(conn: sqlite3.Connection):
    """Create tables if they don't exist."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT '练气期一层',
            spirit_power INTEGER NOT NULL DEFAULT 10,
            hp INTEGER NOT NULL DEFAULT 100,
            max_hp INTEGER NOT NULL DEFAULT 100,
            affinity TEXT NOT NULL DEFAULT '火',
            location TEXT NOT NULL DEFAULT '青云门外门柴房',
            inventory TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS npc_profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            persona TEXT NOT NULL,
            secret TEXT NOT NULL DEFAULT '',
            motive TEXT NOT NULL DEFAULT '',
            favorability INTEGER NOT NULL DEFAULT 50,
            relationship_stage TEXT NOT NULL DEFAULT '陌生'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS npc_memories (
            npc_id TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            recent_turns TEXT NOT NULL DEFAULT '[]',
            key_facts TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY (npc_id) REFERENCES npc_profiles(id),
            PRIMARY KEY (npc_id)
        )
    """)

    conn.commit()


def get_db(db_path: str = "llmud.db") -> sqlite3.Connection:
    """Get a database connection, creating the DB file if needed."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn