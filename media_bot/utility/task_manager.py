# Task orchestration - reference analogue: colab_leecher/utility/task_manager.py
#
# downloadManager() lives in downlader/manager.py and owns the per-URL loop;
# process_urls() here owns the full request lifecycle:
# download -> collect files -> upload -> summarise -> cleanup.

import asyncio
import logging
import shutil
import time

from media_bot.downlader.manager import downloadManager
from media_bot.uploader.telegram import upload_file_with_album
from media_bot.utility.handler import delete_message_after_delay, safe_edit
from media_bot.utility.variables import Config, Paths, Stats, user_states

logger = logging.getLogger(__name__)


async def process_urls(client, message, chat_id, urls, status_msg=None):
    """Download every URL, then upload the resulting files."""
    state = user_states.get(chat_id, {})
    dest = Paths.DOWN_PATH / f"dl_{chat_id}_{int(time.time())}"
    dest.mkdir(parents=True, exist_ok=True)
    user_name = message.from_user.first_name or "User"

    if status_msg is None:
        status_msg = await message.reply(f"🚀 Processing {len(urls)} URL(s)...")

    failed_urls, baddiehub_titles = await downloadManager(
        urls,
        dest,
        status_msg=status_msg,
        after_date=state.get("after_date"),
        before_date=state.get("before_date"),
        user_name=user_name,
        message=message,
    )

    max_bytes = Config.MAX_FILE_SIZE_MB * 1024 * 1024
    all_files = [
        fpath
        for fpath in dest.rglob("*")
        if fpath.is_file() and fpath.stat().st_size <= max_bytes
    ]

    if not all_files:
        await _handle_no_files(status_msg, dest, failed_urls, state, chat_id)
        return

    file_info = f"📊 Found {len(all_files)} file(s)"
    upload_location_info = (
        "to Dump Channel" if Config.DUMP_CHANNEL_ID != 0 else "to Telegram"
    )
    await safe_edit(
        status_msg, f"{file_info}\n📤 Uploading files {upload_location_info}..."
    )

    caption_template = state.get("custom_caption")
    upload_destination_id = Config.DUMP_CHANNEL_ID or chat_id
    uploaded = await upload_file_with_album(
        client,
        upload_destination_id,
        all_files,
        caption_template,
        max_retries=3,
        progress_chat_id=chat_id,
        baddiehub_titles=baddiehub_titles,
    )

    summary = (
        f"✅ **Complete**\n\n"
        f"📥 URLs: {len(urls)}\n"
        f"📁 Files: {len(all_files)}\n"
        f"📤 Uploaded: {uploaded}"
    )
    if failed_urls:
        summary += f"\n❌ Failed: {len(failed_urls)}"
    await safe_edit(status_msg, summary)

    asyncio.create_task(delete_message_after_delay(status_msg, Config.MESSAGE_DELETE_DELAY))
    _cleanup(dest)

    Stats.downloads += len(urls) - len(failed_urls)
    Stats.uploads += uploaded
    Stats.failed += len(failed_urls)
    Stats.total_files += len(all_files)

    user_states.pop(chat_id, None)


async def _handle_no_files(status_msg, dest, failed_urls, state, chat_id):
    no_file_msg = "⚠️ No files downloaded."
    if failed_urls:
        no_file_msg += f"\n\n{len(failed_urls)} URL(s) failed."
    if state.get("after_date") or state.get("before_date"):
        no_file_msg += "\n\n💡 No content in date range or site doesn't support filtering."
    await safe_edit(status_msg, no_file_msg)
    asyncio.create_task(delete_message_after_delay(status_msg, Config.MESSAGE_DELETE_DELAY))
    _cleanup(dest)
    user_states.pop(chat_id, None)


def _cleanup(dest):
    if Config.AUTO_CLEANUP:
        try:
            shutil.rmtree(dest, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Cleanup error: {exc}")
