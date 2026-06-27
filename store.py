"""
store.py
--------
SQLite persistence so the feedback loop survives across runs.

Each recommendation is written with the exact context vector that produced it,
so when the real-world result arrives we can feed it straight back into the
learner. Writes are idempotent (upsert on week+topic / on rec_id) so refreshing
the dashboard never inflates the log.
"""
import json
import sqlite3
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week INTEGER, topic TEXT, category TEXT, kind TEXT,
    roi REAL, value_mean REAL, uncertainty REAL, effort TEXT,
    rationale TEXT, context TEXT, created_at REAL,
    UNIQUE(week, topic)
);
CREATE TABLE IF NOT EXISTS outcomes (
    rec_id INTEGER PRIMARY KEY, reward REAL, recorded_at REAL,
    FOREIGN KEY(rec_id) REFERENCES recommendations(id)
);
"""


def connect(path: str = "mie.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    return conn


def save_recommendation(conn, week, topic, category, kind, roi, value_mean,
                        uncertainty, effort, rationale, context_json=None) -> int:
    """Insert a recommendation, or update it in place if (week, topic) exists."""
    row = conn.execute(
        "SELECT id FROM recommendations WHERE week=? AND topic=?",
        (week, topic)).fetchone()
    if row:
        rid = row[0]
        conn.execute(
            """UPDATE recommendations
               SET roi=?, value_mean=?, uncertainty=?, effort=?, rationale=?,
                   context=COALESCE(?, context)
               WHERE id=?""",
            (roi, value_mean, uncertainty, effort, rationale, context_json, rid))
        conn.commit()
        return rid
    cur = conn.execute(
        """INSERT INTO recommendations
           (week, topic, category, kind, roi, value_mean, uncertainty,
            effort, rationale, context, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (week, topic, category, kind, roi, value_mean, uncertainty,
         effort, rationale, context_json, time.time()))
    conn.commit()
    return cur.lastrowid


def get_context(conn, rec_id: int):
    """Return the stored context vector for a recommendation, or None."""
    row = conn.execute(
        "SELECT context FROM recommendations WHERE id=?", (rec_id,)).fetchone()
    if not row or row[0] is None:
        return None
    return json.loads(row[0])


def record_outcome(conn, rec_id: int, reward: float) -> None:
    """Store (or replace) the realised reward for a recommendation."""
    exists = conn.execute(
        "SELECT 1 FROM outcomes WHERE rec_id=?", (rec_id,)).fetchone()
    if exists:
        conn.execute("UPDATE outcomes SET reward=?, recorded_at=? WHERE rec_id=?",
                     (reward, time.time(), rec_id))
    else:
        conn.execute("INSERT INTO outcomes (rec_id, reward, recorded_at) VALUES (?,?,?)",
                     (rec_id, reward, time.time()))
    conn.commit()


def summary(conn) -> dict:
    n_rec = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
    n_out = conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
    avg = conn.execute("SELECT AVG(reward) FROM outcomes").fetchone()[0]
    return {"recommendations": n_rec, "outcomes": n_out,
            "avg_reward": round(avg, 4) if avg is not None else None}
