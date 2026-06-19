"""
SQLite database tracker — stores every job found and tracks its lifecycle.

Status flow:
  found → matched → applying → applied → emailed → [interview | rejected | manual_required]
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id              TEXT PRIMARY KEY,
                title           TEXT NOT NULL,
                company         TEXT NOT NULL,
                location        TEXT,
                url             TEXT UNIQUE NOT NULL,
                description     TEXT,
                source          TEXT,
                posted_date     TEXT,
                match_score     REAL DEFAULT 0.0,
                status          TEXT DEFAULT 'found',
                applied_at      TEXT,
                emailed_at      TEXT,
                recruiter_email TEXT,
                cover_letter    TEXT,
                notes           TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_status  ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_source  ON jobs(source);
            CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);

            CREATE TABLE IF NOT EXISTS email_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT NOT NULL REFERENCES jobs(id),
                to_email    TEXT NOT NULL,
                subject     TEXT,
                sent_at     TEXT DEFAULT (datetime('now')),
                success     INTEGER DEFAULT 1,
                error_msg   TEXT
            );
        """)
    logger.info("Database initialised at %s", DB_PATH)


def job_exists(url: str) -> bool:
    """Return True if a job with this URL is already tracked."""
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM jobs WHERE url = ?", (url,)).fetchone()
        return row is not None


def upsert_job(job: dict) -> bool:
    """
    Insert a job or update if URL already exists.
    Returns True if the job was newly inserted.
    """
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM jobs WHERE url = ?", (job["url"],)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE jobs SET
                    title=?, company=?, location=?, description=?,
                    match_score=?, updated_at=datetime('now')
                   WHERE url=?""",
                (
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("description", ""),
                    job.get("match_score", 0.0),
                    job["url"],
                ),
            )
            return False

        conn.execute(
            """INSERT INTO jobs
                (id, title, company, location, url, description, source, posted_date, match_score, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'found')""",
            (
                job["id"],
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job["url"],
                job.get("description", ""),
                job.get("source", ""),
                job.get("posted_date", ""),
                job.get("match_score", 0.0),
            ),
        )
        return True


def update_status(job_id: str, status: str, **extra_fields) -> None:
    """Update the status of a job, plus any extra fields (applied_at, emailed_at, etc.)."""
    allowed = {"applied_at", "emailed_at", "recruiter_email", "cover_letter", "notes"}
    sets = ["status=?", "updated_at=datetime('now')"]
    params = [status]

    for key, val in extra_fields.items():
        if key in allowed:
            sets.append(f"{key}=?")
            params.append(val)

    params.append(job_id)
    sql = f"UPDATE jobs SET {', '.join(sets)} WHERE id=?"

    with get_connection() as conn:
        conn.execute(sql, params)


def log_email(job_id: str, to_email: str, subject: str, success: bool, error_msg: str = "") -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO email_log (job_id, to_email, subject, success, error_msg) VALUES (?,?,?,?,?)",
            (job_id, to_email, subject, int(success), error_msg),
        )


def get_jobs_by_status(status: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status=? ORDER BY match_score DESC", (status,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_jobs() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_stats() -> dict:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}
