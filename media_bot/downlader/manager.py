# Master dispatcher.
#
# Reference analogue: colab_leecher/downlader/manager.py - it inspects each link
# and routes it to the correct specialised downloader, falling back to the
# general-purpose engines.

import asyncio
import logging
import time
from urllib.parse import urlparse

from media_bot.downlader.aria2c import download_aria2c
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
from media_bot.utility.helper import sizeChecker

logger = logging.getLogger(__name__)

YTDL_HOSTS = ("youtube.com", "youtu.be", "x.com", "twitter.com")

DEFAULT_CHAIN = ["gallerydl", "cyberdrop", "aria2c"]

MANUAL_ENGINES = {"gallerydl", "cyberdrop", "aria2c", "mega"}


async def _run_engine(
    engine,
    url,
    dest,
    after_date,
    before_date,
    status_msg,
    file_index,
    total_files,
    user_name,
    start_time,
    cookies_file,
    ytdl_format,
    resume,
    torrent_files,
):
    """Run one named engine; returns the standard (success, stdout, stderr)."""
    if engine == "gallerydl":
        return await download_gallery_dl(
            url, dest, after_date, before_date, status_msg,
            file_index, total_files, user_name, start_time, cookies_file=cookies_file,
        )
    if engine == "cyberdrop":
        return await download_cyberdrop(
            url, dest, status_msg, file_index, total_files, user_name, start_time
        )
    if engine == "aria2c":
        return await download_aria2c(
            url, dest, status_msg, file_index, total_files, user_name, start_time,
            resume=resume, cookies_file=cookies_file,
            select_files=torrent_files if url.startswith("magnet:?") else "",
        )
    if engine == "mega":
        return await download_mega(
            url, dest, status_msg, file_index, total_files, user_name, start_time
        )
    if engine == "ytdl":
        return await download_ytdl(
            url, dest, status_msg, file_index, total_files, user_name, start_time,
            after_date, before_date, ytdl_format=ytdl_format,
            cookies_file=cookies_file, resume=resume,
        )
    raise ValueError(f"Unknown engine: {engine}")


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
    engine="auto",
    fallback=None,
    cookies_file=None,
    ytdl_format="best",
    resume=True,
    torrent_files="",
):
    """Route a single URL to the right downloader.

    Returns a (success, stdout, stderr) tuple, matching the notebook contract.
    """
    kwargs = dict(
        after_date=after_date,
        before_date=before_date,
        status_msg=status_msg,
        file_index=file_index,
        total_files=total_files,
        user_name=user_name,
        start_time=start_time,
        cookies_file=cookies_file,
        ytdl_format=ytdl_format,
        resume=resume,
        torrent_files=torrent_files,
    )
    try:
        # ---- manual engine override (the ⚙️ buttons) ----
        if engine in MANUAL_ENGINES:
            return await _run_engine(engine, url, dest, **kwargs)

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
                after_date, before_date, ytdl_format=ytdl_format,
                cookies_file=cookies_file, resume=resume,
            )

        if url.startswith("magnet:?"):
            return await download_magnet(url, dest, status_msg, file_index, total_files, user_name, start_time)

        if "mega.nz" in url:
            return await download_mega(url, dest, status_msg, file_index, total_files, user_name, start_time)

        if "terabox.com" in url or "teraboxapp.com" in url:
            return await download_terabox_resolver(url, dest, status_msg, file_index, total_files, user_name, start_time)

        if ".m3u8" in url.lower():
            return await download_m3u8(url, dest, status_msg, file_index, total_files, user_name, start_time)

        # ---- user-configurable generic fallback chain ----
        chain = [e for e in (fallback or DEFAULT_CHAIN) if e in ("gallerydl", "cyberdrop", "aria2c")]
        if not chain:
            chain = list(DEFAULT_CHAIN)

        last_error = ""
        for name in chain:
            await safe_edit(
                status_msg,
                f"⏳ [{file_index}/{total_files}] Trying {name}...\n🔗 {url[:50]}...",
            )
            try:
                success, stdout, stderr = await _run_engine(name, url, dest, **kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"{name} raised for {url}: {exc}")
                last_error = str(exc)
                continue
            if success:
                return True, stdout, stderr
            last_error = stderr or f"{name} failed"

        raise Exception(last_error or f"All downloaders failed for {url}")
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
    engine="auto",
    fallback=None,
    cookies_file=None,
    ytdl_format="best",
    resume=True,
    torrent_files="",
    size_limit=0,
):
    """Loop over every source URL and dispatch it. Returns (failed, titles)."""
    failed_urls = []
    baddiehub_titles = {}

    for idx, url in enumerate(source, 1):
        start_time = time.time()
        try:
            # ---- refuse obviously oversized direct links up front ----
            if size_limit and url.startswith(("http://", "https://")):
                ok, size = sizeChecker(url, size_limit)
                if not ok:
                    raise Exception(
                        f"File is {size / 1024 / 1024:.0f} MB, larger than the "
                        f"{size_limit // 1024 // 1024} MB limit (use Extract/Zip or raise MAX_FILE_SIZE_MB)"
                    )

            if engine == "auto" and "baddiehub.com" in url.lower():
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
                    url, dest, after_date, before_date, status_msg, idx, len(source), user_name, start_time,
                    engine=engine, fallback=fallback, cookies_file=cookies_file,
                    ytdl_format=ytdl_format, resume=resume, torrent_files=torrent_files,
                )
                if not success:
                    raise Exception(stderr or "Download function returned False")
            await safe_edit(
                status_msg,
                f"✅ [{idx}/{len(source)}] Download Complete. Processing files...",
            )
        except asyncio.CancelledError:
            raise
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
                    elif "larger than the" in text:
                        await message.reply(f"⚠️ Skipped oversized file: {url[:60]}\n{text}")
                except Exception as reply_exc:  # noqa: BLE001
                    logger.debug(f"Could not reply with error hint: {reply_exc}")
            await safe_edit(
                status_msg, f"❌ [{idx}/{len(source)}] Failed: {url[:50]}..."
            )
        await asyncio.sleep(1)

    return failed_urls, baddiehub_titles
