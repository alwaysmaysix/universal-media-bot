# Magnet / torrent downloader backed by libtorrent.
#
# Reference analogue: the torrent branch of colab_leecher/utility/task_manager.py
# (kept in its own module here). libtorrent is imported lazily so the rest of
# the package still imports on machines without it.

import asyncio
import logging

from humanize import naturalsize

from media_bot.utility.helper import format_time_hms, load_trackers, update_progress
from media_bot.utility.variables import Trackers

logger = logging.getLogger(__name__)


async def download_magnet(url, dest, status_msg, file_index, total_files, user_name, start_time):
    """Download a magnet link with libtorrent."""
    try:
        import libtorrent as lt
    except ImportError:
        logger.error("Libtorrent library is missing. Cannot download torrent.")
        return False, "", "Libtorrent library not installed."

    try:
        settings = {
            "user_agent": "qBittorrent/4.4.5",
            "listen_interfaces": "0.0.0.0:6881",
            "enable_dht": True,
            "enable_lsd": True,
            "enable_upnp": True,
            "enable_natpmp": True,
            "announce_to_all_tiers": True,
            "announce_to_all_trackers": True,
            "aio_threads": 4,
            "checking_mem_usage": 2048,
            "connections_limit": 2000,
            "unchoke_slots_limit": 50,
            "active_downloads": -1,
            "active_seeds": -1,
            "active_limit": -1,
        }
        session = lt.session(settings)  # type: ignore[attr-defined]
        params = lt.parse_magnet_uri(url)  # type: ignore[attr-defined]
        params.save_path = str(dest)

        if not Trackers.items:
            await asyncio.to_thread(load_trackers)
        params.trackers.extend(Trackers.items)

        handle = session.add_torrent(params)

        while not handle.status().has_metadata:
            await asyncio.sleep(0.1)

        torrent_name = handle.status().name
        logger.info(f"Magnet: Starting download for {torrent_name}")

        while not handle.status().is_seeding:
            s = handle.status()
            if s.state == lt.torrent_status.states.downloading and s.progress >= 1.0:  # type: ignore[attr-defined]
                logger.info("Magnet: Download complete (progress 100%)")
                break
            if s.state == lt.torrent_status.states.seeding:  # type: ignore[attr-defined]
                logger.info("Magnet: Download complete (now seeding)")
                break
            downloaded = s.total_done
            total = s.total_wanted
            speed = f"{naturalsize(s.download_rate)}/s"
            eta_sec = (total - downloaded) / s.download_rate if s.download_rate > 0 else 0
            await update_progress(
                status_msg, torrent_name, file_index, total_files, user_name, start_time,
                downloaded, total, speed, format_time_hms(eta_sec), dl_type="magnet",
            )
            await asyncio.sleep(2)

        s = handle.status()
        logger.info(f"Magnet: Download finished for {s.name}")
        await update_progress(
            status_msg, s.name, file_index, total_files, user_name, start_time,
            s.total_wanted, s.total_wanted, "Done", "Done", dl_type="magnet",
        )
        session.remove_torrent(handle)
        return True, f"Torrent '{s.name}' downloaded", ""
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Magnet download error: {exc}")
        return False, "", f"Magnet Error: {exc}"
