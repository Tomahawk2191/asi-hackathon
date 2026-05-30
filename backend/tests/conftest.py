"""Shared pytest fixtures for the backend test suite.

This is the project's first test harness (none existed before the
airport_capacity feature). Tests run against a throwaway SQLite DB, never the
real ``backend/arrivals.db``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the flat backend modules (capacity, db, main, ...) importable when pytest
# is run from anywhere.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def db_path(tmp_path):
    """Path to a fresh, throwaway SQLite DB for one test."""
    return tmp_path / "test_arrivals.db"


@pytest.fixture
def client(db_path, monkeypatch):
    """A FastAPI TestClient whose endpoints hit the throwaway DB."""
    import main
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "DB_PATH", db_path)
    return TestClient(main.app)
