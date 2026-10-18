# HLS / m3u8 downloader.
#
# Faithful port of the notebook's M3U8Downloader: it fetches the playlist,
# downloads every segment (optionally AES-128 decrypting it), writes an ffmpeg
# concat list and merges everything into a single mp4.
#
# Can be used as a module:
#     from media_bot.downlader.m3u8 import download_m3u8
# or as a CLI:
#     python -m media_bot.downlader.m3u8 "<m3u8 url>" [output.mp4]

import asyncio
import enum
import io
import logging
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from media_bot.utility.helper import update_progress
from media_bot.utility.variables import Paths

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Low level helpers
# --------------------------------------------------------------------------- #
def read_bytes(path):
    with open(path, "rb") as file:
        return file.read()


def write_bytes(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as file:
        file.write(data)


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as file:
        return file.read()


def write_text(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as file:
        file.write(data)


def request_bytes(url, headers):
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error requesting {url}: {exc}")
        return None


def ensure_download(url, headers, path):
    if os.path.exists(path):
        return
    data = request_bytes(url, headers)
    if data:
        write_bytes(path, data)


def decrypt_aes(key, iv, data):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    return decryptor.update(data) + decryptor.finalize()


def ensure_decrypt(key, iv, enc_path, dec_path):
    if os.path.exists(dec_path):
        return
    if not os.path.exists(enc_path):
        logger.error(f"Cannot decrypt, source missing: {enc_path}")
        return
    try:
        write_bytes(dec_path, decrypt_aes(key, iv, read_bytes(enc_path)))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Decryption failed for {enc_path}: {exc}")


def parse_simple_kv_list(text: str):
    d = {}
    for kv in text.split(","):
        kv = kv.strip()
        if not kv:
            continue
        parts = kv.split("=", 1)
        if len(parts) == 2:
            key, value = parts[0].strip(), parts[1].strip()
            match = re.match(r'^"(.*)"$', value)
            if match:
                value = match.group(1).strip()
            d[key] = value
    return d


def sanitize_filename(name: str):
    name = unquote(name)
    name = "".join(ch for ch in name if ord(ch) >= 32)
    name = name.replace("/", "_").replace("\\", "_")
    name = name.replace("'", "").replace('"', "")
    return re.sub(r"\s+", " ", name).strip()


# --------------------------------------------------------------------------- #
# Playlist parser
# --------------------------------------------------------------------------- #
class M3U8Parser:
    class Stage(enum.Enum):
        init = enum.auto()
        trunk = enum.auto()
        end = enum.auto()

    def __init__(self):
        self.stage = self.Stage.init
        self.headers = {}
        self.trunks = []

    @classmethod
    def parse(cls, text: str):
        parser = cls()
        for raw in text.splitlines():
            line = raw.strip()
            if line:
                parser.input(line)
        return parser.headers, parser.trunks

    def input(self, line: str):
        if self.stage is self.Stage.init:
            if line == "#EXTM3U":
                self.stage = self.Stage.trunk
        elif self.stage is self.Stage.trunk:
            self._input_trunk(line)

    def _input_trunk(self, line: str):
        if line == "#EXT-X-ENDLIST":
            self.stage = self.Stage.end
        elif line.startswith("#EXT-X-"):
            kv = line[7:].split(":", 1)
            if len(kv) == 2:
                key, value = kv[0].strip(), kv[1].strip()
            else:
                key, value = kv[0].strip(), ""
            self.headers[key] = value
        elif line.startswith("#EXTINF") or line.startswith("#"):
            pass
        else:
            self.trunks.append(line)


# --------------------------------------------------------------------------- #
# Downloader
# --------------------------------------------------------------------------- #
class M3U8Downloader:
    def __init__(
        self,
        url,
        headers=None,
        download_path="download/",
        index_name="_index.txt",
        output_name="_output.mp4",
        async_max_workers=10,
        check_mode=False,
    ):
        self.url = url
        if "/" in url:
            base, meta = url.rsplit("/", 1)
            self.base_url = base + "/"
            self.m3u8_meta = meta
        else:
            self.base_url = ""
            self.m3u8_meta = url
        self.headers = headers or {}
        self.download_path = os.path.normpath(download_path) + os.sep
        self.index_name = sanitize_filename(index_name)
        self.output_name = sanitize_filename(output_name)
        self.async_max_workers = async_max_workers
        self.check_mode = check_mode
        self.crypt_mode = False
        self.key = None
        self.iv = None
        self.m3u8_trunks = []

    # -- path helpers ------------------------------------------------------ #
    def get_filename(self, url_or_name):
        if url_or_name.startswith("http"):
            parsed = urlparse(url_or_name)
            return sanitize_filename(os.path.basename(parsed.path))
        return sanitize_filename(os.path.basename(url_or_name))

    def _path_for(self, name):
        return os.path.join(self.download_path, name)

    def ensure_download(self, name):
        if name.startswith("http"):
            url = name
        else:
            url = self.base_url + name
        filename = self.get_filename(name)
        path = self._path_for(filename)
        if self.check_mode:
            if not os.path.exists(path):
                raise Exception("Download target not exists:", name)
        else:
            ensure_download(url, self.headers, path)
        return path

    def ensure_decrypt(self, name):
        filename = self.get_filename(name)
        enc_path = self._path_for(filename)
        dec_path = enc_path + "._decrypt.ts"
        if self.check_mode:
            if not os.path.exists(dec_path):
                raise Exception("Decrypt target not exists:", name)
        else:
            ensure_decrypt(self.key, self.iv, enc_path, dec_path)

    # -- pipeline ---------------------------------------------------------- #
    def fetch_meta(self):
        logger.info("Fetch m3u8 meta...")
        meta_path = self.ensure_download(self.m3u8_meta)
        meta_filename = os.path.basename(meta_path)
        self.m3u8_headers, self.m3u8_trunks = M3U8Parser.parse(read_text(meta_path))
        if "KEY" not in self.m3u8_headers:
            self.crypt_mode = False
        else:
            self.crypt_mode = True
            self.fetch_crypt_key()

    def fetch_crypt_key(self):
        self.m3u8_key_meta = parse_simple_kv_list(self.m3u8_headers["KEY"])
        if not self.m3u8_key_meta["METHOD"].startswith("AES-"):
            raise Exception("Invalid method", self.m3u8_key_meta)
        if "IV" in self.m3u8_key_meta and self.m3u8_key_meta["IV"].startswith("0x"):
            self.iv = bytes.fromhex(self.m3u8_key_meta["IV"][2:])
        else:
            self.iv = b"\x00" * 16
        logger.info("Fetch crypt key...")
        key_path = self.ensure_download(self.m3u8_key_meta["URI"])
        self.key = read_bytes(self._path_for(os.path.basename(key_path)))

    def fetch_trunk(self, i):
        trunk = self.m3u8_trunks[i]
        self.ensure_download(trunk)
        if self.crypt_mode:
            self.ensure_decrypt(trunk)

    def fetch_trunks_async(self):
        logger.info(f"Fetch trunks (Async: {self.async_max_workers} threads)...")
        with ThreadPoolExecutor(max_workers=self.async_max_workers) as executor:
            list(executor.map(self.fetch_trunk, range(len(self.m3u8_trunks))))

    def fetch_async(self):
        self.fetch_meta()
        self.fetch_trunks_async()

    def gen_index(self):
        logger.info("Generate index...")
        sio = io.StringIO()
        for trunk in self.m3u8_trunks:
            fname = self.get_filename(trunk)
            name = fname + "._decrypt.ts" if self.crypt_mode else fname
            print(f"file '{name}'", file=sio)
        index_path = self._path_for(self.index_name)
        write_text(index_path, sio.getvalue())
        return index_path

    def ffmpeg_concat(self):
        logger.info("Concat videos...")
        index_path = self._path_for(self.index_name)
        output_path = self._path_for(self.output_name)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", index_path, "-c", "copy", output_path],
            check=False,
        )
        return output_path

    # -- progress ---------------------------------------------------------- #
    def segment_stats(self):
        total = len(self.m3u8_trunks)
        done = 0
        size = 0
        try:
            for entry in os.listdir(self.download_path):
                if entry.endswith(".ts"):
                    done += 1
                    size += os.path.getsize(os.path.join(self.download_path, entry))
        except OSError:
            pass
        return done, total, size


# --------------------------------------------------------------------------- #
# Async entry point
# --------------------------------------------------------------------------- #
async def download_m3u8(
    url,
    dest=None,
    status_msg=None,
    file_index=1,
    total_files=1,
    user_name="User",
    start_time=0,
    user_agent=None,
    referer="https://www.google.com/",
    max_workers=20,
):
    """Download and merge an HLS/m3u8 stream. Returns (ok, message, error)."""
    try:
        download_path = Paths.M3U8_DIR
        download_path.mkdir(parents=True, exist_ok=True)

        headers = {
            "Referer": referer,
            "User-Agent": user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        }
        stem = sanitize_filename(Path(urlparse(url).path).stem) or "output"
        output_name = f"{stem}.mp4"

        md = M3U8Downloader(
            url,
            headers=headers,
            download_path=str(download_path) + os.sep,
            index_name=f"_{stem}_index.txt",
            output_name=output_name,
            async_max_workers=max_workers,
        )

        def work():
            md.fetch_async()
            md.gen_index()
            return md.ffmpeg_concat()

        task = asyncio.create_task(asyncio.to_thread(work))
        while not task.done():
            await asyncio.sleep(3)
            done, total, size = md.segment_stats()
            percentage = (done / total * 100) if total else None
            await update_progress(
                status_msg, url, file_index, total_files, user_name, start_time,
                size, 0, f"{done}/{total} segments", "N/A", dl_type="m3u8",
            )
            _ = percentage

        out_path = await task
        if out_path and os.path.exists(out_path):
            return True, f"Downloaded {out_path}", ""
        return False, "", "ffmpeg did not produce an output file"
    except Exception as exc:  # noqa: BLE001
        logger.error(f"M3U8 download error: {exc}")
        return False, "", f"M3U8 Error: {exc}"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m media_bot.downlader.m3u8 <m3u8_url> [output.mp4]")
        return 1
    url = argv[0]
    output_name = argv[1] if len(argv) > 1 else "_output.mp4"
    target = Paths.M3U8_DIR
    target.mkdir(parents=True, exist_ok=True)
    md = M3U8Downloader(
        url,
        headers={"Referer": "https://www.google.com/", "User-Agent": "Mozilla/5.0"},
        download_path=str(target) + os.sep,
        output_name=output_name,
    )
    md.fetch_async()
    md.gen_index()
    out = md.ffmpeg_concat()
    print(f"Output: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
