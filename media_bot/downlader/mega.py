# Mega.nz downloader using the `megadl` CLI.
#
# Reference analogue: colab_leecher/downlader/mega.py

import asyncio
import logging
import re

from media_bot.utility import runtime
from media_bot.utility.helper import parse_size_to_bytes, update_progress

logger = logging.getLogger(__name__)

MEGA_REGEX = re.compile(
    r"([\d.]+)%\s*\(([\d.]+\s*\w+)\s*/\s*([\d.]+\s*\w+)\)\s*([\d.]+\s*\w+/s)"
)


async def download_mega(url, dest, status_msg, file_index, total_files, user_name, start_time):
    """Download a Mega file/folder using megadl."""
    try:
        cmd_args = ["megadl", "--no-ask-password", "--path", str(dest), url]
        proc = await runtime.spawn_exec(
            *cmd_args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        logger.info(f"Mega: Starting download for {url}")

        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            line_str = line.decode("utf-8", "ignore").strip()
            if not line_str:
                continue

            match = MEGA_REGEX.search(line_str)
            if match:
                downloaded_bytes = parse_size_to_bytes(match.group(2))
                total_bytes = parse_size_to_bytes(match.group(3))
                await update_progress(
                    status_msg, url, file_index, total_files, user_name, start_time,
                    downloaded_bytes, total_bytes, match.group(4), "N/A", dl_type="mega",
                )
                continue

            # megadl sometimes formats progress differently; try the fallback.
            try:
                parts = line_str.split(": ")
                subparts = parts[1].split() if len(parts) > 1 else []
                if len(subparts) > 10:
                    file_name = parts[0]
                    downloaded_bytes = parse_size_to_bytes(f"{subparts[2]} {subparts[3]}")
                    total_bytes = parse_size_to_bytes(f"{subparts[7]} {subparts[8]}")
                    speed_str = f"{subparts[9][1:]} {subparts[10][:-1]}"
                    await update_progress(
                        status_msg, file_name, file_index, total_files, user_name, start_time,
                        downloaded_bytes, total_bytes, speed_str, "N/A", dl_type="mega",
                    )
                else:
                    logger.info(f"[megadl]: {line_str}")
            except Exception:  # noqa: BLE001
                logger.info(f"[megadl]: {line_str}")

        await proc.wait()
        if proc.returncode == 0:
            logger.info(f"Mega: Download complete for {url}")
            return True, "Mega Download Complete", ""
        logger.error(f"Mega: Download failed (code: {proc.returncode})")
        return False, "", "Mega download failed. Check logs."
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Mega download error: {exc}")
        return False, "", f"Mega Error: {exc}"
