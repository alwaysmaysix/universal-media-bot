# cyberdrop-dl engine - the second general-purpose fallback.
#
# Progress is estimated by periodically summing the sizes of the files already
# present in the directory, so the CLI UI is disabled (-‑ui DISABLED) and the
# download starts immediately (--download). This also avoids needing a TTY,
# which Colab does not provide.
#
# Valid --ui values: DISABLED | ACTIVITY | SIMPLE | FULLSCREEN.

import asyncio
import logging
import time
from pathlib import Path

from media_bot.utility import runtime
from media_bot.utility.helper import build_custom_progress_display

logger = logging.getLogger(__name__)


async def get_cyberdrop_progress(dest_path):
    """Estimate progress from the download directory contents."""
    try:
        files = []
        downloaded_bytes = 0
        p_dest_path = Path(dest_path)
        if p_dest_path.exists():
            for filepath in p_dest_path.rglob("*"):
                if filepath.is_file() and filepath.suffix != ".part":
                    files.append(str(filepath))
                    downloaded_bytes += filepath.stat().st_size
        return {
            "completed_files": len(files),
            "downloaded_bytes": downloaded_bytes,
            "type": "cyberdrop-dl",
        }
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Cyberdrop progress monitor error: {exc}")
        return None


def _has_files(dest) -> bool:
    try:
        return any(p.is_file() for p in Path(dest).rglob("*"))
    except Exception:  # noqa: BLE001
        return False


async def download_cyberdrop(
    url,
    dest,
    status_msg=None,
    file_index=1,
    total_files=1,
    user_name="User",
    start_time=0,
):
    from pyrogram.errors import FloodWait, MessageNotModified

    cmd_args = [
        "cyberdrop-dl",
        "--ui", "DISABLED",       # no rich UI / no TTY required
        "--download",             # skip UI, start downloading immediately
        "--ignore-history",       # our dest is per-task; don't skip "seen" URLs
        "-d", str(dest),
        url,
    ]
    proc = await runtime.spawn_exec(
        *cmd_args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    last_update = time.time()

    async def monitor_progress():
        nonlocal last_update
        while proc.returncode is None:
            await asyncio.sleep(2)
            progress_data = await get_cyberdrop_progress(dest)
            if progress_data and status_msg:
                try:
                    display = build_custom_progress_display(
                        url, progress_data, file_index, total_files, user_name, start_time
                    )
                    await status_msg.edit_text(display)
                    last_update = time.time()
                except (MessageNotModified, FloodWait):
                    pass

    monitor_task = asyncio.create_task(monitor_progress())
    stdout, stderr = await proc.communicate()
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass

    # cyberdrop-dl can exit non-zero when some individual files fail; treat the
    # run as successful if anything actually landed on disk.
    success = proc.returncode == 0 or _has_files(dest)
    return success, stdout.decode("utf-8", "ignore"), stderr.decode("utf-8", "ignore")
