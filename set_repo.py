#!/usr/bin/env python3
"""Point the repository at your own GitHub account.

The README badge and the Colab notebook resolve through the GitHub API, so a
placeholder owner (`your-username`) or a private repo returns:

    CustomError: Fetch for https://api.github.com/repos/... failed: {"status": 404}

Run this once after forking/creating your repo:

    python set_repo.py <owner>/<repo> [branch]

Example:

    python set_repo.py alice/universal-media-bot main

It rewrites, in place and keeping line endings intact:

  * README.md                          - the "Open in Colab" badge URL
  * main.py                            - REPO_URL (and BRANCH if given)
  * Universal_Media_Bot.ipynb          - regenerated from main.py so the two
                                         stay byte-for-byte in sync
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent

BADGE_RE = re.compile(
    r"https://colab\.research\.google\.com/github/"
    r"[^/\s]+/[^/\s]+/blob/[^/\s]+/Universal_Media_Bot\.ipynb"
)
REPO_URL_RE = re.compile(r'REPO_URL\s*=\s*"[^"]*"')
BRANCH_RE = re.compile(r'BRANCH\s*=\s*"[^"]*"')

INTRO = """# 🤖 Universal Media Bot — Colab Connector

Click **Runtime → Run all**, fill in the 🔗 repository URL and 🔑 credentials in the
form below, then run the single cell to clone the repo, install the tools and start
the bot.

[![Open In Colab]({badge})]({badge})

> The badge above resolves through the GitHub API, so it requires this repo to be
> published **publicly**. A private repo (or a placeholder owner) returns
> `404 Not Found`. Either `Upload` `Universal_Media_Bot.ipynb` to
> <https://colab.research.google.com> manually, or point `REPO_URL` at a public
> clone and supply a token.
"""


def read(path: pathlib.Path) -> str:
    # newline="" keeps the file's existing CRLF/LF bytes untouched.
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def write(path: pathlib.Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def parse_slug(argv) -> tuple:
    if len(argv) < 2:
        sys.exit(__doc__.strip())
    slug = argv[1].strip().strip("/")
    slug = slug.removeprefix("https://github.com/").removesuffix(".git")
    parts = [p for p in slug.split("/") if p]
    if len(parts) != 2:
        sys.exit(f"Expected <owner>/<repo>, got: {argv[1]!r}")
    branch = argv[2].strip() if len(argv) > 2 else "main"
    return parts[0], parts[1], branch


def main() -> int:
    owner, repo, branch = parse_slug(sys.argv)
    repo_url = f"https://github.com/{owner}/{repo}"
    badge = (
        "https://colab.research.google.com/github/"
        f"{owner}/{repo}/blob/{branch}/Universal_Media_Bot.ipynb"
    )

    changed = []

    # ---- README badge ------------------------------------------------------
    readme_path = ROOT / "README.md"
    readme = read(readme_path)
    if BADGE_RE.search(readme):
        write(readme_path, BADGE_RE.sub(badge, readme))
        changed.append("README.md (badge)")
    else:
        print("! README.md: no Colab badge URL found, skipped")

    # ---- main.py -----------------------------------------------------------
    main_path = ROOT / "main.py"
    main_src = read(main_path)
    new_src, n_repo = REPO_URL_RE.subn(f'REPO_URL = "{repo_url}"', main_src)
    new_src, n_branch = BRANCH_RE.subn(f'BRANCH = "{branch}"', new_src)
    if n_repo:
        write(main_path, new_src)
        changed.append(f"main.py (REPO_URL{f', BRANCH={branch}' if n_branch else ''})")
    else:
        print("! main.py: no REPO_URL assignment found, skipped")

    # ---- notebook (regenerated so it matches main.py) ----------------------
    if n_repo:
        src = read(main_path)
        notebook = {
            "nbformat": 4,
            "nbformat_minor": 0,
            "metadata": {
                "colab": {"provenance": [], "toc_visible": True},
                "kernelspec": {"name": "python3", "display_name": "Python 3"},
                "language_info": {"name": "python"},
            },
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {"id": "intro"},
                    "source": INTRO.format(badge=badge).splitlines(keepends=True),
                },
                {
                    "cell_type": "code",
                    "metadata": {"id": "connector", "cellView": "form"},
                    "execution_count": None,
                    "outputs": [],
                    "source": src.splitlines(keepends=True),
                },
            ],
        }
        nb_path = ROOT / "Universal_Media_Bot.ipynb"
        write(nb_path, json.dumps(notebook, indent=1, ensure_ascii=False) + "\n")
        changed.append("Universal_Media_Bot.ipynb (regenerated)")

    print(f"✅ Repo set to {owner}/{repo} (branch {branch})")
    for item in changed:
        print(f"   • {item}")
    print("\nNext: commit and push, then the README badge will open the notebook.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
