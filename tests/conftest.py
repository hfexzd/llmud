import os
import sqlite3
import pytest
from unittest.mock import AsyncMock

# Ensure test environment uses a temporary DB
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")


@pytest.fixture
def db_conn(tmp_path):
    """Provide a fresh in-memory SQLite connection for each test."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from db.connection import init_db
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def mock_llm_client():
    """Provide a mock LLM client that returns preset JSON."""
    client = AsyncMock()
    return client