"""图片生成/编辑调用日志与统计。

独立 SQLite 文件，不复用 request_log，避免与老库结构冲突。
仅新增/迁移本模块自己的表；不改、不删任何旧业务日志。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config

_BJT = timezone(timedelta(hours=8))
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_db_path: str | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS image_call_logs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id      TEXT UNIQUE NOT NULL,
  created_at      REAL NOT NULL,
  finished_at     REAL,
  api_key_name    TEXT,
  action          TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'running',
  account_key     TEXT,
  account_email   TEXT,
  main_model      TEXT,
  tool_model      TEXT,
  size            TEXT,
  prompt_preview  TEXT,
  prompt_hash     TEXT,
  duration_ms     INTEGER,
  image_count     INTEGER DEFAULT 0,
  cached_images   INTEGER DEFAULT 0,
  image_bytes     INTEGER DEFAULT 0,
  cache_paths     TEXT,
  usage_json      TEXT,
  error_type      TEXT,
  error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_image_logs_created ON image_call_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_image_logs_status ON image_call_logs(status);
CREATE INDEX IF NOT EXISTS idx_image_logs_account ON image_call_logs(account_key);
CREATE INDEX IF NOT EXISTS idx_image_logs_action ON image_call_logs(action);

CREATE TABLE IF NOT EXISTS image_attempt_logs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  image_log_id    INTEGER NOT NULL,
  request_id      TEXT NOT NULL,
  started_at      REAL NOT NULL,
  finished_at     REAL,
  account_key     TEXT,
  account_email   TEXT,
  status          TEXT NOT NULL DEFAULT 'running',
  duration_ms     INTEGER,
  image_count     INTEGER DEFAULT 0,
  image_bytes     INTEGER DEFAULT 0,
  error_type      TEXT,
  error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_image_attempt_log_id ON image_attempt_logs(image_log_id);
CREATE INDEX IF NOT EXISTS idx_image_attempt_account ON image_attempt_logs(account_key);
CREATE INDEX IF NOT EXISTS idx_image_attempt_created ON image_attempt_logs(started_at);
"""


_MIGRATIONS: dict[str, str] = {
    "finished_at": "ALTER TABLE image_call_logs ADD COLUMN finished_at REAL",
    "api_key_name": "ALTER TABLE image_call_logs ADD COLUMN api_key_name TEXT",
    "action": "ALTER TABLE image_call_logs ADD COLUMN action TEXT NOT NULL DEFAULT 'generate'",
    "status": "ALTER TABLE image_call_logs ADD COLUMN status TEXT NOT NULL DEFAULT 'running'",
    "account_key": "ALTER TABLE image_call_logs ADD COLUMN account_key TEXT",
    "account_email": "ALTER TABLE image_call_logs ADD COLUMN account_email TEXT",
    "main_model": "ALTER TABLE image_call_logs ADD COLUMN main_model TEXT",
    "tool_model": "ALTER TABLE image_call_logs ADD COLUMN tool_model TEXT",
    "size": "ALTER TABLE image_call_logs ADD COLUMN size TEXT",
    "prompt_preview": "ALTER TABLE image_call_logs ADD COLUMN prompt_preview TEXT",
    "prompt_hash": "ALTER TABLE image_call_logs ADD COLUMN prompt_hash TEXT",
    "duration_ms": "ALTER TABLE image_call_logs ADD COLUMN duration_ms INTEGER",
    "image_count": "ALTER TABLE image_call_logs ADD COLUMN image_count INTEGER DEFAULT 0",
    "cached_images": "ALTER TABLE image_call_logs ADD COLUMN cached_images INTEGER DEFAULT 0",
    "image_bytes": "ALTER TABLE image_call_logs ADD COLUMN image_bytes INTEGER DEFAULT 0",
    "cache_paths": "ALTER TABLE image_call_logs ADD COLUMN cache_paths TEXT",
    "usage_json": "ALTER TABLE image_call_logs ADD COLUMN usage_json TEXT",
    "error_type": "ALTER TABLE image_call_logs ADD COLUMN error_type TEXT",
    "error_message": "ALTER TABLE image_call_logs ADD COLUMN error_message TEXT",
}


def _resolve_db_path() -> str:
    raw = (config.get().get("images") or {}).get("dbPath") or "image_logs.db"
    raw = str(raw).strip() or "image_logs.db"
    if os.path.isabs(raw):
        return raw
    return os.path.join(config.DATA_DIR, raw)


def init() -> None:
    global _conn, _db_path
    with _lock:
        path = _resolve_db_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.execute("PRAGMA busy_timeout=5000")
        _conn.executescript(_SCHEMA)
        _ensure_migrations(_conn)
        _conn.commit()
        _db_path = path
        cleanup_stale_running(1800)
        print(f"[image_db] Using {path}")


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        init()
    assert _conn is not None
    return _conn


def _ensure_migrations(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(image_call_logs)").fetchall()}
    changed = False
    for col, sql in _MIGRATIONS.items():
        if col not in cols:
            conn.execute(sql)
            changed = True
    if changed:
        conn.commit()


def checkpoint() -> None:
    try:
        with _lock:
            _get_conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        pass


def start_call(
    *,
    request_id: str,
    api_key_name: str | None,
    action: str,
    main_model: str,
    tool_model: str,
    size: str | None,
    prompt_preview: str,
    prompt_hash: str,
) -> int:
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            """INSERT INTO image_call_logs
               (request_id, created_at, api_key_name, action, status,
                main_model, tool_model, size, prompt_preview, prompt_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                request_id, time.time(), api_key_name, action, "running",
                main_model, tool_model, size, prompt_preview, prompt_hash,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def finish_call(
    log_id: int,
    *,
    status: str,
    account_key: str | None = None,
    account_email: str | None = None,
    duration_ms: int | None = None,
    image_count: int = 0,
    cached_images: int = 0,
    image_bytes: int = 0,
    cache_paths: list[str] | None = None,
    usage: dict | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    with _lock:
        _get_conn().execute(
            """UPDATE image_call_logs SET
                 finished_at=?, status=?, account_key=COALESCE(?, account_key),
                 account_email=COALESCE(?, account_email), duration_ms=?,
                 image_count=?, cached_images=?, image_bytes=?, cache_paths=?,
                 usage_json=?, error_type=?, error_message=?
               WHERE id=?""",
            (
                time.time(), status, account_key, account_email, duration_ms,
                int(image_count or 0), int(cached_images or 0), int(image_bytes or 0),
                json.dumps(cache_paths or [], ensure_ascii=False),
                json.dumps(usage, ensure_ascii=False) if isinstance(usage, dict) else None,
                error_type, (error_message or "")[:1000] if error_message else None,
                log_id,
            ),
        )
        _get_conn().commit()


def mark_attempt(log_id: int, *, account_key: str, account_email: str | None) -> None:
    with _lock:
        _get_conn().execute(
            "UPDATE image_call_logs SET account_key=?, account_email=? WHERE id=?",
            (account_key, account_email, log_id),
        )
        _get_conn().commit()


def start_attempt(log_id: int, *, request_id: str, account_key: str, account_email: str | None) -> int:
    """记录一次真实上游账号尝试。用于账号 Top 统计；不影响主调用总数。"""
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            """INSERT INTO image_attempt_logs
               (image_log_id, request_id, started_at, account_key, account_email, status)
               VALUES (?,?,?,?,?,?)""",
            (log_id, request_id, time.time(), account_key, account_email, "running"),
        )
        conn.commit()
        return int(cur.lastrowid)


def finish_attempt(
    attempt_id: int,
    *,
    status: str,
    duration_ms: int | None = None,
    image_count: int = 0,
    image_bytes: int = 0,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    with _lock:
        _get_conn().execute(
            """UPDATE image_attempt_logs SET
                 finished_at=?, status=?, duration_ms=?, image_count=?, image_bytes=?,
                 error_type=?, error_message=?
               WHERE id=?""",
            (
                time.time(), status, duration_ms, int(image_count or 0), int(image_bytes or 0),
                error_type, (error_message or "")[:1000] if error_message else None,
                attempt_id,
            ),
        )
        _get_conn().commit()


def get_log(log_id: int) -> dict | None:
    with _lock:
        row = _get_conn().execute("SELECT * FROM image_call_logs WHERE id=?", (log_id,)).fetchone()
    return dict(row) if row else None


def recent(limit: int = 10) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM image_call_logs ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def summary() -> dict:
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            """SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN action='generate' THEN 1 ELSE 0 END) AS generate_count,
                 SUM(CASE WHEN action='edit' THEN 1 ELSE 0 END) AS edit_count,
                 SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_count,
                 SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count,
                 SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running_count,
                 AVG(CASE WHEN status='success' THEN duration_ms END) AS avg_duration_ms,
                 SUM(COALESCE(duration_ms,0)) AS total_duration_ms,
                 SUM(COALESCE(image_bytes,0)) AS image_bytes,
                 SUM(COALESCE(cached_images,0)) AS cached_images
               FROM image_call_logs"""
        ).fetchone()
    d = dict(row) if row else {}
    return {k: (v if v is not None else 0) for k, v in d.items()}


def account_top(limit: int = 5) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            """SELECT
                 COALESCE(account_key, '') AS account_key,
                 COALESCE(account_email, '') AS account_email,
                 COUNT(*) AS total,
                 SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_count,
                 SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count,
                 SUM(COALESCE(duration_ms,0)) AS total_duration_ms,
                 AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms END) AS avg_duration_ms,
                 SUM(COALESCE(image_bytes,0)) AS image_bytes
               FROM image_attempt_logs
               WHERE COALESCE(account_key, '') != ''
               GROUP BY account_key, account_email
               ORDER BY total DESC, success_count DESC
               LIMIT ?""",
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def cleanup_stale_running(max_age_seconds: int = 1800) -> int:
    cutoff = time.time() - int(max_age_seconds)
    with _lock:
        now = time.time()
        cur = _get_conn().execute(
            """UPDATE image_call_logs
               SET status='failed', finished_at=?, error_type='stale',
                   error_message='process ended before image call completed'
               WHERE status='running' AND created_at < ?""",
            (now, cutoff),
        )
        _get_conn().execute(
            """UPDATE image_attempt_logs
               SET status='failed', finished_at=?, error_type='stale',
                   error_message='process ended before image attempt completed'
               WHERE status='running' AND started_at < ?""",
            (now, cutoff),
        )
        _get_conn().commit()
        return int(cur.rowcount or 0)


def fmt_bjt(ts: float | None) -> str:
    if not ts:
        return "?"
    return datetime.fromtimestamp(float(ts), tz=_BJT).strftime("%m-%d %H:%M:%S")


def seconds_since(ts: float | None) -> int:
    if not ts:
        return 0
    return max(0, int(time.time() - float(ts)))
