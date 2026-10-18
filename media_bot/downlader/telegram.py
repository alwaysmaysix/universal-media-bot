# Telegram downloader - fetches media from a public t.me link.
#
# Reference analogue: colab_leecher/downlader/telegram.py

import logging
import time
from pathlib import Path

from humanize import naturalsize

from media_bot import bot
from media_bot.utility.helper import format_time_hms, update_progress

logger = logging.getLogger(__name__)


def _resolve_chat_id(chat_id_str: str):
    if chat_id_str.startswith("-100"):
        try:
            return int(chat_id_str)
        except ValueError:
            return chat_id_str
    return chat_id_str


async def download_telegram(url, dest, status_msg, file_index, total_files, user_name, start_time):
    """Download the media attached to a public Telegram message."""
    try:
        parts = url.split("/")
        if len(parts) < 2:
            return False, "", "Invalid Telegram URL"
        chat_id_str = parts[-2]
        message_id = int(parts[-1].split("?")[0])

        try:
            chat_id = await bot.get_chat(chat_id_str)
            chat_id = chat_id.id
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"Could not resolve {chat_id_str} as username, trying as channel ID: {exc}"
            )
            chat_id = _resolve_chat_id(chat_id_str)

        message = await bot.get_messages(chat_id, message_id)
        if not (message.video or message.document or message.photo or message.audio):
            return False, "", "Telegram message has no downloadable media"

        async def tg_progress_callback(current, total):
            elapsed = time.time() - start_time
            speed = current / elapsed if elapsed > 0 else 0
            eta_sec = (total - current) / speed if speed > 0 else 0
            await update_progress(
                status_msg, url, file_index, total_files, user_name, start_time,
                current, total, f"{naturalsize(speed)}/s", format_time_hms(eta_sec),
                dl_type="telegram",
            )

        logger.info(f"Telegram: Starting download for message {message_id}")
        filepath = await message.download(
            file_name=str(dest / ""), progress=tg_progress_callback
        )
        logger.info(f"Telegram: Download complete: {filepath}")
        return True, f"Downloaded from TG: {Path(filepath).name}", ""
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Telegram download error: {exc}")
        return False, "", f"Telegram Error: {exc}"
