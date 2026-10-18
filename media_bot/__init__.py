# Universal Media Bot - a Pyrogram based downloader / uploader bot.
#
# Structure mirrors the reference "Telegram-Leecher" package layout:
#   media_bot/
#     __init__.py        -> loads credentials + builds the Pyrogram client
#     __main__.py        -> bot command / callback handlers
#     downlader/         -> one module per supported source
#     uploader/          -> Telegram upload helpers
#     utility/           -> shared state, helpers, task orchestration
#     tools/             -> standalone utilities (m3u8 already lives in downlader)

import logging

from pyrogram.client import Client

from media_bot.utility.variables import Config

# Read the credentials (credentials.json in the repo root, or MEDIA_BOT_* env vars)
API_ID = Config.API_ID
API_HASH = Config.API_HASH
BOT_TOKEN = Config.BOT_TOKEN
OWNER = Config.OWNER
DUMP_ID = Config.DUMP_CHANNEL_ID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

if not API_ID or not API_HASH or not BOT_TOKEN:
    logging.warning(
        "Telegram credentials are incomplete. Copy credentials.example.json to "
        "credentials.json and fill in API_ID / API_HASH / BOT_TOKEN."
    )

# Single shared client instance for the whole application.
bot = Client("media_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
