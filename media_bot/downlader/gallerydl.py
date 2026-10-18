# gallery-dl engine.
#
# Reference analogue: colab_leecher/downlader/aria2.py (the "catch-all" direct
# downloader). Here gallery-dl is the first general-purpose fallback.

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from media_bot.utility import runtime
from media_bot.utility.helper import (
    build_custom_progress_display,
    parse_size_to_bytes,
)

logger = logging.getLogger(__name__)


async def parse_gallery_dl_progress(line: str):
    """Parse gallery-dl progress output from stderr."""
    try:
        match = re.search(
            r"\[download\]\s+(\d+\.?\d*)%\s+of\s+([\d.]+\w+)\s+at\s+([\d.]+\w+/s)"
            r"(?:\s+ETA\s+([\d:]+))?",
            line,
        )
        if match:
            percentage = float(match.group(1))
            total_size_str = match.group(2)
            total_bytes = parse_size_to_bytes(total_size_str)
            downloaded_bytes = percentage / 100 * total_bytes
            return {
                "percentage": percentage,
                "total_size_str": total_size_str,
                "total_bytes": total_bytes,
                "downloaded_bytes": downloaded_bytes,
                "speed": match.group(3),
                "eta": match.group(4) or "00:00",
                "type": "gallery-dl",
            }
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Gallery-dl progress parse error: {exc}")
    return None


def _build_date_filter(after_date=None, before_date=None):
    """Translate after/before (YYYYMMDD) dates into a gallery-dl --filter."""
    date_fields = ["date", "published", "created", "timestamp", "post_date", "upload_date"]
    filters = []
    if after_date:
        conditions = [
            f"({field} and {field} >= datetime({after_date[:4]},{after_date[4:6]},{after_date[6:8]}))"
            for field in date_fields
        ]
        filters.append(f"({' or '.join(conditions)})")
    if before_date:
        end_date = datetime.strptime(before_date, "%Y%m%d") + timedelta(days=1)
        end_str = end_date.strftime("%Y%m%d")
        conditions = [
            f"({field} and {field} < datetime({end_str[:4]},{end_str[4:6]},{end_str[6:8]}))"
            for field in date_fields
        ]
        filters.append(f"({' or '.join(conditions)})")
    return " and ".join(filters) if filters else None


async def download_gallery_dl(
    url,
    dest,
    after_date=None,
    before_date=None,
    status_msg=None,
    file_index=1,
    total_files=1,
    user_name="User",
    start_time=0,
    cookies_file=None,
):
    from pyrogram.errors import FloodWait, MessageNotModified

    cmd = ["gallery-dl", "-d", str(dest)]
    if cookies_file and Path(cookies_file).exists():
        cmd.extend(["--cookies", str(cookies_file)])
    combined_filter = _build_date_filter(after_date, before_date)
    if combined_filter:
        cmd.extend(["--filter", combined_filter])
    cmd.append(url)

    proc = await runtime.spawn_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    last_update = time.time()
    stderr_lines = []

    async def monitor_progress():
        nonlocal last_update
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            decoded_line = line.decode("utf-8", errors="ignore")
            stderr_lines.append(decoded_line)
            progress_data = await parse_gallery_dl_progress(decoded_line)
            if progress_data and status_msg and (time.time() - last_update > 2):
                try:
                    display = build_custom_progress_display(
                        url, progress_data, file_index, total_files, user_name, start_time
                    )
                    await status_msg.edit_text(display)
                    last_update = time.time()
                except (MessageNotModified, FloodWait):
                    pass

    await asyncio.gather(proc.wait(), monitor_progress())
    stdout = (await proc.stdout.read()).decode("utf-8", errors="ignore")
    return proc.returncode == 0, stdout, "".join(stderr_lines)
