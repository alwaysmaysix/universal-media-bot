# Google Drive downloader (Drive API v3).
#
# Requires a valid token.json in the repo root (OAuth "drive.readonly").

import asyncio
import io
import logging
import re
import time
from pathlib import Path

from humanize import naturalsize

from media_bot.utility.helper import format_time_hms, update_progress
from media_bot.utility.variables import Config, Paths

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _extract_file_id(url: str):
    match = re.search(r"file/d/([a-zA-Z0-9_-]+)", url)
    if match:
        return match.group(1)
    match = re.search(r"id=([a-zA-Z0-9_-]+)", url)
    if match:
        return match.group(1)
    return None


def _build_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = Paths.TOKEN_FILE
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Gdrive token refresh failed: {exc}")
                return None, "GDrive token refresh failed. Please re-authenticate."
        else:
            logger.error("Gdrive token.json not found or invalid.")
            return None, "Gdrive 'token.json' not found or invalid. Please generate it."

    with open(token_path, "w", encoding="utf-8") as token:
        token.write(creds.to_json())
    return build("drive", "v3", credentials=creds), None


async def download_gdrive(url, dest, status_msg, file_index, total_files, user_name, start_time):
    """Download a single file from Google Drive."""
    try:
        from googleapiclient.http import MediaIoBaseDownload

        service, error = await asyncio.to_thread(_build_service)
        if error:
            return False, "", error

        file_id = _extract_file_id(url)
        if not file_id:
            return False, "", "Could not parse Google Drive file ID"

        metadata = service.files().get(fileId=file_id, fields="name, size").execute()
        filename = metadata.get("name", f"gdrive_file_{file_id}")
        total_bytes = int(metadata.get("size", 0))
        filepath = dest / filename
        logger.info(f"GDrive: Starting download for {filename} ({naturalsize(total_bytes)})")

        request = service.files().get_media(fileId=file_id)
        downloader = MediaIoBaseDownload(io.FileIO(str(filepath), "wb"), request)

        downloaded_bytes = 0
        done = False
        while not done:
            status, done = await asyncio.to_thread(downloader.next_chunk)
            if status:
                downloaded_bytes = int(status.progress() * total_bytes)
                elapsed = time.time() - start_time
                speed = downloaded_bytes / elapsed if elapsed > 0 else 0
                eta_sec = (total_bytes - downloaded_bytes) / speed if speed > 0 else 0
                await update_progress(
                    status_msg, url, file_index, total_files, user_name, start_time,
                    downloaded_bytes, total_bytes,
                    f"{naturalsize(speed)}/s", format_time_hms(eta_sec), dl_type="gdrive",
                )
            await asyncio.sleep(0.1)

        logger.info(f"GDrive: Download complete for {filename}")
        return True, f"Downloaded {filename}", ""
    except Exception as exc:  # noqa: BLE001
        logger.error(f"GDrive download error: {exc}")
        return False, "", f"GDrive Error: {exc}"
