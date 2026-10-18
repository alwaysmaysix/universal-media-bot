# 🤖 Universal Media Bot

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/alwaysmaysix/universal-media-bot/blob/main/Universal_Media_Bot.ipynb)

> ▶️ **Run in Colab** — the badge above opens
> [`Universal_Media_Bot.ipynb`](Universal_Media_Bot.ipynb), the ready-to-run
> connector (clone repo → install tools → write credentials → start bot).
>
> ⚠️ **The badge only works once this repo is public at the URL above.** Colab
> resolves the notebook through the GitHub API, so a placeholder owner (or a
> *private* repo) fails with `CustomError: ... {"status": 404}`. Set your account
> once with:
>
> ```bash
> python set_repo.py <owner>/<repo>        # e.g. python set_repo.py alice/universal-media-bot
> ```
>
> Not published yet? Open <https://colab.research.google.com>, choose **Upload**
> and drop in `Universal_Media_Bot.ipynb` — the bot still needs `REPO_URL` to
> point at a repo Colab can clone.

A Pyrogram-based Telegram bot that downloads from many sources and re-uploads
the files to Telegram (or a dump channel). The code is organised as a Python
package that mirrors the layout of the classic **Telegram-Leecher** project,
one module per responsibility.

> ⚠️ Deploying download bots like this on Google Colab goes against Colab's
> policy (torrents, media serving, remote proxies). Use a VPS if you plan to
> keep it running.

---

## ✨ Features

- Simple bot commands: `/dl`, `/batch`, `/settings`, `/history`, `/queue`,
  `/status`, `/stats`, `/help`, `/cancel`
- Also works **without a command**: just send a link, or use **inline mode**
  (`@yourbot <link>`)
- **Per-user settings keyboard** (persisted in SQLite):
  engine, archive action, yt-dlp format, caption font, upload kind, split
  options, prefix/suffix, custom thumbnail, destination and cookies
- **Manual engines**: force `auto`, `gallery-dl`, `cyberdrop-dl`, `aria2c` or `megadl`
- **Zip / Unzip**: compress, extract, or unzip-then-zip (split archives + passwords)
- **Split oversized videos** with ffmpeg so they fit the Telegram limit
- **Access control**: `ALLOWED_USERS` allowlist, owner-only commands and a
  per-user rate limit
- **Real cancellation**: `/cancel` (or the ✘ Cancel button) kills the running
  subprocesses, not just the state
- **Quotas** per day (files / GB) and **download history** with `/redo`
- **Per-site cookies** (Twitter, Instagram, TikTok, Reddit, Pixiv, Facebook)
- **Configurable fallback chain** for unknown links
- **Torrent file selection** (list a magnet's files, download only some)
- Album (media group) uploads, auto thumbnails, auto cleanup, dump-channel logging
- Rich live progress display for every download engine **and** for uploads
  (same ⬢⬡ Task/Status/Done/Speed/ETA/Past/User layout)

### Commands

| Command | Description |
| --- | --- |
| `/dl` / `/batch` | Single / batch download to Telegram |
| `/settings` | All per-user options (engine, zip, format, cookies, …) |
| `/history` | Last 10 downloads with one-tap **Redo** |
| `/redo <id>` | Re-run a history entry |
| `/queue` | Running downloads |
| `/status` | Your settings, destination and today's quota |
| `/cancel` | Cancel **your** running download (kills processes) |
| `/cancelall` | Owner only — cancel everything |
| `/broadcast <text>` | Owner only — message all known users |
| `/stats`, `/help`, `/start` | Statistics / help / welcome |

### 📊 Progress display

Downloads and uploads share the same live `⬢⬡` layout, refreshed per status
message (so concurrent users don't delay each other's updates):

```
#Task: [1/3] https://example.com/gallery
➜ ⬢⬢⬢⬢⬡⬡⬡⬡⬡⬡ » 42.0%
➜ Status : Download 📥 (gallery-dl)
➜ Done   : 15.0 MB of 35.7 MB
➜ Speed  : 2.3 MB/s
➜ ETA    : 00:15
➜ Past   : 0h0m12s
➜ User   : Alice
```

| Engine | Progress source |
| --- | --- |
| `gdrive`, `telegram`, `magnet`, `mega`, `ytdl`, `aria2c`, `gallery-dl` | real bytes / percentage |
| `m3u8` (HLS) | segment count (`12/40 segments`) |
| `cyberdrop-dl` | files landed on disk (its CLI UI is disabled) |

Each engine has its own throttle (≈2 s, 3 s for uploads) and every update runs
per-chat, so one user's fast download no longer starves another's.

## 🔗 Supported sources

| Source | Engine |
| --- | --- |
| Google Drive (files) | Drive API v3 (`token.json`) |
| Telegram (`t.me/...`) | Pyrogram |
| YouTube / Twitter-X / 1800+ sites | yt-dlp |
| Magnet / torrent | libtorrent |
| Mega.nz | `megadl` |
| Terabox | resolver API → direct link |
| HLS / `m3u8` streams | built-in segment downloader + `ffmpeg` |
| Most image/video galleries | gallery-dl |
| Most direct hosts | cyberdrop-dl |
| Any direct link (multi-connection) | `aria2c` |
| BaddieHub pages | custom scraper + cyberdrop-dl |

---

## 🗂️ Project structure

```
universal-media-bot/
├── Universal_Media_Bot.ipynb  # the Colab badge target (same code as main.py)
├── main.py                 # Google Colab entry point (clone, install, run)
├── set_repo.py             # one-shot: point README/main.py/notebook at your repo
├── credentials.example.json
├── requirements.txt
├── custom_thmb.jpg         # default thumbnail
├── LICENSE                 # GPL-3.0
└── media_bot/
    ├── __init__.py         # loads credentials, builds the Pyrogram client
    ├── __main__.py         # bot handlers + entry point (`python -m media_bot`)
    ├── downlader/
    │   ├── manager.py       # master dispatcher + downloadManager()
    │   ├── gallerydl.py     # gallery-dl engine
    │   ├── cyberdrop.py     # cyberdrop-dl engine
    │   ├── aria2c.py        # aria2c engine (manual selection)
    │   ├── baddiehub.py     # BaddieHub scraper
    │   ├── gdrive.py        # Google Drive
    │   ├── telegram.py      # t.me links
    │   ├── ytdl.py          # yt-dlp
    │   ├── magnet.py        # libtorrent
    │   ├── mega.py          # megadl
    │   ├── terabox.py       # Terabox resolver
    │   └── m3u8.py          # HLS/m3u8 downloader (also a CLI)
    ├── uploader/
    │   └── telegram.py      # upload_to_telegram / album uploads
    ├── utility/
    │   ├── variables.py     # Config / Paths / Prefs / shared state
    │   ├── store.py         # SQLite: prefs, stats, history, quotas
    │   ├── runtime.py       # task + subprocess registry, cancellation
    │   ├── security.py      # allowlist, owner-only, rate limiting
    │   ├── helper.py        # progress display, captions, cookies, thumbnails
    │   ├── handler.py       # message cleanup + dump-channel logging
    │   ├── converters.py    # zip / unzip / split-video helpers
    │   └── task_manager.py  # process_urls() request lifecycle
    └── tools/
        ├── code_cleaner.py  # strip selected blocks from a source file
        └── ytdlp_runner.py  # standalone yt-dlp runner
```

---

## 🚀 Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt

# system tools:
apt-get install -y ffmpeg megatools aria2 p7zip-full unrar-free   # Debian/Ubuntu
# brew install ffmpeg megatools aria2 p7zip unar                    # macOS
```

### 2. Provide credentials

Copy the example file and fill it in:

```bash
cp credentials.example.json credentials.json
```

| Key | Meaning |
| --- | --- |
| `API_ID`, `API_HASH` | from <https://my.telegram.org> |
| `BOT_TOKEN` | from [@BotFather](https://t.me/BotFather) |
| `OWNER` | your Telegram user id (unlocks owner commands) |
| `DUMP_CHANNEL_ID` | channel to upload/log to (`0` = upload to the user chat) |
| `ALLOWED_USERS` | list of user ids allowed to use the bot (`[]` = open to everyone) |
| `RATE_LIMIT_SECONDS` | cooldown between downloads per user (`0` = off) |
| `QUOTA_FILES_PER_DAY`, `QUOTA_GB_PER_DAY` | daily limits per user (`0` = unlimited) |
| `RESUME` | resume partial downloads where the engine supports it |
| `SPLIT_SIZE_MB` | part size for split archives / split videos |
| `FALLBACK_CHAIN` | order of generic engines, e.g. `["gallerydl","cyberdrop","aria2c"]` |
| `TWITTER_COOKIES` | JSON list of `{name, value}` cookies for Twitter/X |
| `DOWNLOAD_PATH` | where files are downloaded (default `./Downloads`) |

Every key can also be supplied through an environment variable prefixed with
`MEDIA_BOT_` (e.g. `MEDIA_BOT_BOT_TOKEN`), which overrides `credentials.json`.

`credentials.json` is **git-ignored** — never commit it. The SQLite database
(`media_bot.db`), `cookies/` and `thumbs/` are ignored too.

### 3. Run

```bash
python -m media_bot
```

Or click the **Open in Colab** badge at the top of this README — it opens
[`Universal_Media_Bot.ipynb`](Universal_Media_Bot.ipynb), fill the `@param`
fields and run the cell. `main.py` contains the exact same connector code if you
prefer to paste it into a blank notebook yourself.

> 🔁 To use your own repo, edit the badge URL in this README (and `REPO_URL` in
> the notebook) to point at `github.com/<you>/<repo>`.

---

## 🧰 Standalone tools

```bash
# Download a single HLS/m3u8 stream
python -m media_bot.downlader.m3u8 "<m3u8 url>" output.mp4

# One-off yt-dlp download
python -m media_bot.tools.ytdlp_runner "<url>" ./Downloads

# Strip selected blocks (e.g. a removed feature) from a source file
python -m media_bot.tools.code_cleaner New_Text_Document.txt bot_cleaned.py
```

---

## 📖 Usage

1. Send `/dl` (single) or `/batch` (multiple URLs) — or just paste a link.
2. Choose a caption — default, custom template — or open **⚙️ Download Options**.
3. Send the URL(s) — one per line — or upload a `.txt` file with one URL per line.
4. The bot downloads, applies the chosen archive action, then uploads the files.
5. Press **✘ Cancel** on the status message to abort at any time.

### ⚙️ Settings keyboard (`/settings`)

| Button | What it does |
| --- | --- |
| 🎛 Download Engine | Force `auto`, `gallery-dl`, `cyberdrop-dl`, `aria2c` or `megadl` |
| 🗜 Archive Action | `Regular` · `Compress` · `Extract` · `Unzip then Zip` |
| 🎬 Video Format | yt-dlp quality: best / 1080p / 720p / 480p / smallest / audio |
| 🔤 Caption Font | default / bold / monospace / spoiler |
| 📤 Upload | Send files as media (streamable) or as documents |
| 🍪 Cookies | Per-site Netscape cookies for gallery-dl / yt-dlp |
| ✂️ Split Zip / 🎬 Split Video | Split archives / oversized videos into parts |
| 🔐 / 🔓 Password | Set (or clear) the zip / unzip password |
| 🔗 Fallback Chain | Which generic engines Auto may try, and in what order |
| 📂 Torrent Files | List a magnet's files and download only chosen indices |
| 🖼 Thumbnail | Send a photo to use as your custom video thumbnail |
| 🎯 Destination | Upload to a specific chat/channel instead of the default |
| ✏️ Prefix / Suffix | Extra text prepended / appended to every caption |
| ♻️ Reset Defaults / ✘ Close | Restore defaults / close the menu |

Settings are **per chat** and stored in SQLite, so they survive restarts. Zip and
unzip output is always uploaded as documents.

---

## ⚖️ License

Released under the **GNU General Public License v3.0** (see `LICENSE`).

Portions of the download/upload architecture and the yt-dlp / mega / terabox
logic are adapted from [XronTrix10/Telegram-Leecher](https://github.com/XronTrix10/Telegram-Leecher)
(GPL-3.0). M3U8 downloader logic was adapted from the original `NEW MEDIA.ipynb`.
