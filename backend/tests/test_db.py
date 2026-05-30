"""Round-trip tests for the airport_capacity storage helpers."""

from __future__ import annotations

import capacity
import db


def test_write_then_read_round_trips_the_aar(db_path):
    conn = db.connect(db_path)
    try:
        written = db.write_capacity(conn, capacity.capacity_rows())
        assert written == 3
        aar = {r["airport"]: r["aar"] for r in db.read_capacity(conn)}
        assert aar == {"KJFK": 52, "KLGA": 40, "KEWR": 52}
        assert all(r["source"] for r in db.read_capacity(conn))  # provenance stored
    finally:
        conn.close()


def test_reseeding_replaces_rather_than_duplicates(db_path):
    conn = db.connect(db_path)
    try:
        db.write_capacity(conn, capacity.capacity_rows())
        db.write_capacity(conn, capacity.capacity_rows())  # re-seed
        rows = db.read_capacity(conn)
        assert len(rows) == 3  # not 6 -- whole table replaced
    finally:
        conn.close()


def test_read_capacity_airport_filter(db_path):
    conn = db.connect(db_path)
    try:
        db.write_capacity(conn, capacity.capacity_rows())
        assert [r["airport"] for r in db.read_capacity(conn, ["KLGA"])] == ["KLGA"]
        assert db.read_capacity(conn, []) == []  # explicit empty filter -> empty
    finally:
        conn.close()
