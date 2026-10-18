# Terabox resolver - turns a Terabox share link into a direct link and hands it
# back to the master dispatcher.
#
# Reference analogue: colab_leecher/downlader/terabox.py

import logging

import aiohttp

logger = logging.getLogger(__name__)

RESOLVER_API = "https://ytshorts.savetube.me/api/v1/terabox-downloader"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


async def resolve_terabox(url: str):
    """Return a direct download link for a Terabox URL (or raise)."""
    payload = {"url": url}
    async with aiohttp.ClientSession() as session:
        async with session.post(RESOLVER_API, data=payload, headers=HEADERS) as response:
            if response.status != 200:
                raise Exception(f"Terabox resolver API failed (status {response.status})")
            data = await response.json()

    response_items = data.get("response")
    if not (isinstance(response_items, list) and response_items):
        logger.error(f"Terabox resolver API gave bad response: {data}")
        raise Exception("Terabox resolver API gave bad response")

    resolutions = response_items[0].get("resolutions")
    if not resolutions:
        raise Exception("Terabox resolver gave bad response (no resolutions)")

    direct_link = resolutions.get("Fast Download") or resolutions.get("HD Video")
    if not direct_link:
        raise Exception("Terabox resolver did not return a link")
    return direct_link


async def download_terabox_resolver(
    url, dest, status_msg, file_index, total_files, user_name, start_time
):
    """Resolve a Terabox link, then re-dispatch the direct link."""
    from media_bot.downlader.manager import download_media
    from media_bot.utility.handler import safe_edit

    try:
        logger.info(f"Terabox: Resolving link {url}")
        direct_link = await resolve_terabox(url)
        logger.info(f"Terabox: Resolved. New link: {direct_link[:70]}...")
        await safe_edit(
            status_msg,
            f"⏳ [{file_index}/{total_files}] Terabox link resolved. Starting download...",
        )
        return await download_media(
            direct_link, dest, None, None, status_msg, file_index, total_files, user_name, start_time
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Terabox resolver error: {exc}")
        return False, "", f"Terabox Error: {exc}"
