# yt-dlp downloader (YouTube, Twitter/X and ~1800 other sites).
#
# yt-dlp is synchronous, so it runs in a worker thread while this coroutine
# polls a shared state dict and refreshes the status message.
# Reference analogue: colab_leecher/downlader/ytdl.py

import asyncio
import logging
import threading
import time

from humanize import naturalsize

from media_bot.utility.helper import (
    build_custom_progress_display,
    format_time_hms,
    update_progress,
    write_twitter_cookie_file,
)
from media_bot.utility.variables import Config, Paths

logger = logging.getLogger(__name__)

_YTDL_STATE: dict = {}
_YTDL_THREAD: threading.Thread | None = None


class _YTDLLogger:
    def debug(self, msg):
        if "[ExtractAudio]" in str(msg) or "[ffmpeg]" in str(msg):
            _YTDL_STATE["status"] = "merging"
            _YTDL_STATE["speed"] = "Merging..."
            _YTDL_STATE["eta"] = "..."
        elif "item" in str(msg):
            _YTDL_STATE["status"] = "playlist"
            _YTDL_STATE["speed"] = "Playlist..."
            _YTDL_STATE["eta"] = "..."

    @staticmethod
    def warning(msg):
        logger.warning(f"[yt-dlp] {msg}")

    @staticmethod
    def error(msg):
        if msg != "ERROR: Cancelling...":
            logger.error(f"[yt-dlp] {msg}")


def _ytdl_progress_hook(d):
    """Synchronous progress hook called by yt-dlp inside the worker thread."""
    if d["status"] == "downloading":
        total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
        downloaded_bytes = d.get("downloaded_bytes", 0)
        _YTDL_STATE["status"] = "downloading"
        _YTDL_STATE["total_bytes"] = total_bytes
        _YTDL_STATE["downloaded_bytes"] = downloaded_bytes
        _YTDL_STATE["percentage"] = (
            downloaded_bytes / total_bytes * 100 if total_bytes > 0 else 0
        )
        speed = d.get("speed")
        _YTDL_STATE["speed"] = f"{naturalsize(speed)}/s" if speed else "N/A"
        eta = d.get("eta")
        _YTDL_STATE["eta"] = format_time_hms(eta) if eta else "N/A"
    elif d["status"] == "finished":
        _YTDL_STATE["status"] = "merging"
        _YTDL_STATE["percentage"] = 100
        _YTDL_STATE["total_bytes"] = d.get("total_bytes", d.get("downloaded_bytes", 0))
    elif d["status"] == "error":
        _YTDL_STATE["status"] = "error"
        _YTDL_STATE["error"] = d.get("message", "Unknown YTDL error")


def _ytdl_downloader_thread(url, ydl_opts):
    """The synchronous worker executed in the background thread."""
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if _YTDL_STATE.get("status") != "error":
            _YTDL_STATE["status"] = "finished"
    except Exception as exc:  # noqa: BLE001
        logger.error(f"YTDL Thread Exception: {exc}")
        _YTDL_STATE["status"] = "error"
        _YTDL_STATE["error"] = str(exc)


def _write_cookie_file_if_needed(url, cookies):
    if ("twitter.com" in url or "x.com" in url) and cookies:
        try:
            write_twitter_cookie_file(cookies)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not write twitter cookie file: {exc}")


async def download_ytdl(
    url, dest, status_msg, file_index, total_files, user_name, start_time,
    after_date=None, before_date=None,
):
    """Download from a yt-dlp supported site using a worker thread."""
    from pyrogram.errors import FloodWait, MessageNotModified

    global _YTDL_THREAD

    _YTDL_STATE.clear()
    _YTDL_STATE.update(
        {"status": "starting", "percentage": 0, "downloaded_bytes": 0,
         "total_bytes": 0, "speed": "N/A", "eta": "N/A"}
    )

    ydl_opts = {
        "outtmpl": str(dest / "%(title)s [%(id)s].%(ext)s"),
        "progress_hooks": [_ytdl_progress_hook],
        "logger": _YTDLLogger(),
        "cookiefile": str(Paths.TWITTER_COOKIE_FILE),
        "writethumbnail": True,
        "concurrent_fragment_downloads": 4,
        "overwrites": True,
        "writesubtitles": True,
        "subtitleslangs": ["all"],
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "merge_output_format": "mp4",
    }
    if after_date:
        ydl_opts["dateafter"] = after_date
    if before_date:
        ydl_opts["datebefore"] = before_date

    _write_cookie_file_if_needed(url, Config.TWITTER_COOKIES)

    _YTDL_THREAD = threading.Thread(
        target=_ytdl_downloader_thread, args=(url, ydl_opts), daemon=True
    )
    _YTDL_THREAD.start()

    while _YTDL_THREAD.is_alive():
        await asyncio.sleep(2)
        progress_data = {
            "type": "ytdl",
            "percentage": _YTDL_STATE.get("percentage", 0),
            "downloaded_bytes": _YTDL_STATE.get("downloaded_bytes", 0),
            "total_size_str": naturalsize(_YTDL_STATE.get("total_bytes", 0)),
            "speed": _YTDL_STATE.get("speed", "N/A"),
            "eta": _YTDL_STATE.get("eta", "N/A"),
        }
        display = build_custom_progress_display(
            url, progress_data, file_index, total_files, user_name, start_time
        )
        try:
            if status_msg:
                await status_msg.edit_text(display)
        except (MessageNotModified, FloodWait):
            pass

    if _YTDL_STATE.get("status") in ("finished", "merging"):
        logger.info(f"YTDL: Download complete for {url}")
        total = _YTDL_STATE.get("total_bytes", 0)
        await update_progress(
            status_msg, url, file_index, total_files, user_name, start_time,
            total, total, "Done", "Done", dl_type="ytdl",
        )
        return True, "YTDL Download Complete", ""
    logger.error(f"YTDL: Thread failed: {_YTDL_STATE.get('error')}")
    return False, "", _YTDL_STATE.get("error", "YTDL thread failed")
