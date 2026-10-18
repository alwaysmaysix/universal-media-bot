# Small, dependency-light helpers shared across the bot.
#
# Ported from the original notebook: cookie parsing, size parsing, the
# "iZombie" style progress display, caption formatting, thumbnail generation
# and the network scrapers used by the BaddieHub downloader.

import json
import logging
import re
import subprocess
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

import certifi
import requests
from humanize import naturalsize

from media_bot.utility.variables import Paths, Trackers

logger = logging.getLogger(__name__)

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

TRACKER_FILES = [
    ("best_aria2.txt", "https://cf.trackerslist.com/best_aria2.txt"),
    ("all_aria2.txt", "https://cf.trackerslist.com/all_aria2.txt"),
]
DEFAULT_TRACKERS = [
    "udp://tracker.openbittorrent.com:80/announce",
    "udp://tracker.opentrackr.org:1337/announce",
]


# --------------------------------------------------------------------------- #
# Cookie / text helpers
# --------------------------------------------------------------------------- #
def parse_cookies(cookie_data):
    """Accept a JSON string, list or dict of cookies and return {name: value}."""
    if not cookie_data:
        return {}
    if isinstance(cookie_data, str):
        try:
            cookie_data = json.loads(cookie_data.strip())
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Cookie parse error: {exc}")
            return {}
    cookies = {}
    if isinstance(cookie_data, list):
        for cookie in cookie_data:
            if isinstance(cookie, dict) and "name" in cookie and "value" in cookie:
                cookies[cookie["name"]] = cookie["value"]
    elif isinstance(cookie_data, dict):
        cookies = dict(cookie_data)
    return cookies


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return ANSI_ESCAPE.sub("", text)


def write_cookies(cookies: dict, path, domain: str = ".twitter.com") -> Path:
    """Write cookies in Netscape format for yt-dlp / gallery-dl / aria2c."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write("# Netscape HTTP Cookie File\n")
        for name, value in cookies.items():
            file.write(f"{domain}\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")
    return path


def write_twitter_cookie_file(cookies: dict) -> Path:
    """Write the configured Twitter cookies to the default cookie file."""
    return write_cookies(cookies, Paths.TWITTER_COOKIE_FILE, ".twitter.com")


def cookie_file_for(chat_id, site: str) -> Path:
    """Per-user, per-site Netscape cookie file path."""
    return Paths.COOKIES_DIR / f"{chat_id}_{site}.txt"


def cookie_domain(site: str) -> str:
    return {
        "twitter": ".twitter.com",
        "instagram": ".instagram.com",
        "tiktok": ".tiktok.com",
        "reddit": ".reddit.com",
        "pixiv": ".pixiv.net",
        "facebook": ".facebook.com",
    }.get(site, f".{site}.com")


def set_cookie_file(chat_id, site: str, cookies: dict) -> Path:
    """Persist a user's cookies for one site and return the cookie file path."""
    return write_cookies(cookies, cookie_file_for(chat_id, site), cookie_domain(site))


def build_user_cookie_file(chat_id):
    """Merge every per-site cookie file for a user into one Netscape file.

    Downloaders accept a single cookie file and match by domain, so merging is
    enough to cover Twitter, Instagram, TikTok, ... at once.
    """
    if not Paths.COOKIES_DIR.exists():
        return None
    parts = [
        f
        for f in sorted(Paths.COOKIES_DIR.glob(f"{chat_id}_*.txt"))
        if not f.name.endswith("_all.txt")
    ]
    global_file = Path(Paths.TWITTER_COOKIE_FILE)
    if global_file.exists():
        parts.append(global_file)
    merged = Paths.COOKIES_DIR / f"{chat_id}_all.txt"
    if not parts:
        if merged.exists():
            merged.unlink()
        return None
    with open(merged, "w", encoding="utf-8") as out:
        out.write("# Netscape HTTP Cookie File\n")
        for part in parts:
            try:
                for line in part.read_text(encoding="utf-8").splitlines():
                    if line and not line.startswith("#"):
                        out.write(line + "\n")
            except Exception:  # noqa: BLE001
                continue
    return merged


def sizeChecker(url, max_bytes: int):
    """Best-effort HEAD request.

    Returns (ok, size_bytes). ok is False only when the remote size is known
    and exceeds max_bytes.
    """
    if not url.startswith(("http://", "https://")):
        return True, 0
    try:
        response = requests.head(
            url, allow_redirects=True, timeout=10, verify=certifi.where()
        )
        length = int(response.headers.get("Content-Length", 0) or 0)
        if length and max_bytes and length > max_bytes:
            return False, length
        return True, length
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"sizeChecker failed for {url}: {exc}")
        return True, 0


def create_gallery_config(cookies: dict) -> None:
    """Create ~/.config/gallery-dl/config.json with the Twitter cookies."""
    config_dir = Path.home() / ".config" / "gallery-dl"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "extractor": {
            "twitter": {"cookies": cookies},
            "base-directory": str(Paths.DOWN_PATH),
        }
    }
    with open(config_dir / "config.json", "w", encoding="utf-8") as file:
        json.dump(config, file, indent=2)
    logger.info("Gallery-dl config created")


# --------------------------------------------------------------------------- #
# Size / time / progress formatting
# --------------------------------------------------------------------------- #
def parse_size_to_bytes(size_str) -> float:
    """Parse strings like '15.3MiB' into bytes."""
    if not size_str:
        return 0
    match = re.match(r"([\d.]+)\s*(\w+)", str(size_str))
    if not match:
        try:
            return float(size_str)
        except (TypeError, ValueError):
            return 0
    value, unit = match.groups()
    value = float(value)
    unit = unit.lower()
    units = {
        "b": 1,
        "kb": 1000**1,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
        "kib": 1024**1,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
    }
    if unit.endswith("s"):
        unit = unit[:-1]
    return value * units.get(unit, 1)


def format_time_hms(seconds) -> str:
    """Format seconds into a compact Hh Mm Ss string."""
    if seconds is None:
        return "N/A"
    try:
        seconds = int(seconds)
        total = timedelta(seconds=seconds).total_seconds()
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{int(hours)}h{int(minutes)}m{int(seconds)}s"
    except (TypeError, ValueError):
        return "N/A"


def generate_progress_bar(percentage, total_blocks: int = 10) -> str:
    """Build the ⬢⬡ progress bar."""
    if percentage is None:
        return "⬡" * total_blocks
    filled = int(total_blocks * (percentage / 100))
    filled = max(0, min(total_blocks, filled))
    return "⬢" * filled + "⬡" * (total_blocks - filled)


def build_custom_progress_display(
    url, progress_data, file_index, total_files, user_name, start_time
) -> str:
    """Build the custom 'iZombie' style progress display."""
    task_name = f"[{file_index}/{total_files}] {url[:50]}..."
    elapsed_str = format_time_hms(time.time() - start_time)
    status_str = "Download 📥"

    if not progress_data:
        return (
            f"#Task: {task_name}\n"
            "➜ ⬡⬡⬡⬡⬡⬡⬡⬡⬡⬡ » ? %\n"
            "➜ Status : Initializing...\n"
            "➜ Done   : 0 MB of ? MB\n"
            "➜ Speed  : ...\n"
            "➜ ETA    : ...\n"
            f"➜ Past   : {elapsed_str}\n"
            f"➜ User   : {user_name}"
        )

    bar = "⬡⬡⬡⬡⬡⬡⬡⬡⬡⬡"
    percentage_str = "N/A %"
    done_str = "N/A"
    total_str = "Unknown"
    speed_str = "N/A"
    eta_str = "N/A"

    dl_type = progress_data.get("type", "unknown")

    if dl_type in ["gdrive", "telegram", "ytdl", "magnet", "mega", "m3u8", "aria2c"]:
        status_str = f"Download 📥 ({dl_type})"
        percentage = progress_data.get("percentage")
        if percentage is not None:
            bar = generate_progress_bar(percentage)
            percentage_str = f"{percentage:.1f}%"
        done_str = naturalsize(progress_data.get("downloaded_bytes", 0))
        total_str = progress_data.get("total_size_str", "Unknown")
        speed_str = progress_data.get("speed", "N/A")
        eta_str = progress_data.get("eta", "N/A")
    elif dl_type == "gallery-dl":
        status_str = "Download 📥 (gallery-dl)"
        percentage = progress_data.get("percentage")
        if percentage is not None:
            bar = generate_progress_bar(percentage)
            percentage_str = f"{percentage:.1f}%"
        done_str = naturalsize(progress_data.get("downloaded_bytes", 0))
        total_str = progress_data.get("total_size_str", "Unknown")
        speed_str = progress_data.get("speed", "N/A")
        eta_raw = progress_data.get("eta")
        if eta_raw:
            try:
                parts = eta_raw.split(":")
                eta_sec = 0
                if len(parts) == 2:
                    eta_sec = int(parts[0]) * 60 + int(parts[1])
                elif len(parts) == 3:
                    eta_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                eta_str = format_time_hms(eta_sec)
            except (TypeError, ValueError):
                eta_str = "N/A"
    elif dl_type == "cyberdrop-dl":
        done_str = naturalsize(progress_data.get("downloaded_bytes", 0))
        status_str = f"Download 📥 ({progress_data.get('completed_files', 0)} files)"

    display = (
        f"#Task: {task_name}\n"
        f"➜ {bar} » {percentage_str}\n"
        f"➜ Status : {status_str}\n"
        f"➜ Done   : {done_str} of {total_str}\n"
        f"➜ Speed  : {speed_str}\n"
        f"➜ ETA    : {eta_str}\n"
        f"➜ Past   : {elapsed_str}\n"
        f"➜ User   : {user_name}"
    )
    return display.strip()


def build_upload_progress_display(
    filename, progress_data, user_name="User", file_index=None, total_files=None
) -> str:
    """The same ⬢⬡ layout used for downloads, applied to uploads."""
    task_name = str(filename)[:50]
    if file_index and total_files:
        task_name = f"[{file_index}/{total_files}] {task_name}"

    percentage = progress_data.get("percentage") or 0
    bar = generate_progress_bar(percentage)
    elapsed_str = format_time_hms(progress_data.get("elapsed", 0))

    return (
        f"#Task: ⬆️ {task_name}\n"
        f"➜ {bar} » {percentage:.1f} %\n"
        "➜ Status : Upload 📤\n"
        f"➜ Done   : {naturalsize(progress_data.get('downloaded_bytes', 0))}"
        f" of {progress_data.get('total_size_str', 'Unknown')}\n"
        f"➜ Speed  : {progress_data.get('speed', 'N/A')}\n"
        f"➜ ETA    : {progress_data.get('eta', 'N/A')}\n"
        f"➜ Past   : {elapsed_str}\n"
        f"➜ User   : {user_name}"
    ).strip()


_PROGRESS_TICKS: dict = {}


def _progress_key(status_msg):
    """Stable per-status-message key (chat id + message id when available)."""
    chat = getattr(status_msg, "chat", None)
    chat_id = getattr(chat, "id", None)
    mid = getattr(status_msg, "id", None)
    if chat_id is None and mid is None:
        return id(status_msg)
    return (chat_id, mid)


def progress_due(status_msg, interval: float = 2.0) -> bool:
    """True when this status message may be edited again.

    The throttle is keyed per status message, so several users (or several
    concurrent downloads) no longer starve each other's updates the way a
    single global timestamp did.
    """
    if not status_msg:
        return False
    key = _progress_key(status_msg)
    now = time.time()
    if now - _PROGRESS_TICKS.get(key, 0) < interval:
        return False
    _PROGRESS_TICKS[key] = now
    return True


async def update_progress(
    status_msg,
    url,
    file_index,
    total_files,
    user_name,
    start_time,
    downloaded_bytes,
    total_bytes,
    speed_str="N/A",
    eta_str="N/A",
    dl_type="unknown",
    percentage=None,
    total_size_str=None,
):
    """Standardised progress reporting for the specialised downloaders.

    `percentage` / `total_size_str` can be supplied directly for engines whose
    progress is not a simple byte ratio (e.g. m3u8 segment counts).
    """
    if not status_msg:
        return
    if not progress_due(status_msg, 2.0):
        return

    if percentage is None:
        percentage = downloaded_bytes / total_bytes * 100 if total_bytes > 0 else 0
    progress_data = {
        "type": dl_type,
        "percentage": percentage,
        "downloaded_bytes": downloaded_bytes,
        "total_size_str": (
            total_size_str if total_size_str is not None else naturalsize(total_bytes)
        ),
        "speed": speed_str,
        "eta": eta_str,
    }
    display = build_custom_progress_display(
        url, progress_data, file_index, total_files, user_name, start_time
    )

    # Imported lazily to avoid a hard dependency loop at import time.
    from pyrogram.errors import FloodWait, MessageNotModified

    try:
        await status_msg.edit_text(display)
    except (MessageNotModified, FloodWait):
        pass


_TWITTER_SAFE = re.compile(r"\W")


def apply_font(text: str, font: str = "default") -> str:
    """Wrap a caption in Telegram markup for the chosen 'caption font'."""
    if not text:
        return text
    if font == "bold":
        return f"**{text}**"
    if font == "mono":
        return f"`{text}`"
    if font == "spoiler":
        return f"||{text}||"
    return text


def format_caption(
    template,
    filename,
    file_size,
    current: int = 1,
    total: int = 1,
    prefix: str = "",
    suffix: str = "",
    font: str = "default",
) -> str:
    """Fill placeholders {filename}/{size}/{index}/{total} (max 1024 chars)."""
    if not template:
        caption = f"📄 {filename}\n💾 {naturalsize(file_size)}"
        if total > 1:
            caption = f"[{current}/{total}] " + caption
    else:
        caption = template
        caption = caption.replace("{filename}", filename)
        caption = caption.replace("{size}", naturalsize(file_size))
        caption = caption.replace("{index}", str(current))
        caption = caption.replace("{total}", str(total))
    if prefix:
        caption = f"{prefix}{caption}"
    if suffix:
        caption = f"{caption}{suffix}"
    caption = apply_font(caption, font)
    return caption[:1024]


def baddiehub_caption(title: str):
    """Turn a scraped page title into a single hashtag caption."""
    if not title:
        return None
    clean_title = _TWITTER_SAFE.sub("", title)
    return f"#{clean_title}" if clean_title else None


# --------------------------------------------------------------------------- #
# Thumbnails
# --------------------------------------------------------------------------- #
def _thumbnail_from_ffmpeg(video_path: Path):
    """Fallback thumbnail generator using ffprobe / ffmpeg (no moviepy)."""
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(video_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        info = json.loads(probe.stdout.decode("utf-8", "ignore"))
        duration = int(float(info.get("format", {}).get("duration", 0)))
        width = height = 0
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                width = int(stream.get("width", 0))
                height = int(stream.get("height", 0))
                break
        thumb_path = video_path.with_name(f"{video_path.stem}_thumb.jpg")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(max(duration // 2, 0)),
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                "scale=320:-1",
                str(thumb_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if thumb_path.exists():
            return str(thumb_path), duration, width, height
    except Exception as exc:  # noqa: BLE001
        logger.error(f"ffmpeg thumbnail fallback error: {exc}")
    return None, 0, 0, 0


def generate_thumbnail(video_path):
    """Generate a thumbnail and extract video metadata.

    Returns: (thumb_path, duration, width, height)
    """
    try:
        try:  # moviepy < 2
            from moviepy.editor import VideoFileClip
        except ImportError:  # moviepy >= 2
            from moviepy import VideoFileClip
        from PIL import Image

        video_path_p = Path(video_path)
        clip = VideoFileClip(str(video_path))
        duration = int(clip.duration)
        width, height = clip.size
        frame = clip.get_frame(clip.duration / 2)
        thumb_path = str(video_path_p.with_name(f"{video_path_p.stem}_thumb.jpg"))
        Image.fromarray(frame).save(thumb_path)
        clip.close()

        if Path(thumb_path).stat().st_size > 200 * 1024:
            img = Image.open(thumb_path)
            img.save(thumb_path, quality=70, optimize=True)
        return thumb_path, duration, width, height
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Thumbnail/Metadata generation error: {exc}")
        return _thumbnail_from_ffmpeg(Path(video_path))


# --------------------------------------------------------------------------- #
# Trackers (for the libtorrent downloader)
# --------------------------------------------------------------------------- #
def load_trackers():
    """Download and cache the public tracker lists used for magnet links."""
    trackers = []
    try:
        Paths.ARIA2_DIR.mkdir(parents=True, exist_ok=True)
        for fname, url in TRACKER_FILES:
            fpath = Paths.ARIA2_DIR / fname
            if not fpath.exists():
                try:
                    response = requests.get(url, timeout=5, verify=certifi.where())
                    response.raise_for_status()
                    fpath.write_text(response.text, encoding="utf-8")
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"Failed to fetch tracker list {url}: {exc}")
            if fpath.exists():
                try:
                    trackers.extend(
                        line.strip()
                        for line in fpath.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"Failed to read tracker file {fpath}: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Failed to load trackers: {exc}")

    Trackers.items = sorted(set(trackers)) or list(DEFAULT_TRACKERS)
    if not trackers:
        logger.warning("Tracker list is empty, using defaults.")
    else:
        logger.info(f"Loaded {len(Trackers.items)} trackers for libtorrent.")
    return Trackers.items


# --------------------------------------------------------------------------- #
# Website scraping (BaddieHub)
# --------------------------------------------------------------------------- #
def get_website_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    return requests.get(url, headers=headers, verify=certifi.where(), timeout=30).text


def extract_urls(html: str, base_url: str):
    pattern = r"""(?<=href=["'])(?:https?:\/\/(?:www\.)?[^"']+\.[^"'\/]+)?\/[^"']*"""
    urls = re.findall(pattern, html)
    parsed_base = urlparse(base_url)
    internal = []
    for url in urls:
        parsed = urlparse(url)
        if not parsed.netloc:
            internal.append(f"{parsed_base.scheme}://{parsed_base.netloc}{url}")
        elif parsed.netloc == parsed_base.netloc:
            internal.append(url)
    return internal


def extract_media_urls(html: str):
    return re.findall(r"""https?://[^"'\s]+\.(?:mp4|hls|webm|mp3|m3u8)""", html)
