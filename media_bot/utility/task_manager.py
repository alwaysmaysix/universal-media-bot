# Task orchestration - reference analogue: colab_leecher/utility/task_manager.py
#
# process_urls() owns the full request lifecycle:
# guard quota -> download -> archive/split -> upload -> history -> cleanup.
#
# Downloads run as background asyncio tasks so /cancel can kill them.

import asyncio
import logging
import shutil
import time
from pathlib import Path

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from media_bot.downlader.manager import downloadManager
from media_bot.uploader.telegram import upload_file_with_album
from media_bot.utility import runtime, store
from media_bot.utility.converters import is_video, split_video, unzip_handler, zip_handler
from media_bot.utility.handler import delete_message_after_delay, safe_edit
from media_bot.utility.helper import build_user_cookie_file
from media_bot.utility.variables import Config, Paths, Stats, get_prefs, user_states

logger = logging.getLogger(__name__)

STATUS_LABELS = {
    "zip": "🗜 Compressing files...",
    "unzip": "📂 Extracting archives...",
    "undzip": "🔁 Extracting then re-compressing...",
}


def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✘ Cancel", callback_data="task:cancel")]])


def _archive_name(dest: Path) -> str:
    entries = list(dest.iterdir())
    if len(entries) == 1 and entries[0].is_file():
        return entries[0].stem
    return "media_bot_archive"


def quota_block(chat_id):
    """Return a message when the user is over quota, else None."""
    if not Config.QUOTA_FILES_PER_DAY and not Config.QUOTA_GB_PER_DAY:
        return None
    quota = store.get_quota(chat_id)
    if Config.QUOTA_FILES_PER_DAY and quota.get("files", 0) >= Config.QUOTA_FILES_PER_DAY:
        return (
            f"🚫 Daily quota reached: {quota['files']}/{Config.QUOTA_FILES_PER_DAY} files.\n"
            "Try again tomorrow."
        )
    if Config.QUOTA_GB_PER_DAY and quota.get("bytes", 0) >= Config.QUOTA_GB_PER_DAY * 1024**3:
        used = quota["bytes"] / 1024**3
        return f"🚫 Daily quota reached: {used:.1f}/{Config.QUOTA_GB_PER_DAY} GB.\nTry again tomorrow."
    return None


def _all_work_dirs(dest: Path):
    return [
        dest,
        Paths.DOWN_PATH / f"zip_{dest.name}",
        Paths.DOWN_PATH / f"unzip_{dest.name}",
        Paths.DOWN_PATH / f"split_{dest.name}",
    ]


async def start_task(client, message, chat_id, urls, status_msg=None, user_name=None):
    """Launch process_urls() as a tracked background task."""
    dest = Paths.DOWN_PATH / f"dl_{chat_id}_{int(time.time())}"
    dest.mkdir(parents=True, exist_ok=True)

    token = runtime.set_chat(chat_id)
    try:
        task = asyncio.create_task(
            process_urls(
                client, message, chat_id, urls,
                status_msg=status_msg, dest=dest, user_name=user_name,
            )
        )
    finally:
        runtime.reset_chat(token)

    runtime.register_task(chat_id, task)

    def _done(finished):
        runtime.remove_task(chat_id, finished)
        if finished.cancelled():
            runtime.kill_chat_processes(chat_id)
            _cleanup(_all_work_dirs(dest))

    task.add_done_callback(_done)
    return task


async def _apply_archive_action(prefs, dest: Path, work_dirs):
    """Apply the user's zip/unzip choice; returns the files that should upload."""
    action = prefs.action
    chunk = f"{Config.SPLIT_SIZE_MB}m"

    if action == "zip":
        out = Paths.DOWN_PATH / f"zip_{dest.name}"
        work_dirs.append(out)
        return await zip_handler(
            dest, out, is_split=prefs.is_split, password=prefs.zip_password,
            name=_archive_name(dest), chunk=chunk,
        )

    if action == "unzip":
        out = Paths.DOWN_PATH / f"unzip_{dest.name}"
        work_dirs.append(out)
        return await unzip_handler(dest, out, password=prefs.unzip_password)

    if action == "undzip":
        mid = Paths.DOWN_PATH / f"unzip_{dest.name}"
        out = Paths.DOWN_PATH / f"zip_{dest.name}"
        work_dirs.extend([mid, out])
        await unzip_handler(dest, mid, password=prefs.unzip_password)
        return await zip_handler(
            mid, out, is_split=prefs.is_split, password=prefs.zip_password,
            name=_archive_name(dest), chunk=chunk,
        )

    return [p for p in dest.rglob("*") if p.is_file()]


async def process_urls(client, message, chat_id, urls, status_msg=None, dest=None, user_name=None):
    """Download every URL, optionally archive/split, then upload the results."""
    prefs = get_prefs(chat_id)
    if dest is None:
        dest = Paths.DOWN_PATH / f"dl_{chat_id}_{int(time.time())}"
        dest.mkdir(parents=True, exist_ok=True)
    if user_name is None:
        user_name = (message.from_user.first_name if message.from_user else None) or "User"
    work_dirs = [dest]
    max_bytes = Config.MAX_FILE_SIZE_MB * 1024 * 1024

    blocked = quota_block(chat_id)
    if blocked:
        if status_msg is None:
            status_msg = await message.reply(blocked)
        else:
            await safe_edit(status_msg, blocked)
        asyncio.create_task(delete_message_after_delay(status_msg, Config.MESSAGE_DELETE_DELAY))
        _cleanup(work_dirs)
        user_states.pop(chat_id, None)
        return

    if status_msg is None:
        status_msg = await message.reply(
            f"🚀 Processing {len(urls)} URL(s)...", reply_markup=cancel_keyboard()
        )
    else:
        await safe_edit(status_msg, f"🚀 Processing {len(urls)} URL(s)...", reply_markup=cancel_keyboard())

    cookies_file = build_user_cookie_file(chat_id)
    engine = prefs.engine
    manual_magnet = url_is_magnet_only(urls)

    failed_urls, baddiehub_titles = await downloadManager(
        urls,
        dest,
        status_msg=status_msg,
        after_date=prefs.after_date,
        before_date=prefs.before_date,
        user_name=user_name,
        message=message,
        engine=engine,
        fallback=prefs.fallback,
        cookies_file=cookies_file,
        ytdl_format=prefs.ytdl_format,
        resume=Config.RESUME,
        torrent_files=prefs.torrent_files,
        size_limit=0 if (prefs.action != "normal" or manual_magnet) else max_bytes,
    )

    raw_files = [p for p in dest.rglob("*") if p.is_file()]
    if not raw_files and not failed_urls:
        await _finish_no_files(status_msg, work_dirs, failed_urls, prefs, chat_id)
        return

    # ---- archive action ----
    if prefs.action in STATUS_LABELS and raw_files:
        await safe_edit(status_msg, STATUS_LABELS[prefs.action], reply_markup=cancel_keyboard())
        try:
            produced = await _apply_archive_action(prefs, dest, work_dirs)
            if produced:
                raw_files = produced
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Archive action '{prefs.action}' failed: {exc}")
            await safe_edit(status_msg, f"⚠️ Archive step failed: {exc}\nUploading originals...")

    # ---- split oversized videos ----
    if prefs.split_video and prefs.action == "normal":
        split_dir = Paths.DOWN_PATH / f"split_{dest.name}"
        split_any = False
        new_files = []
        for fpath in raw_files:
            if is_video(fpath) and fpath.stat().st_size > max_bytes:
                work_dirs.append(split_dir)
                parts = await split_video(fpath, max_bytes, split_dir)
                if parts:
                    new_files.extend(parts)
                    split_any = True
                    continue
            new_files.append(fpath)
        if split_any:
            await safe_edit(status_msg, "✂️ Split oversized video(s).", reply_markup=cancel_keyboard())
        raw_files = new_files

    # ---- enforce the upload size limit on the final list ----
    all_files = [p for p in raw_files if p.exists() and p.stat().st_size <= max_bytes]

    if not all_files:
        await _finish_no_files(status_msg, work_dirs, failed_urls, prefs, chat_id)
        return

    as_document = (not prefs.stream_upload) or prefs.action != "normal"
    destination = prefs.destination or Config.DUMP_CHANNEL_ID or chat_id

    await safe_edit(
        status_msg,
        f"📊 Found {len(all_files)} file(s)\n📤 Uploading to Telegram...",
        reply_markup=cancel_keyboard(),
    )

    try:
        uploaded = await upload_file_with_album(
            client,
            destination,
            all_files,
            prefs.custom_caption,
            max_retries=3,
            progress_chat_id=chat_id,
            baddiehub_titles=baddiehub_titles,
            as_document=as_document,
            prefs=prefs,
        )
    except asyncio.CancelledError:
        raise

    total_bytes = sum(p.stat().st_size for p in all_files if p.exists())
    summary = (
        f"✅ **Complete**\n\n"
        f"📥 URLs: {len(urls)}\n"
        f"📁 Files: {len(all_files)}\n"
        f"📤 Uploaded: {uploaded}"
    )
    if prefs.action in STATUS_LABELS:
        summary += f"\n🗜 Action: {prefs.action}"
    if failed_urls:
        summary += f"\n❌ Failed: {len(failed_urls)}"
    await safe_edit(status_msg, summary, reply_markup=None)

    asyncio.create_task(delete_message_after_delay(status_msg, Config.MESSAGE_DELETE_DELAY))
    _cleanup(work_dirs)

    Stats.downloads += len(urls) - len(failed_urls)
    Stats.uploads += uploaded
    Stats.failed += len(failed_urls)
    Stats.total_files += len(all_files)

    try:
        store.bump_stats(
            0,
            downloads=len(urls) - len(failed_urls),
            uploads=uploaded,
            failed=len(failed_urls),
            total_files=len(all_files),
            bytes_=total_bytes,
        )
        store.bump_stats(
            chat_id,
            downloads=len(urls) - len(failed_urls),
            uploads=uploaded,
            failed=len(failed_urls),
            total_files=len(all_files),
            bytes_=total_bytes,
        )
        store.bump_quota(chat_id, files=len(all_files), bytes_=total_bytes)
        store.add_history(
            chat_id, urls, engine, prefs.action, len(all_files), uploaded,
            "failed" if failed_urls else "ok",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not persist stats/history: {exc}")

    user_states.pop(chat_id, None)


def url_is_magnet_only(urls):
    return bool(urls) and all(str(u).startswith("magnet:?") for u in urls)


async def _finish_no_files(status_msg, work_dirs, failed_urls, prefs, chat_id):
    message = "⚠️ No files downloaded."
    if failed_urls:
        message += f"\n\n{len(failed_urls)} URL(s) failed."
        for url, err in failed_urls[:3]:
            message += f"\n• `{url[:45]}` — {err[:80]}"
    if prefs.after_date or prefs.before_date:
        message += "\n\n💡 No content in date range or site doesn't support filtering."
    if prefs.action in ("unzip", "undzip"):
        message += "\n\n💡 No extractable archives were found."
    await safe_edit(status_msg, message, reply_markup=None)
    asyncio.create_task(delete_message_after_delay(status_msg, Config.MESSAGE_DELETE_DELAY))
    _cleanup(work_dirs)
    try:
        store.add_history(chat_id, [], prefs.engine, prefs.action, 0, 0, "empty")
    except Exception:  # noqa: BLE001
        pass
    user_states.pop(chat_id, None)


def _cleanup(work_dirs):
    if not Config.AUTO_CLEANUP:
        return
    for directory in work_dirs:
        try:
            shutil.rmtree(directory, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Cleanup error for {directory}: {exc}")
