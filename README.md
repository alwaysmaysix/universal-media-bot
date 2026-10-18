# 🤖 Universal Media Bot

A Pyrogram-based Telegram bot that downloads from many sources and re-uploads
the files to Telegram (or a dump channel). The code is organised as a Python
package that mirrors the layout of the classic **Telegram-Leecher** project,
one module per responsibility.

> ⚠️ Deploying download bots like this on Google Colab goes against Colab's
> policy (torrents, media serving, remote proxies). Use a VPS if you plan to
> keep it running.

---

## ✨ Features

- Simple bot commands: `/dl`, `/batch`, `/stats`, `/help`, `/cancel`
- Custom captions with `{filename}` `{size}` `{index}` `{total}` placeholders
- Album (media group) uploads for image batches
- Auto thumbnail generation for videos
- Auto cleanup of temporary download folders
- Optional dump-channel logging of every processed URL
- Rich live progress display for every download engine

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
| BaddieHub pages | custom scraper + cyberdrop-dl |

---

## 🗂️ Project structure

```
universal-media-bot/
├── main.py                 # Google Colab entry point (clone, install, run)
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
    │   ├── variables.py     # Config / Paths / Stats / shared state
    │   ├── helper.py        # progress display, captions, thumbnails, scraping
    │   ├── handler.py       # message cleanup + dump-channel logging
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
apt-get install -y ffmpeg megatools     # Debian/Ubuntu
# brew install ffmpeg megatools         # macOS
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
| `DUMP_CHANNEL_ID` | channel to upload/log to (`0` = upload to the user chat) |
| `TWITTER_COOKIES` | JSON list of `{name, value}` cookies for Twitter/X |
| `DOWNLOAD_PATH` | where files are downloaded (default `./Downloads`) |

Every key can also be supplied through an environment variable prefixed with
`MEDIA_BOT_` (e.g. `MEDIA_BOT_BOT_TOKEN`), which overrides `credentials.json`.

`credentials.json` is **git-ignored** — never commit it.

### 3. Run

```bash
python -m media_bot
```

Or open `main.py` in Google Colab, fill the `@param` fields and run the cell.

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

1. Send `/dl` (single) or `/batch` (multiple URLs).
2. Choose a caption: default, or a custom template with placeholders.
3. Send the URL(s) — one per line — or upload a `.txt` file with one URL per line.
4. The bot downloads, then uploads each file (albums for image batches).

---

## ⚖️ License

Released under the **GNU General Public License v3.0** (see `LICENSE`).

Portions of the download/upload architecture and the yt-dlp / mega / terabox
logic are adapted from [XronTrix10/Telegram-Leecher](https://github.com/XronTrix10/Telegram-Leecher)
(GPL-3.0). M3U8 downloader logic was adapted from the original `NEW MEDIA.ipynb`.
