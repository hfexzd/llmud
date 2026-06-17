"""Dependency injection helpers for FastAPI."""
import os
import sqlite3
from functools import lru_cache

from dotenv import load_dotenv

from dm.client import LLMClient, DeepSeekClient
from db.connection import init_db


load_dotenv()


@lru_cache
def get_llm_client() -> LLMClient:
    """Return a singleton LLMClient instance."""
    return DeepSeekClient()


def create_db_connection_from_env(db_path: str | None = None) -> sqlite3.Connection:
    """Create and return a new SQLite connection with initialized tables."""
    db_path = db_path or os.environ.get("LLMUD_DB_PATH", "llmud.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn