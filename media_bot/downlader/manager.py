# Master dispatcher.
#
# Reference analogue: colab_leecher/downlader/manager.py - it inspects each link
# and routes it to the correct specialised downloader, falling back to the
# general-purpose engines.

import asyncio
import logging
import time
from urllib.parse import urlparse

from media_bot.downlader.baddiehub import download_baddiehub
from media_bot.downlader.cyberdrop import download_cyberdrop
from media_bot.downlader.gallerydl import download_gallery_dl
from media_bot.downlader.gdrive import download_gdrive
from media_bot.downlader.m3u8 import download_m3u8
from media_bot.downlader.magnet import download_magnet
from media_bot.downlader.mega import download_mega
from media_bot.downlader.telegram import download_telegram
from media_bot.downlader.terabox import download_terabox_resolver
from media_bot.downlader.ytdl import download_ytdl
from media_bot.utility.handler import safe_edit

logger = logging.getLogger(__name__)

YTDL_HOSTS = ("youtube.com", "youtu.be", "x.com", "twitter.com")


async def download_media(
    url,
    dest,
    after_date=None,
    before_date=None,
    status_msg=None,
    file_index=1,
    total_files=1,
    user_name="User",
    start_time=0,
):
    """Route a single URL to the right downloader.

    Returns a (success, stdout, stderr) tuple, matching the notebook contract.
    """
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()

        if "baddiehub.com" in netloc:
            await safe_edit(
                status_msg,
                f"⏳ [{file_index}/{total_files}] Downloading (BaddieHub)...\n🔗 {url[:50]}...",
            )
            await download_baddiehub(url, dest)
            return True, "BaddieHub download complete", ""

        if "drive.google.com" in url:
            return await download_gdrive(url, dest, status_msg, file_index, total_files, user_name, start_time)

        if "t.me/" in url:
            return await download_telegram(url, dest, status_msg, file_index, total_files, user_name, start_time)

        if any(host in url for host in YTDL_HOSTS):
            return await download_ytdl(
                url, dest, status_msg, file_index, total_files, user_name, start_time,
                after_date, before_date,
            )

        if url.startswith("magnet:?"):
            return await download_magnet(url, dest, status_msg, file_index, total_files, user_name, start_time)

        if "mega.nz" in url:
            return await download_mega(url, dest, status_msg, file_index, total_files, user_name, start_time)

        if "terabox.com" in url or "teraboxapp.com" in url:
            return await download_terabox_resolver(url, dest, status_msg, file_index, total_files, user_name, start_time)

        if ".m3u8" in url.lower():
            return await download_m3u8(url, dest, status_msg, file_index, total_files, user_name, start_time)

        # ---- generic fallbacks: gallery-dl, then cyberdrop-dl ----
        await safe_edit(
            status_msg,
            f"⏳ [{file_index}/{total_files}] Trying gallery-dl...\n🔗 {url[:50]}...",
        )
        success, stdout, stderr = await download_gallery_dl(
            url, dest, after_date, before_date, status_msg, file_index, total_files, user_name, start_time
        )
        if success:
            return True, stdout, stderr

        logger.warning("Gallery-dl failed, trying cyberdrop-dl")
        await safe_edit(
            status_msg,
            f"⏳ [{file_index}/{total_files}] Trying cyberdrop-dl...\n🔗 {url[:50]}...",
        )
        success, stdout, stderr = await download_cyberdrop(
            url, dest, status_msg, file_index, total_files, user_name, start_time
        )
        if success:
            return True, stdout, stderr

        raise Exception(f"All downloaders failed for {url}")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Download error for {url}: {exc}")
        return False, "", str(exc)


async def downloadManager(
    source,
    dest,
    status_msg=None,
    after_date=None,
    before_date=None,
    user_name="User",
    message=None,
):
    """Loop over every source URL and dispatch it. Returns (failed, titles)."""
    failed_urls = []
    baddiehub_titles = {}

    for idx, url in enumerate(source, 1):
        start_time = time.time()
        try:
            if "baddiehub.com" in url.lower():
                await safe_edit(
                    status_msg,
                    f"⏳ [{idx}/{len(source)}] Downloading (BaddieHub)...\n🔗 {url[:50]}...",
                )
                success, title_map = await download_baddiehub(url, dest)
                if success:
                    baddiehub_titles.update(title_map)
                else:
                    raise Exception("BaddieHub download failed")
            else:
                success, _stdout, stderr = await download_media(
                    url, dest, after_date, before_date, status_msg, idx, len(source), user_name, start_time
                )
                if not success:
                    raise Exception(stderr or "Download function returned False")
            await safe_edit(
                status_msg,
                f"✅ [{idx}/{len(source)}] Download Complete. Processing files...",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Download error {url}: {exc}")
            failed_urls.append((url, str(exc)))
            if message is not None:
                text = str(exc)
                try:
                    if "Login with username & password" in text:
                        await message.reply("⚠️ Twitter authentication error. Check cookies.")
                    elif "Unavailable" in text:
                        await message.reply(f"⚠️ Content unavailable: {url[:50]}")
                except Exception as reply_exc:  # noqa: BLE001
                    logger.debug(f"Could not reply with error hint: {reply_exc}")
            await safe_edit(
                status_msg, f"❌ [{idx}/{len(source)}] Failed: {url[:50]}..."
            )
        await asyncio.sleep(1)

    return failed_urls, baddiehub_titles
