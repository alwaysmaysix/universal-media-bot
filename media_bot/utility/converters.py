# Archive helpers - zipping and unzipping downloaded media.
#
# Reference analogue: colab_leecher/utility/converters.py (the archive(),
# extract(), multipartArchive() and *Handler helpers). Commands are the same
# ones the reference shells out to (zip / 7z / unrar / tar), so behaviour
# matches on a Colab or Debian style host.

import asyncio
import logging
import re
import shlex
import shutil
from pathlib import Path

from media_bot.utility import runtime

logger = logging.getLogger(__name__)

ARCHIVE_EXTS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".001",
}

# companion parts we must never extract on their own
_SPLIT_ZIP_RE = re.compile(r"\.z\d\d$", re.IGNORECASE)
_SPLIT_7Z_RE = re.compile(r"\.\d{3}$", re.IGNORECASE)
_PART_RAR_RE = re.compile(r"\.part(\d+)\.rar$", re.IGNORECASE)
_TAR_GZ_RE = re.compile(r"\.tar\.(gz|bz2|xz)$", re.IGNORECASE)


def is_archive(path) -> bool:
    path = Path(path)
    name = path.name.lower()
    return (
        path.suffix.lower() in ARCHIVE_EXTS
        or bool(_TAR_GZ_RE.search(name))
        or bool(_SPLIT_ZIP_RE.search(name))
        or bool(_PART_RAR_RE.search(name))
    )


def _is_primary_archive(path) -> bool:
    """Filter out split companions (.z01, .002, .part2.rar ...)."""
    name = Path(path).name.lower()
    if _SPLIT_ZIP_RE.search(name):
        return False
    if _SPLIT_7Z_RE.search(name) and not name.endswith(".001"):
        return False
    match = _PART_RAR_RE.search(name)
    if match and match.group(1) != "1":
        return False
    return True


async def _run(cmd: str, cwd=None):
    proc = await runtime.spawn_shell(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await proc.communicate()
    finally:
        runtime.unregister(proc)
    output = stdout.decode("utf-8", "ignore") if stdout else ""
    if proc.returncode != 0:
        logger.warning(f"Archive command failed ({proc.returncode}): {cmd}\n{output[-500:]}")
    return proc.returncode, output


def _snapshot(directory: Path) -> set:
    try:
        return {p for p in directory.iterdir()}
    except FileNotFoundError:
        return set()


async def archive(
    source_path,
    out_dir,
    is_split: bool = False,
    password: str = "",
    remove: bool = False,
    name: str = None,
    chunk: str = "2000m",
):
    """Create a .zip from `source_path` inside `out_dir`.

    Returns the list of created files (a split archive produces several parts).
    """
    source_path = Path(source_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base = name or source_path.name
    zip_path = out_dir / f"{base}.zip"
    before = _snapshot(out_dir)

    # Zip a folder's *contents* so extraction lands at the top level.
    if source_path.is_dir():
        entries = ["."]
        workdir = source_path
    else:
        entries = [source_path.name]
        workdir = source_path.parent

    if not password:
        split = f"-s {chunk} " if is_split else ""
        quoted = " ".join(shlex.quote(e) for e in entries)
        cmd = f"zip -r -0 {split}{shlex.quote(str(zip_path))} {quoted}"
    else:
        split = f"-v{chunk} " if is_split else ""
        quoted = " ".join(shlex.quote(e) for e in entries)
        cmd = (
            f"7z a -y -mx=0 -tzip -p{shlex.quote(password)} {split}"
            f"{shlex.quote(str(zip_path))} {quoted}"
        )

    code, _out = await _run(cmd, cwd=workdir)
    produced = [p for p in _snapshot(out_dir) - before if p.name.startswith(f"{base}.z")]

    if code == 0 and remove:
        try:
            if source_path.is_dir():
                shutil.rmtree(source_path, ignore_errors=True)
            else:
                source_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not remove source after archiving: {exc}")

    return sorted(produced, key=lambda p: p.name)


async def extract(archive_path, out_dir, password: str = "", remove: bool = False):
    """Extract one archive into `out_dir` using unrar / tar / 7z."""
    archive_path = Path(archive_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    archive = shlex.quote(str(archive_path))
    dest = shlex.quote(str(out_dir))
    pwd = f"-p{shlex.quote(password)} " if password else ""
    lower = archive_path.name.lower()
    suffix = archive_path.suffix.lower()

    if suffix == ".rar" or _PART_RAR_RE.search(lower):
        cmd = f"unrar x -kb -idq {pwd}{archive} {dest}"
    elif lower.endswith(".tar"):
        cmd = f"tar -xvf {archive} -C {dest}"
    elif _TAR_GZ_RE.search(lower) or suffix in (".tgz", ".gz"):
        cmd = f"tar -zxf {archive} -C {dest}"
    else:
        cmd = f"7z x -y {pwd}{archive} -o{dest}"

    code, _out = await _run(cmd)
    if code == 0 and remove:
        try:
            archive_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not remove archive after extraction: {exc}")
    return code == 0


def _default_name(source_dir: Path) -> str:
    entries = list(source_dir.iterdir())
    if len(entries) == 1:
        return entries[0].name
    return source_dir.name


async def zip_handler(source_dir, out_dir, is_split=False, password="", remove=False, name=None, chunk="2000m"):
    """Zip a whole download folder into out_dir. Returns the archive parts."""
    source_dir = Path(source_dir)
    if not any(source_dir.iterdir()):
        return []
    arch_name = name or _default_name(source_dir)
    return await archive(source_dir, out_dir, is_split, password, remove, name=arch_name, chunk=chunk)


async def unzip_handler(source_dir, out_dir, password="", remove=False):
    """Extract every (primary) archive found in source_dir into out_dir.

    Returns the list of newly created files.
    """
    source_dir = Path(source_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    before = _snapshot(out_dir)

    archives = [
        p
        for p in sorted(source_dir.rglob("*"))
        if p.is_file() and is_archive(p) and _is_primary_archive(p)
    ]

    for archive_path in archives:
        await extract(archive_path, out_dir, password, remove)

    return sorted(p for p in _snapshot(out_dir) - before if p.is_file())


VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".ts"}


def is_video(path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS


async def split_video(path, max_bytes, out_dir=None):
    """Split a video into ≤max_bytes parts with ffmpeg (stream copy).

    Returns the list of produced part files, excluding the original.
    """
    path = Path(path)
    out_dir = Path(out_dir or path.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / f"{path.stem}_part%03d{path.suffix}"

    cmd = (
        f"ffmpeg -y -i {shlex.quote(str(path))} -c copy -map 0 "
        f"-f segment -segment_time 14400 -reset_timestamps 1 "
        f"-fs {int(max_bytes)} {shlex.quote(str(pattern))}"
    )
    code, _out = await _run(cmd)
    parts = sorted(out_dir.glob(f"{path.stem}_part*{path.suffix}"))
    if code != 0 or len(parts) <= 1:
        return []
    return parts
