# Central runtime configuration and shared state.
#
# Mirrors the reference layout (colab_leecher/utility/variables.py): all the
# mutable, cross-module state lives in small classes so the downloader,
# uploader and bot handlers can share it without threading arguments around.

import json
import os
from datetime import datetime
from pathlib import Path
from time import time

# repository root = <root>/media_bot/utility/variables.py -> parents[2]
ROOT_DIR = Path(__file__).resolve().parents[2]


def _load_credentials() -> dict:
    """Load credentials.json from the repo root (override with MEDIA_BOT_CREDENTIALS)."""
    path = Path(os.environ.get("MEDIA_BOT_CREDENTIALS", ROOT_DIR / "credentials.json"))
    if path.exists():
        with open(path, "r", encoding="utf-8") as file:
            return json.loads(file.read())
    return {}


credentials = _load_credentials()


def _raw(key: str, default=None):
    """Prefer the MEDIA_BOT_<key> environment variable, then credentials.json."""
    env = os.environ.get(f"MEDIA_BOT_{key}")
    if env is not None:
        return env
    return credentials.get(key, default)


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class Config:
    # ---- Telegram credentials ----
    API_ID = _as_int(_raw("API_ID", 0))
    API_HASH = str(_raw("API_HASH", ""))
    BOT_TOKEN = str(_raw("BOT_TOKEN", ""))
    OWNER = _as_int(_raw("OWNER", 0))
    DUMP_CHANNEL_ID = _as_int(_raw("DUMP_CHANNEL_ID", 0))

    # ---- Behaviour ----
    MAX_FILE_SIZE_MB = _as_int(_raw("MAX_FILE_SIZE_MB", 2000))
    ALBUM_SIZE = _as_int(_raw("ALBUM_SIZE", 10))
    DELAY_BETWEEN_FILES = _as_int(_raw("DELAY_BETWEEN_FILES", 3))
    MESSAGE_DELETE_DELAY = _as_int(_raw("MESSAGE_DELETE_DELAY", 10))

    AUTO_CLEANUP = _as_bool(_raw("AUTO_CLEANUP", True), True)
    SEND_AS_ALBUM = _as_bool(_raw("SEND_AS_ALBUM", True), True)
    ENABLE_CUSTOM_CAPTIONS = _as_bool(_raw("ENABLE_CUSTOM_CAPTIONS", True), True)

    # Twitter cookies may be a JSON list/dict (credentials.json) or a raw JSON
    # string (environment variable). helper.parse_cookies() normalises both.
    TWITTER_COOKIES = _raw("TWITTER_COOKIES", [])

    DOWNLOAD_PATH = Path(_raw("DOWNLOAD_PATH", ROOT_DIR / "Downloads"))


class Paths:
    ROOT = ROOT_DIR
    WORK_PATH = ROOT_DIR

    DOWN_PATH = Config.DOWNLOAD_PATH
    ARIA2_DIR = Path.home() / ".aria2"

    THMB_PATH = ROOT_DIR / "media_bot" / "Thumbnail.jpg"
    DEFAULT_THMB = ROOT_DIR / "custom_thmb.jpg"

    TOKEN_FILE = ROOT_DIR / "token.json"
    TWITTER_COOKIE_FILE = ROOT_DIR / "twitter_cookies.txt"
    M3U8_DIR = Config.DOWNLOAD_PATH / "m3u8"


class Stats:
    downloads = 0
    uploads = 0
    failed = 0
    total_files = 0


class Transfer:
    """Aggregate byte counters used by the status display."""

    down_bytes = [0, 0]
    up_bytes = [0, 0]
    total_down_size = 0
    sent_file = []
    sent_file_names = []


class BotTimes:
    current_time = time()
    start_time = datetime.now()
    task_start = datetime.now()


class Trackers:
    items = []


class Messages:
    download_name = ""
    task_msg = ""
    status_head = ""


class MSG:
    status_msg = None
    sent_msg = None


# chat_id -> {"mode", "stage", "custom_caption", "after_date", "before_date"}
user_states: dict = {}


def reset_times():
    BotTimes.start_time = datetime.now()
    BotTimes.task_start = datetime.now()
    BotTimes.current_time = time()
