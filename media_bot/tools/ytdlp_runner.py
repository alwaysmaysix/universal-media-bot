# Standalone yt-dlp runner.
#
# Ported from the notebook's subprocess-based yt-dlp cell. It is handy for
# one-off downloads / debugging without a running bot.
#
# CLI:
#     python -m media_bot.tools.ytdlp_runner "<url>" [output_dir] [--cookies cookies.txt]

import argparse
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
)


def run_ytdlp(url, out_dir, cookies_file=None, use_cookies=False, user_agent=DEFAULT_USER_AGENT):
    """Download `url` into `out_dir` with yt-dlp. Returns the subprocess result."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp",
        url,
        "-o",
        str(out_dir / "%(title)s.%(ext)s"),
        "--no-check-certificates",
        "--concurrent-fragments",
        "4",
        "--merge-output-format",
        "mp4",
    ]

    if use_cookies:
        if not cookies_file or not Path(cookies_file).exists():
            raise FileNotFoundError(
                f"Cookies file not found: {cookies_file}. Upload it or set use_cookies=False."
            )
        cmd += ["--cookies", str(cookies_file)]

    cmd += ["--user-agent", user_agent]

    print("Running:", " ".join(cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print("\n==== yt-dlp STDOUT ====\n", proc.stdout.decode(errors="replace"))
    print("\n==== yt-dlp STDERR ====\n", proc.stderr.decode(errors="replace"))
    print("\nExit code:", proc.returncode)
    print("\nFiles in output dir:")
    for path in sorted(out_dir.glob("*")):
        print(" -", path.name)
    return proc


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run yt-dlp on a single URL.")
    parser.add_argument("url", help="video/page URL")
    parser.add_argument("out_dir", nargs="?", default="Downloads", help="output directory")
    parser.add_argument("--cookies", default=None, help="path to a cookies.txt file")
    parser.add_argument(
        "--use-cookies", action="store_true", help="pass the cookies file to yt-dlp"
    )
    args = parser.parse_args(argv)

    try:
        proc = run_ytdlp(
            args.url, args.out_dir, cookies_file=args.cookies, use_cookies=args.use_cookies
        )
    except FileNotFoundError as exc:
        print(f"❌ {exc}")
        return 1
    return 0 if proc.returncode == 0 else proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
