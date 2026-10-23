import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "cases.db"


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cases ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, notes TEXT, created_at TEXT NOT NULL)"
    )
    return conn


def add_case(title: str, notes: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO cases (title, notes, created_at) VALUES (?, ?, ?)",
            (title, notes, datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def all_cases() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, title, notes, created_at FROM cases ORDER BY id DESC").fetchall()
    return [{"id": r[0], "title": r[1], "notes": r[2], "created_at": r[3]} for r in rows]
