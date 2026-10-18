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


def _as_id_set(value):
    """Parse a list or comma separated string of Telegram user ids."""
    if not value:
        return set()
    parts = value.replace(";", ",").split(",") if isinstance(value, str) else value
    ids = set()
    for part in parts:
        try:
            ids.add(int(part))
        except (TypeError, ValueError):
            continue
    return ids


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

    # ---- Access control ----
    ALLOWED_USERS = _as_id_set(_raw("ALLOWED_USERS", []))

    # ---- Limits ----
    RATE_LIMIT_SECONDS = _as_int(_raw("RATE_LIMIT_SECONDS", 5))
    QUOTA_FILES_PER_DAY = _as_int(_raw("QUOTA_FILES_PER_DAY", 0))
    QUOTA_GB_PER_DAY = _as_int(_raw("QUOTA_GB_PER_DAY", 0))

    # ---- Download behaviour ----
    RESUME = _as_bool(_raw("RESUME", True), True)
    SPLIT_SIZE_MB = _as_int(_raw("SPLIT_SIZE_MB", 2000))
    DEFAULT_FALLBACK = _raw("FALLBACK_CHAIN", ["gallerydl", "cyberdrop", "aria2c"])


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

    COOKIES_DIR = ROOT_DIR / "cookies"
    THUMBS_DIR = ROOT_DIR / "thumbs"


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


# chat_id -> {"mode", "stage", "prefs": Prefs}
user_states: dict = {}

# --------------------------------------------------------------------------- #
# Per-user download preferences.
# Mirrors the reference project's BOT.Options / BOT.Setting, but scoped per
# chat so multiple users can hold different settings at the same time.
# --------------------------------------------------------------------------- #
ENGINE_LABELS = {
    "auto": "🌐 Auto (Smart)",
    "gallerydl": "📦 gallery-dl",
    "cyberdrop": "☁️ cyberdrop-dl",
    "aria2c": "⚡ aria2c",
    "mega": "💾 megadl",
}

ACTION_LABELS = {
    "normal": "📄 Regular",
    "zip": "🗜 Compress",
    "unzip": "📂 Extract",
    "undzip": "🔁 Unzip+Zip",
}

FONT_LABELS = {
    "default": "Default",
    "bold": "Bold",
    "mono": "Monospace",
    "spoiler": "Spoiler",
}

FORMAT_LABELS = {
    "best": "Best (video+audio)",
    "1080": "1080p",
    "720": "720p",
    "480": "480p",
    "worst": "Smallest",
    "audio": "Audio only (mp3)",
}

COOKIE_SITES = ["twitter", "instagram", "tiktok", "reddit", "pixiv", "facebook"]


class Prefs:
    """Everything the settings keyboard can toggle for one user.

    Persisted to SQLite via store.save_prefs() so it survives restarts.
    """

    def __init__(self):
        self.engine = "auto"           # auto | gallerydl | cyberdrop | aria2c | mega
        self.action = "normal"         # normal | zip | unzip | undzip
        self.stream_upload = True      # True = media, False = document
        self.is_split = False          # split archives into parts
        self.split_video = False       # split oversized videos
        self.zip_password = ""
        self.unzip_password = ""
        self.custom_caption = None
        self.prefix = ""
        self.suffix = ""
        self.caption_font = "default"  # default | bold | mono | spoiler
        self.thumbnail = None          # absolute path or None
        self.destination = 0           # chat/channel id, 0 = configured default
        self.ytdl_format = "best"      # best | 1080 | 720 | 480 | worst | audio
        self.fallback = ["gallerydl", "cyberdrop", "aria2c"]
        self.torrent_files = ""        # aria2c --select-file value
        self.after_date = None
        self.before_date = None

    def reset(self):
        self.__init__()

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "Prefs":
        prefs = cls()
        for key, value in (data or {}).items():
            if not hasattr(prefs, key):
                continue
            if key in ("stream_upload", "is_split", "split_video"):
                value = bool(value)
            elif key == "destination":
                value = int(value or 0)
            elif key == "fallback":
                value = list(value) if isinstance(value, list) else prefs.fallback
            setattr(prefs, key, value)
        return prefs


def get_prefs(chat_id) -> "Prefs":
    from media_bot.utility import store

    state = user_states.setdefault(chat_id, {})
    prefs = state.get("prefs")
    if prefs is None:
        try:
            data = store.load_prefs(chat_id)
        except Exception:  # noqa: BLE001
            data = {}
        prefs = Prefs.from_dict(data) if data else Prefs()
        state["prefs"] = prefs
    return prefs


def save_prefs(chat_id, prefs=None) -> None:
    from media_bot.utility import store

    if prefs is None:
        prefs = get_prefs(chat_id)
    try:
        store.save_prefs(chat_id, prefs.to_dict())
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("Could not persist prefs for %s", chat_id)


def reset_times():
    BotTimes.start_time = datetime.now()
    BotTimes.task_start = datetime.now()
    BotTimes.current_time = time()
