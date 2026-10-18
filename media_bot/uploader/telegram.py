# Telegram upload helpers.
#
# Reference analogue: colab_leecher/uploader/telegram.py

import asyncio
import logging
import time
from pathlib import Path

from humanize import naturalsize
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import InputMediaPhoto

from media_bot.utility.helper import (
    baddiehub_caption,
    build_upload_progress_display,
    format_caption,
    generate_thumbnail,
    progress_due,
)
from media_bot.utility.variables import Config

logger = logging.getLogger(__name__)

IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]
VIDEO_EXTS = [".mp4", ".mkv", ".webm", ".avi", ".mov"]


async def progress_cb(current, total, msg, start_time, filename, user_name="User"):
    """Upload progress callback for Pyrogram (same layout as downloads)."""
    if not msg:
        return
    if not progress_due(msg, 3.0):
        return

    now = time.time()
    elapsed = now - start_time
    speed = current / elapsed if elapsed > 0 else 0
    eta = (total - current) / speed if speed > 0 else 0

    progress_data = {
        "percentage": (current * 100 / total) if total else 0,
        "downloaded_bytes": current,
        "total_size_str": naturalsize(total),
        "speed": f"{naturalsize(speed)}/s",
        "eta": time.strftime("%M:%S", time.gmtime(eta)),
        "elapsed": elapsed,
    }
    text = build_upload_progress_display(filename, progress_data, user_name)

    try:
        await msg.edit_text(text)
    except FloodWait as exc:
        logger.debug(f"FloodWait {exc.value}s on progress update, skipping...")
    except MessageNotModified:
        pass


async def upload_to_telegram(
    client,
    file_chat_id,
    file_path,
    caption=None,
    max_retries=3,
    progress_chat_id=None,
    as_document=False,
    thumb_override=None,
    user_name="User",
):
    """Upload a single file, choosing video / photo / document based on the suffix.

    When `as_document` is True the file is always sent as a document (used for
    archives produced by the zip/unzip action). `thumb_override` replaces the
    auto-generated video thumbnail with the user's own.
    """
    file_path_p = Path(file_path)
    filename = file_path_p.name
    target_chat_id = progress_chat_id if progress_chat_id else file_chat_id

    progress_msg = None
    for attempt in range(max_retries):
        try:
            progress_msg = await client.send_message(target_chat_id, f"⏳ Preparing: `{filename[:40]}`...")
            break
        except FloodWait as exc:
            if attempt < max_retries - 1:
                logger.warning(f"FloodWait {exc.value}s on progress msg, waiting...")
                await asyncio.sleep(exc.value)
            else:
                logger.error(f"Failed to send progress message after {max_retries} attempts")
                return False

    try:
        file_size = file_path_p.stat().st_size
        ext = file_path_p.suffix.lower()

        if ext == ".m4v":
            new_path = file_path_p.with_suffix(".mp4")
            file_path_p.rename(new_path)
            file_path_p = new_path
            ext = new_path.suffix.lower()
            file_path = str(new_path)

        cap = caption or f"{filename}\n💾 {naturalsize(file_size)}"

        for attempt in range(max_retries):
            try:
                if not as_document and ext in VIDEO_EXTS:
                    gen_thumb, duration, width, height = generate_thumbnail(file_path)
                    thumb = (
                        thumb_override
                        if (thumb_override and Path(thumb_override).exists())
                        else gen_thumb
                    )
                    await client.send_video(
                        file_chat_id, file_path, caption=cap, thumb=thumb,
                        duration=duration or None, width=width or None, height=height or None,
                        supports_streaming=True, progress=progress_cb,
                        progress_args=(progress_msg, time.time(), filename, user_name),
                    )
                    if gen_thumb and gen_thumb != thumb and Path(gen_thumb).exists():
                        Path(gen_thumb).unlink()
                elif not as_document and ext in IMAGE_EXTS:
                    await client.send_photo(
                        file_chat_id, file_path, caption=cap, progress=progress_cb,
                        progress_args=(progress_msg, time.time(), filename, user_name),
                    )
                else:
                    await client.send_document(
                        file_chat_id, file_path, caption=cap, progress=progress_cb,
                        progress_args=(progress_msg, time.time(), filename, user_name),
                    )
                break
            except FloodWait as exc:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"FloodWait {exc.value}s during upload (attempt {attempt + 1}/{max_retries}), waiting..."
                    )
                    await asyncio.sleep(exc.value)
                else:
                    logger.error(f"Upload failed after {max_retries} attempts due to FloodWait")
                    if progress_msg:
                        try:
                            await progress_msg.edit_text("❌ Upload failed: Too many flood waits")
                        except MessageNotModified:
                            pass
                    return False

        if progress_msg:
            try:
                await progress_msg.delete()
            except Exception:  # noqa: BLE001
                pass
        return True

    except FloodWait as exc:
        logger.warning(f"FloodWait: {exc.value}s")
        await asyncio.sleep(exc.value)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Upload error: {exc}")
        if progress_msg:
            try:
                await progress_msg.edit_text(f"❌ Upload failed: {str(exc)[:100]}")
            except MessageNotModified:
                pass
        return False


async def upload_file_with_album(
    client,
    file_chat_id,
    files,
    caption_template=None,
    max_retries=3,
    progress_chat_id=None,
    baddiehub_titles=None,
    as_document=False,
    prefs=None,
    user_name="User",
):
    """Upload a batch of files, grouping consecutive images into media albums.

    `as_document=True` sends everything as documents and disables albums (used
    for archive output). `prefs` supplies prefix / suffix / caption font and the
    per-user thumbnail.
    """
    files = [Path(f) for f in files]
    if as_document:
        images, videos, others = [], [], list(files)
    else:
        images = [f for f in files if f.suffix.lower() in IMAGE_EXTS]
        videos = [f for f in files if f.suffix.lower() in VIDEO_EXTS]
        others = [f for f in files if f not in images and f not in videos]
    uploaded = 0

    prefix = getattr(prefs, "prefix", "") or ""
    suffix = getattr(prefs, "suffix", "") or ""
    font = getattr(prefs, "caption_font", "default") or "default"
    thumb_override = getattr(prefs, "thumbnail", None)

    def make_caption(path, index):
        return format_caption(
            caption_template, path.name, path.stat().st_size, index, len(files),
            prefix=prefix, suffix=suffix, font=font,
        )

    def title_caption():
        if not baddiehub_titles:
            return None
        return baddiehub_caption(next(iter(baddiehub_titles.values()), None))

    def image_caption(img_path, index):
        if caption_template is None and baddiehub_titles:
            return title_caption() or make_caption(img_path, index)
        return make_caption(img_path, index)

    def file_caption(path, index):
        if caption_template is None and baddiehub_titles:
            return title_caption() or make_caption(path, index)
        return make_caption(path, index)

    if Config.SEND_AS_ALBUM and len(images) > 1:
        for i in range(0, len(images), Config.ALBUM_SIZE):
            batch = images[i:i + Config.ALBUM_SIZE]
            media_group = []
            for idx, img in enumerate(batch):
                cap = image_caption(img, i + idx + 1) if idx == 0 else ""
                media_group.append(InputMediaPhoto(str(img), caption=cap))
            for attempt in range(max_retries):
                try:
                    await client.send_media_group(file_chat_id, media_group)
                    uploaded += len(batch)
                    await asyncio.sleep(Config.DELAY_BETWEEN_FILES)
                    break
                except FloodWait as exc:
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"FloodWait {exc.value}s on album (attempt {attempt + 1}/{max_retries}), waiting..."
                        )
                        await asyncio.sleep(exc.value)
                    else:
                        logger.error(f"Album upload failed after {max_retries} attempts")
                except Exception as exc:  # noqa: BLE001
                    logger.error(f"Album upload error: {exc}")
                    break
    else:
        for idx, img in enumerate(images, 1):
            if await upload_to_telegram(
                client, file_chat_id, str(img), image_caption(img, idx),
                progress_chat_id=progress_chat_id, as_document=as_document,
                thumb_override=thumb_override, user_name=user_name,
            ):
                uploaded += 1
            await asyncio.sleep(Config.DELAY_BETWEEN_FILES)

    for idx, video in enumerate(videos, len(images) + 1):
        if await upload_to_telegram(
            client, file_chat_id, str(video), file_caption(video, idx),
            progress_chat_id=progress_chat_id, as_document=as_document,
            thumb_override=thumb_override, user_name=user_name,
        ):
            uploaded += 1
        await asyncio.sleep(Config.DELAY_BETWEEN_FILES)

    for idx, other in enumerate(others, len(images) + len(videos) + 1):
        if await upload_to_telegram(
            client, file_chat_id, str(other), file_caption(other, idx),
            progress_chat_id=progress_chat_id, as_document=as_document,
            thumb_override=thumb_override, user_name=user_name,
        ):
            uploaded += 1
        await asyncio.sleep(Config.DELAY_BETWEEN_FILES)

    return uploaded
