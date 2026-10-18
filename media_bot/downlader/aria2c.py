# aria2c download engine.
#
# Reference analogue: colab_leecher/downlader/aria2.py - a general purpose
# multi-connection direct downloader. Here it is exposed as a *user selectable*
# engine (see Prefs.engine) instead of only being used for magnets.

import asyncio
import logging
import re
import subprocess
import time
from pathlib import Path

from media_bot.utility import runtime
from media_bot.utility.helper import build_custom_progress_display, parse_size_to_bytes

logger = logging.getLogger(__name__)

# aria2c summary lines look like:
# [#1a2b3c 15MiB/50MiB(30%) CN:5 DL:2.3MiB ETA:15s]
_PROGRESS_RE = re.compile(r"([\d.]+[KMGTP]?i?B)/([\d.]+[KMGTP]?i?B)\((\d+)%\)")
_SPEED_RE = re.compile(r"DL:([\d.]+[KMGTP]?i?B)")
_ETA_RE = re.compile(r"ETA:(\S+)")


def get_aria2c_name(url: str) -> str:
    """Ask aria2c for the filename it would save, using a dry run."""
    try:
        result = subprocess.run(
            f'aria2c -x10 --dry-run --file-allocation=none "{url}"',
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=True,
            timeout=60,
        )
        stdout = result.stdout.decode("utf-8", "ignore")
        filename = stdout.split("complete: ")[-1].split("\n")[0].strip()
        name = filename.split("/")[-1].strip()
        return name or "UNKNOWN DOWNLOAD NAME"
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"aria2c dry-run name lookup failed: {exc}")
        return "UNKNOWN DOWNLOAD NAME"


async def download_aria2c(
    url,
    dest,
    status_msg=None,
    file_index=1,
    total_files=1,
    user_name="User",
    start_time=0,
    resume=True,
    cookies_file=None,
    select_files="",
):
    """Download a direct link with aria2c, streaming progress to status_msg."""
    from pyrogram.errors import FloodWait, MessageNotModified

    Path(dest).mkdir(parents=True, exist_ok=True)

    cmd = [
        "aria2c",
        "-x16",
        "-s16",
        "--seed-time=0",
        "--summary-interval=1",
        "--max-tries=3",
        "--console-log-level=warn",
        "--file-allocation=none",
    ]
    if resume:
        cmd.append("--continue=true")
    if cookies_file and Path(cookies_file).exists():
        cmd.append(f"--load-cookies={cookies_file}")
    if select_files:
        cmd.append(f"--select-file={select_files}")
    cmd.extend(["-d", str(dest), url])

    proc = await runtime.spawn_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )

    last_update = time.time()
    output_lines = []

    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode("utf-8", "ignore")
        output_lines.append(text)

        match = _PROGRESS_RE.search(text)
        if match and status_msg and (time.time() - last_update > 2):
            speed = _SPEED_RE.search(text)
            eta = _ETA_RE.search(text)
            progress_data = {
                "type": "aria2c",
                "percentage": float(match.group(3)),
                "downloaded_bytes": parse_size_to_bytes(match.group(1)),
                "total_size_str": match.group(2),
                "speed": f"{speed.group(1)}/s" if speed else "N/A",
                "eta": eta.group(1) if eta else "N/A",
            }
            try:
                display = build_custom_progress_display(
                    url, progress_data, file_index, total_files, user_name, start_time
                )
                await status_msg.edit_text(display)
                last_update = time.time()
            except (MessageNotModified, FloodWait):
                pass

    await proc.wait()
    stdout = "".join(output_lines)
    return proc.returncode == 0, stdout, "" if proc.returncode == 0 else stdout


_FILE_LINE_RE = re.compile(r"^\s*(\d+)\|(.+?)\s*$")


async def list_torrent_files(magnet: str, timeout: int = 90):
    """Fetch torrent metadata and return [(index, path)] without downloading.

    Returns an empty list when the metadata could not be retrieved.
    """
    cmd = [
        "aria2c",
        "--bt-metadata-only=true",
        "--bt-save-metadata=true",
        "--show-files=true",
        "--follow-torrent=mem",
        "--console-log-level=warn",
        "--summary-interval=0",
        magnet,
    ]
    proc = await runtime.spawn_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        return []

    files = []
    for line in stdout.decode("utf-8", "ignore").splitlines():
        match = _FILE_LINE_RE.match(line)
        if match:
            files.append((int(match.group(1)), match.group(2)))
    return files
