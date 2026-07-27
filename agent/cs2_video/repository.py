import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS match_queries (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, player_id TEXT NOT NULL,
                    status TEXT NOT NULL, matches_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, query_id TEXT NOT NULL,
                    match_id TEXT NOT NULL, player_id TEXT NOT NULL, status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0, error TEXT,
                    events_json TEXT NOT NULL DEFAULT '[]', selection_json TEXT,
                    output_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner, created_at DESC);
            """)

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        for key in ("matches_json", "events_json", "selection_json", "output_json"):
            if key in result:
                value = result.pop(key)
                result[key[:-5]] = json.loads(value) if value else None
        return result

    def create_query(self, query_id, owner, player_id):
        now = utcnow()
        with self._lock, self._db:
            self._db.execute("INSERT INTO match_queries VALUES (?,?,?,?,?,?,?,?)",
                             (query_id, owner, player_id, "querying", "[]", None, now, now))
        return self.get_query(query_id)

    def finish_query(self, query_id, matches=None, error=None):
        with self._lock, self._db:
            self._db.execute("UPDATE match_queries SET status=?,matches_json=?,error=?,updated_at=? WHERE id=?",
                             ("failed" if error else "completed", json.dumps(matches or [], ensure_ascii=False), error, utcnow(), query_id))

    def update_query(self, query_id, *, status, matches, error=None):
        """Persist incremental match enrichment without exposing raw platform data."""
        with self._lock, self._db:
            self._db.execute(
                "UPDATE match_queries SET status=?,matches_json=?,error=?,updated_at=? WHERE id=?",
                (status, json.dumps(matches or [], ensure_ascii=False), error, utcnow(), query_id),
            )

    def get_query(self, query_id):
        with self._lock:
            return self._decode(self._db.execute("SELECT * FROM match_queries WHERE id=?", (query_id,)).fetchone())

    def active_count(self, owner):
        terminal = ("completed", "cancelled", "failed", "sending_unknown")
        q = "SELECT COUNT(*) FROM jobs WHERE owner=? AND status NOT IN (?,?,?,?)"
        with self._lock:
            return self._db.execute(q, (owner, *terminal)).fetchone()[0]

    def create_job(self, job_id, owner, query_id, match_id, player_id):
        now = utcnow()
        with self._lock, self._db:
            self._db.execute("INSERT INTO jobs(id,owner,query_id,match_id,player_id,status,progress,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                             (job_id, owner, query_id, match_id, player_id, "downloading", 5, now, now))
        return self.get_job(job_id)

    def update_job(self, job_id, **values):
        allowed = {"status", "progress", "error", "events", "selection", "output"}
        fields, args = [], []
        for key, value in values.items():
            if key not in allowed:
                continue
            column = key + "_json" if key in {"events", "selection", "output"} else key
            fields.append(column + "=?")
            args.append(json.dumps(value, ensure_ascii=False) if column.endswith("_json") else value)
        fields.append("updated_at=?"); args.append(utcnow()); args.append(job_id)
        with self._lock, self._db:
            self._db.execute(f"UPDATE jobs SET {','.join(fields)} WHERE id=?", args)
        return self.get_job(job_id)

    def get_job(self, job_id):
        with self._lock:
            return self._decode(self._db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def delete_job(self, job_id):
        with self._lock, self._db:
            self._db.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    def delete_cancelled_jobs(self, owner=None):
        with self._lock, self._db:
            if owner:
                self._db.execute("DELETE FROM jobs WHERE owner=? AND status='cancelled'", (owner,))
            else:
                self._db.execute("DELETE FROM jobs WHERE status='cancelled'")

    def list_jobs(self, owner=None):
        with self._lock:
            if owner:
                rows = self._db.execute("SELECT * FROM jobs WHERE owner=? ORDER BY created_at DESC LIMIT 100", (owner,)).fetchall()
            else:
                rows = self._db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100").fetchall()
        return [self._decode(row) for row in rows]
