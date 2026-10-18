# SQLite persistence.
#
# Keeps per-user preferences, the global/per-user statistics, download history
# and daily quota counters across restarts. Deliberately dependency-free
# (stdlib sqlite3 only) and it does not import anything from the package, so it
# can be imported from `variables` without creating a cycle.

import json
import logging
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "media_bot.db"

_lock = threading.Lock()
_conn = None

PREF_COLUMNS = [
    "engine",
    "action",
    "stream_upload",
    "is_split",
    "zip_password",
    "unzip_password",
    "custom_caption",
    "prefix",
    "suffix",
    "caption_font",
    "thumbnail",
    "destination",
    "ytdl_format",
    "fallback",
    "torrent_files",
    "split_video",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    engine TEXT DEFAULT 'auto',
    action TEXT DEFAULT 'normal',
    stream_upload INTEGER DEFAULT 1,
    is_split INTEGER DEFAULT 0,
    zip_password TEXT DEFAULT '',
    unzip_password TEXT DEFAULT '',
    custom_caption TEXT,
    prefix TEXT DEFAULT '',
    suffix TEXT DEFAULT '',
    caption_font TEXT DEFAULT 'default',
    thumbnail TEXT,
    destination INTEGER DEFAULT 0,
    ytdl_format TEXT DEFAULT 'best',
    fallback TEXT DEFAULT '["gallerydl","cyberdrop","aria2c"]',
    torrent_files TEXT DEFAULT '',
    split_video INTEGER DEFAULT 0,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    created_at TEXT,
    urls TEXT,
    engine TEXT,
    action TEXT,
    files INTEGER DEFAULT 0,
    uploaded INTEGER DEFAULT 0,
    status TEXT
);
CREATE TABLE IF NOT EXISTS stats (
    chat_id INTEGER PRIMARY KEY,
    downloads INTEGER DEFAULT 0,
    uploads INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    total_files INTEGER DEFAULT 0,
    bytes INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS quota (
    chat_id INTEGER,
    day TEXT,
    files INTEGER DEFAULT 0,
    bytes INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, day)
);
"""


def _connect():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(_SCHEMA)
        _conn.commit()
    return _conn


def init():
    with _lock:
        _connect()
    logger.info(f"SQLite store ready at {DB_PATH}")


# --------------------------------------------------------------------------- #
# Preferences
# --------------------------------------------------------------------------- #
def load_prefs(chat_id) -> dict:
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,)).fetchone()
    if not row:
        return {}
    data = dict(row)
    try:
        data["fallback"] = json.loads(data.get("fallback") or "[]")
    except Exception:  # noqa: BLE001
        data["fallback"] = []
    return data


def save_prefs(chat_id, data: dict):
    payload = {key: data.get(key) for key in PREF_COLUMNS}
    payload["fallback"] = json.dumps(payload.get("fallback") or [])
    payload["stream_upload"] = int(bool(payload.get("stream_upload")))
    payload["is_split"] = int(bool(payload.get("is_split")))
    payload["split_video"] = int(bool(payload.get("split_video")))
    payload["destination"] = int(payload.get("destination") or 0)
    columns = ", ".join(PREF_COLUMNS)
    placeholders = ", ".join("?" for _ in PREF_COLUMNS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in PREF_COLUMNS)
    with _lock:
        conn = _connect()
        conn.execute(
            f"INSERT INTO users (chat_id, {columns}, updated_at) VALUES (?, {placeholders}, ?) "
            f"ON CONFLICT(chat_id) DO UPDATE SET {updates}, updated_at=excluded.updated_at",
            [chat_id] + [payload[c] for c in PREF_COLUMNS] + [datetime.now().isoformat()],
        )
        conn.commit()


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
def add_history(chat_id, urls, engine, action, files, uploaded, status):
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO history (chat_id, created_at, urls, engine, action, files, uploaded, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                datetime.now().isoformat(timespec="seconds"),
                json.dumps(list(urls)),
                engine,
                action,
                files,
                uploaded,
                status,
            ),
        )
        conn.commit()
        return cur.lastrowid


def _decode_history(row):
    data = dict(row)
    try:
        data["urls"] = json.loads(data.get("urls") or "[]")
    except Exception:  # noqa: BLE001
        data["urls"] = []
    return data


def list_history(chat_id, limit=10):
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM history WHERE chat_id=? ORDER BY id DESC LIMIT ?", (chat_id, limit)
        ).fetchall()
    return [_decode_history(r) for r in rows]


def get_history(entry_id):
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT * FROM history WHERE id=?", (entry_id,)).fetchone()
    return _decode_history(row) if row else None


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
def get_stats(chat_id=0) -> dict:
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT * FROM stats WHERE chat_id=?", (chat_id,)).fetchone()
    return dict(row) if row else {"downloads": 0, "uploads": 0, "failed": 0, "total_files": 0, "bytes": 0}


def bump_stats(chat_id, downloads=0, uploads=0, failed=0, total_files=0, bytes_=0):
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO stats (chat_id, downloads, uploads, failed, total_files, bytes) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "downloads=downloads+excluded.downloads, uploads=uploads+excluded.uploads, "
            "failed=failed+excluded.failed, total_files=total_files+excluded.total_files, "
            "bytes=bytes+excluded.bytes",
            (chat_id, downloads, uploads, failed, total_files, bytes_),
        )
        conn.commit()


def all_chat_ids():
    with _lock:
        conn = _connect()
        rows = conn.execute("SELECT chat_id FROM users UNION SELECT chat_id FROM stats").fetchall()
    return [r["chat_id"] for r in rows if r["chat_id"]]


# --------------------------------------------------------------------------- #
# Quota
# --------------------------------------------------------------------------- #
def get_quota(chat_id) -> dict:
    today = date.today().isoformat()
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT * FROM quota WHERE chat_id=? AND day=?", (chat_id, today)
        ).fetchone()
    return dict(row) if row else {"chat_id": chat_id, "day": today, "files": 0, "bytes": 0}


def bump_quota(chat_id, files=0, bytes_=0):
    today = date.today().isoformat()
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO quota (chat_id, day, files, bytes) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id, day) DO UPDATE SET "
            "files=files+excluded.files, bytes=bytes+excluded.bytes",
            (chat_id, today, files, bytes_),
        )
        conn.commit()
