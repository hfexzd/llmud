import sqlite3


def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str,
                         col_type: str, default: str) -> None:
    """Add a column to a table if it doesn't already exist.

    Uses PRAGMA table_info to check for the column first so that
    ALTER TABLE is only issued when the column is truly missing.
    """
    cursor = conn.cursor()
    col_info = cursor.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {row[1] for row in col_info}  # row[1] is column name
    if column not in existing:
        cursor.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default}"
        )
        conn.commit()


def init_db(conn: sqlite3.Connection):
    """Create tables if they don't exist, then run migrations."""
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
            current_scene TEXT NOT NULL DEFAULT 'outer_gate',
            inventory TEXT NOT NULL DEFAULT '[]',
            recent_stories TEXT NOT NULL DEFAULT '[]',
            seen_events TEXT NOT NULL DEFAULT '[]',
            tick INTEGER NOT NULL DEFAULT 0,
            quests TEXT NOT NULL DEFAULT '[]',
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
            default_scene TEXT NOT NULL DEFAULT 'outer_gate',
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS world_state (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)

    conn.commit()

    # Migrations for existing databases that lack the new columns
    _migrate_add_column(conn, "players", "current_scene", "TEXT", "'outer_gate'")
    _migrate_add_column(conn, "players", "seen_events", "TEXT", "'[]'")
    _migrate_add_column(conn, "players", "tick", "INTEGER", "0")
    _migrate_add_column(conn, "players", "visited_scenes", "TEXT", "'[]'")
    _migrate_add_column(conn, "players", "active_enemy", "TEXT", "NULL")
    _migrate_add_column(conn, "players", "quests", "TEXT", "'[]'")
    _migrate_add_column(conn, "npc_profiles", "default_scene", "TEXT", "'outer_gate'")


def get_db(db_path: str = "llmud.db") -> sqlite3.Connection:
    """Get a database connection, creating the DB file if needed."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn