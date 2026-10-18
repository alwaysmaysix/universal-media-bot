# yt-dlp downloader (YouTube, Twitter/X and ~1800 other sites).
#
# yt-dlp is synchronous, so it runs in a worker thread while this coroutine
# polls a shared state dict and refreshes the status message.
# Reference analogue: colab_leecher/downlader/ytdl.py

import asyncio
import logging
import threading
import time
from pathlib import Path

from humanize import naturalsize

from media_bot.utility.helper import (
    build_custom_progress_display,
    format_time_hms,
    update_progress,
    write_twitter_cookie_file,
)
from media_bot.utility.variables import Config, Paths

logger = logging.getLogger(__name__)


class _YTDLLogger:
    """Routes yt-dlp's log lines into one download's own state dict."""

    def __init__(self, state):
        self._state = state

    def debug(self, msg):
        if "[ExtractAudio]" in str(msg) or "[ffmpeg]" in str(msg):
            self._state["status"] = "merging"
            self._state["speed"] = "Merging..."
            self._state["eta"] = "..."
        elif "item" in str(msg):
            self._state["status"] = "playlist"
            self._state["speed"] = "Playlist..."
            self._state["eta"] = "..."

    @staticmethod
    def warning(msg):
        logger.warning(f"[yt-dlp] {msg}")

    @staticmethod
    def error(msg):
        if msg != "ERROR: Cancelling...":
            logger.error(f"[yt-dlp] {msg}")


def _make_progress_hook(state):
    """Synchronous progress hook, bound to one download's state.

    yt-dlp calls this from inside the worker thread. Binding the state here
    (instead of a module-level dict) keeps concurrent downloads isolated.
    """

    def _hook(d):
        if d["status"] == "downloading":
            total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded_bytes = d.get("downloaded_bytes", 0)
            state["status"] = "downloading"
            state["total_bytes"] = total_bytes
            state["downloaded_bytes"] = downloaded_bytes
            state["percentage"] = (
                downloaded_bytes / total_bytes * 100 if total_bytes > 0 else 0
            )
            speed = d.get("speed")
            state["speed"] = f"{naturalsize(speed)}/s" if speed else "N/A"
            eta = d.get("eta")
            state["eta"] = format_time_hms(eta) if eta else "N/A"
        elif d["status"] == "finished":
            state["status"] = "merging"
            state["percentage"] = 100
            state["total_bytes"] = d.get("total_bytes") or state.get("downloaded_bytes", 0)

    return _hook


def _ytdl_downloader_thread(url, ydl_opts, state):
    """The synchronous worker executed in the background thread."""
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if state.get("status") != "error":
            state["status"] = "finished"
    except Exception as exc:  # noqa: BLE001
        logger.error(f"YTDL Thread Exception: {exc}")
        state["status"] = "error"
        state["error"] = str(exc)


def _write_cookie_file_if_needed(url, cookies):
    if ("twitter.com" in url or "x.com" in url) and cookies:
        try:
            write_twitter_cookie_file(cookies)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not write twitter cookie file: {exc}")


FORMAT_PRESETS = {
    "best": ("bestvideo+bestaudio/best", "mp4", None),
    "1080": ("bestvideo[height<=1080]+bestaudio/best[height<=1080]", "mp4", None),
    "720": ("bestvideo[height<=720]+bestaudio/best[height<=720]", "mp4", None),
    "480": ("bestvideo[height<=480]+bestaudio/best[height<=480]", "mp4", None),
    "worst": ("worstvideo+worstaudio/worst", "mp4", None),
    "audio": ("bestaudio/best", None, "mp3"),
}


async def download_ytdl(
    url, dest, status_msg, file_index, total_files, user_name, start_time,
    after_date=None, before_date=None, ytdl_format="best", cookies_file=None, resume=True,
):
    """Download from a yt-dlp supported site using a worker thread."""
    from pyrogram.errors import FloodWait, MessageNotModified

    # Per-download state: two concurrent yt-dlp jobs never share it.
    state = {
        "status": "starting",
        "percentage": 0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "speed": "N/A",
        "eta": "N/A",
    }

    fmt, merge_ext, audio_ext = FORMAT_PRESETS.get(ytdl_format, FORMAT_PRESETS["best"])

    ydl_opts = {
        "outtmpl": str(dest / "%(title)s [%(id)s].%(ext)s"),
        "progress_hooks": [_make_progress_hook(state)],
        "logger": _YTDLLogger(state),
        "writethumbnail": True,
        "concurrent_fragment_downloads": 4,
        "overwrites": True,
        "continuedl": bool(resume),
        "writesubtitles": True,
        "subtitleslangs": ["all"],
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "format": fmt,
    }
    if merge_ext:
        ydl_opts["merge_output_format"] = merge_ext
    if audio_ext:
        ydl_opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": audio_ext}
        ]

    cookie_path = cookies_file or Paths.TWITTER_COOKIE_FILE
    _write_cookie_file_if_needed(url, Config.TWITTER_COOKIES)
    if cookie_path and Path(cookie_path).exists():
        ydl_opts["cookiefile"] = str(cookie_path)

    if after_date:
        ydl_opts["dateafter"] = after_date
    if before_date:
        ydl_opts["datebefore"] = before_date

    thread = threading.Thread(
        target=_ytdl_downloader_thread, args=(url, ydl_opts, state), daemon=True
    )
    thread.start()

    while thread.is_alive():
        await asyncio.sleep(2)
        progress_data = {
            "type": "ytdl",
            "percentage": state.get("percentage", 0),
            "downloaded_bytes": state.get("downloaded_bytes", 0),
            "total_size_str": naturalsize(state.get("total_bytes", 0)),
            "speed": state.get("speed", "N/A"),
            "eta": state.get("eta", "N/A"),
        }
        display = build_custom_progress_display(
            url, progress_data, file_index, total_files, user_name, start_time
        )
        try:
            if status_msg:
                await status_msg.edit_text(display)
        except (MessageNotModified, FloodWait):
            pass

    if state.get("status") in ("finished", "merging"):
        logger.info(f"YTDL: Download complete for {url}")
        total = state.get("total_bytes", 0)
        await update_progress(
            status_msg, url, file_index, total_files, user_name, start_time,
            total, total, "Done", "Done", dl_type="ytdl",
        )
        return True, "YTDL Download Complete", ""
    logger.error(f"YTDL: Thread failed: {state.get('error')}")
    return False, "", state.get("error", "YTDL thread failed")
