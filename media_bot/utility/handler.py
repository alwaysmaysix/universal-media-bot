# Message / logging side-effects shared by the bot handlers.
#
# Reference analogue: colab_leecher/utility/handler.py (message cleanup,
# dump-channel logging and the small "task" side effects).

import asyncio
import logging
from datetime import datetime

from pyrogram.types import LinkPreviewOptions

from media_bot.utility.variables import Config

logger = logging.getLogger(__name__)


async def delete_message_after_delay(message, delay: int):
    """Delete a message after a given delay (no-op when delay <= 0)."""
    if not message or delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass


async def log_to_dump_channel(client, user_message, urls):
    """Log every processed URL to the dump channel."""
    if Config.DUMP_CHANNEL_ID == 0:
        return
    user = user_message.from_user
    username = f"@{user.username}" if user.username else "None"
    log_text = f"User: {user.first_name} ({username} | `{user.id}`)\n"
    log_text += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    log_text += f"URLs ({len(urls)}):\n" + "\n".join(urls)
    try:
        await client.send_message(
            Config.DUMP_CHANNEL_ID,
            log_text,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Failed to log to dump channel: {exc}")


async def safe_edit(message, text, **kwargs):
    """edit_text() that swallows the two noisy Pyrogram exceptions."""
    from pyrogram.errors import FloodWait, MessageNotModified

    if not message:
        return
    try:
        await message.edit_text(text, **kwargs)
    except (MessageNotModified, FloodWait):
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Could not edit status message: {exc}")
