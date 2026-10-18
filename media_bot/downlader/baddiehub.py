# BaddieHub scraper.
#
# Walks listing pages, collects direct media URLs, maps them to their page
# titles (used as hashtag captions) and hands each URL to cyberdrop-dl.

import asyncio
import logging
import re
from urllib.parse import urlparse

from media_bot.utility import runtime
from media_bot.utility.helper import (
    extract_media_urls,
    extract_urls,
    get_website_html,
)

logger = logging.getLogger(__name__)

TITLE_REGEXES = [
    re.compile(r"""<h1[^>]*class=["']entry-title["'][^>]*itemprop=["']name["'][^>]*>([^<]+)</h1>""", re.IGNORECASE),
    re.compile(r"""<h1[^>]*itemprop=["']name["'][^>]*class=["']entry-title["'][^>]*>([^<]+)</h1>""", re.IGNORECASE),
]
IFRAME_REGEX = re.compile(r"""<iframe[^>]+src=["']([^"']+)["']""", re.IGNORECASE)


def _page_title(html: str):
    for pattern in TITLE_REGEXES:
        match = pattern.search(html)
        if match:
            return match.group(1).strip()
    return None


async def download_baddiehub(url, dest):
    """Download all media from a BaddieHub page.

    Returns (success, {media_url: page_title}).
    """
    try:
        logger.info(f"BaddieHub download: {url}")
        html = await asyncio.to_thread(get_website_html, url)
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        is_listing = (
            not parsed.path.strip("/")
            or "?filter=" in url
            or parsed.path.strip("/") in ["latest", "trending", "popular"]
        )

        all_media = []
        title_map = {}

        if is_listing:
            internal = extract_urls(html, base_url)
            content_urls = [
                u
                for u in set(internal)
                if urlparse(u).path.strip("/")
                and not any(
                    x in u.lower()
                    for x in ["?filter=", "/page/", "/category/", "/tag/", ".css", ".js", ".png", ".jpg"]
                )
            ]
            logger.info(f"Found {len(content_urls)} content URLs")
            for content_url in content_urls[:30]:
                try:
                    content_html = await asyncio.to_thread(get_website_html, content_url)
                    page_title = _page_title(content_html)
                    media = extract_media_urls(content_html)
                    if page_title:
                        for media_url in media:
                            title_map[media_url] = page_title
                    all_media.extend(media)
                    await asyncio.sleep(0.5)
                except Exception as exc:  # noqa: BLE001
                    logger.error(f"Error scraping {content_url}: {exc}")
        else:
            page_title = _page_title(html)
            all_media = extract_media_urls(html)
            if page_title:
                for media_url in all_media:
                    title_map[media_url] = page_title

            iframes = IFRAME_REGEX.findall(html)
            for iframe_url in iframes[:5]:
                try:
                    if "baddiehub.com" in iframe_url or iframe_url.startswith("/"):
                        if iframe_url.startswith("/"):
                            iframe_url = base_url + iframe_url
                        iframe_html = await asyncio.to_thread(get_website_html, iframe_url)
                        iframe_media = extract_media_urls(iframe_html)
                        if page_title:
                            for media_url in iframe_media:
                                title_map[media_url] = page_title
                        all_media.extend(iframe_media)
                except Exception as exc:  # noqa: BLE001
                    logger.error(f"Iframe error {iframe_url}: {exc}")

        all_media = list(set(all_media))
        if not all_media:
            raise Exception("No media URLs found on BaddieHub page")

        logger.info(f"Found {len(all_media)} media URLs")
        for media_url in all_media:
            cmd_args = ["cyberdrop-dl", "--download", "--ui", "DISABLED", "-d", str(dest), media_url]
            proc = await runtime.spawn_exec(
                *cmd_args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()

        return True, title_map
    except Exception as exc:  # noqa: BLE001
        logger.error(f"BaddieHub download failed: {exc}")
        raise
