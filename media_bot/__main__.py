# Bot entry point and all Pyrogram handlers.
#
# Reference analogue: colab_leecher/__main__.py
#
# Run with:  python -m media_bot

import asyncio
import logging
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from media_bot import bot
from media_bot.utility.handler import delete_message_after_delay, log_to_dump_channel
from media_bot.utility.helper import create_gallery_config, load_trackers, parse_cookies
from media_bot.utility.task_manager import process_urls
from media_bot.utility.variables import Config, Paths, Stats, user_states

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

COMMANDS = ["start", "help", "stats", "cancel", "dl", "batch"]


def _caption_buttons():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Use Default Caption", callback_data="caption:default")],
            [InlineKeyboardButton("Set Custom Caption", callback_data="caption:custom")],
        ]
    )


# --------------------------------------------------------------------------- #
# Basic commands
# --------------------------------------------------------------------------- #
@bot.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply(
        "🤖 **Universal Media Bot**\n\n"
        "**Download Commands:**\n"
        "/dl - Download → Telegram\n"
        "/batch - Batch → Telegram\n\n"
        "**Other Commands:**\n"
        "/stats - View statistics\n"
        "/help - Detailed help\n"
        "/cancel - Cancel operation\n\n"
        "Supports 100+ sites including Twitter, GDrive, Telegram, YTDL, Mega, "
        "Torrents, Terabox, HLS/m3u8 & more!"
    )
    asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))


@bot.on_message(filters.command("help") & filters.private)
async def help_cmd(client, message):
    await message.reply(
        "📖 **Help Guide**\n\n"
        "**How to use:**\n"
        "1. Send command (/dl or /batch)\n"
        "2. Set custom caption (optional)\n"
        "3. Send URL(s) or upload .txt file\n"
        "4. Bot downloads and uploads\n\n"
        "**Supported Links:**\n"
        "• Google Drive (files)\n"
        "• Telegram (public t.me links)\n"
        "• YouTube, Twitter/X (via yt-dlp)\n"
        "• Magnet links (torrents)\n"
        "• Mega.nz (files/folders)\n"
        "• Terabox\n"
        "• HLS/m3u8 streams\n"
        "• gallery-dl / cyberdrop-dl sites\n\n"
        "**Custom Captions:** use placeholders\n"
        "• `{filename}` - File name\n"
        "• `{size}` - File size\n"
        "• `{index}` - File number\n"
        "• `{total}` - Total files"
    )
    asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))


@bot.on_message(filters.command("stats") & filters.private)
async def show_stats(client, message):
    await message.reply(
        f"📊 **Statistics**\n\n"
        f"✅ Downloads: {Stats.downloads}\n"
        f"📁 Total Files: {Stats.total_files}\n"
        f"📤 TG Uploads: {Stats.uploads}\n"
        f"❌ Failed: {Stats.failed}"
    )


@bot.on_message(filters.command("cancel") & filters.private)
async def cancel(client, message):
    chat_id = message.chat.id
    if chat_id in user_states:
        del user_states[chat_id]
        await message.reply("❌ Operation cancelled")
    else:
        await message.reply("No active operation")


# --------------------------------------------------------------------------- #
# Download commands
# --------------------------------------------------------------------------- #
@bot.on_message(filters.command(["dl"]) & filters.private)
async def single_dl(client, message):
    chat_id = message.chat.id
    user_states[chat_id] = {"mode": "single", "stage": None}
    if Config.ENABLE_CUSTOM_CAPTIONS:
        await message.reply(
            "📝 **Caption Settings**\n\nChoose caption option:", reply_markup=_caption_buttons()
        )
    else:
        user_states[chat_id].update(
            {"custom_caption": None, "after_date": None, "before_date": None, "stage": "awaiting_url"}
        )
        await message.reply("🔗 Send the URL to download")
    asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))


@bot.on_message(filters.command(["batch"]) & filters.private)
async def batch_dl(client, message):
    chat_id = message.chat.id
    user_states[chat_id] = {"mode": "batch", "stage": None}
    if Config.ENABLE_CUSTOM_CAPTIONS:
        await message.reply(
            "📝 **Caption Settings**\n\nChoose caption option:", reply_markup=_caption_buttons()
        )
    else:
        user_states[chat_id].update(
            {"custom_caption": None, "after_date": None, "before_date": None, "stage": "awaiting_urls"}
        )
        await message.reply("📝 Send multiple URLs (one per line) or upload .txt file")
    asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))


# --------------------------------------------------------------------------- #
# Callback queries (caption selection)
# --------------------------------------------------------------------------- #
@bot.on_callback_query()
async def handle_callback_query(client: Client, callback_query: CallbackQuery):
    chat_id = callback_query.message.chat.id
    data = callback_query.data
    message = callback_query.message

    if chat_id not in user_states:
        await callback_query.answer("⚠️ This operation has expired or was cancelled.", show_alert=True)
        try:
            await message.delete()
        except Exception:  # noqa: BLE001
            pass
        return

    state = user_states[chat_id]
    try:
        if data == "caption:default":
            state["custom_caption"] = None
            state["after_date"] = None
            state["before_date"] = None
            await callback_query.answer("✅ Default caption selected")
            if state["mode"] == "single":
                state["stage"] = "awaiting_url"
                await message.edit_text("🔗 Send the URL")
            else:
                state["stage"] = "awaiting_urls"
                await message.edit_text("📝 Send URLs or upload .txt file")
        elif data == "caption:custom":
            state["stage"] = "awaiting_custom_caption"
            await callback_query.answer()
            await message.edit_text(
                "✏️ **Enter custom caption**\n\n"
                "Placeholders:\n`{filename}` `{size}` `{index}` `{total}`\n\n"
                "Example: `Downloaded: {filename} ({size})`"
            )
    except MessageNotModified:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Callback query error: {exc}")
        try:
            await callback_query.answer(f"An error occurred: {exc}", show_alert=True)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# .txt file uploads (batch mode)
# --------------------------------------------------------------------------- #
@bot.on_message(filters.document & filters.private)
async def handle_file(client, message):
    chat_id = message.chat.id
    if chat_id not in user_states or user_states[chat_id].get("stage") != "awaiting_urls":
        return
    if Path(message.document.file_name).suffix.lower() != ".txt":
        await message.reply("⚠️ Please send a .txt file with URLs")
        return

    status = await message.reply("📥 Reading file...")
    asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))

    file_path = await message.download()
    file_path_p = Path(file_path)
    try:
        with open(file_path_p, "r", encoding="utf-8") as file:
            urls = [
                line.strip()
                for line in file
                if line.strip().startswith(("http://", "https://", "magnet:?"))
            ]
    except Exception as exc:  # noqa: BLE001
        await status.edit_text(f"⚠️ Error reading file: {exc}")
        return
    finally:
        if file_path_p.exists():
            file_path_p.unlink()

    asyncio.create_task(log_to_dump_channel(client, message, urls))
    if not urls:
        await status.edit_text("⚠️ No valid URLs found in file")
        asyncio.create_task(delete_message_after_delay(status, Config.MESSAGE_DELETE_DELAY))
        return

    await status.edit_text(f"✅ Found {len(urls)} URL(s). Starting...")
    await process_urls(client, message, chat_id, urls, status_msg=status)


# --------------------------------------------------------------------------- #
# Free text input (urls / captions)
# --------------------------------------------------------------------------- #
@bot.on_message(filters.text & filters.private & ~filters.command(COMMANDS))
async def handle_text_input(client, message):
    chat_id = message.chat.id
    if chat_id not in user_states:
        return

    state = user_states[chat_id]
    stage = state.get("stage")

    if stage == "awaiting_custom_caption":
        custom_caption = message.text.strip()
        if len(custom_caption) > 1024:
            await message.reply("⚠️ Caption too long (max 1024 chars)")
            return
        state["custom_caption"] = custom_caption
        bot_reply = await message.reply(f"✅ Caption set: `{custom_caption[:100]}`")
        asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))
        asyncio.create_task(delete_message_after_delay(bot_reply, Config.MESSAGE_DELETE_DELAY))
        state["after_date"] = None
        state["before_date"] = None
        if state["mode"] == "single":
            state["stage"] = "awaiting_url"
            await message.reply("🔗 Send the URL")
        else:
            state["stage"] = "awaiting_urls"
            await message.reply("📝 Send URLs or upload .txt file")

    elif stage == "awaiting_url":
        url = message.text.strip()
        if not url.startswith(("http://", "https://", "magnet:?")):
            bot_reply = await message.reply(
                "⚠️ Invalid URL. Must start with http://, https://, or magnet:?"
            )
            asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))
            asyncio.create_task(delete_message_after_delay(bot_reply, Config.MESSAGE_DELETE_DELAY))
            return
        asyncio.create_task(log_to_dump_channel(client, message, [url]))
        asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))
        status_msg = await message.reply("🚀 Processing 1 URL(s)...")
        await process_urls(client, message, chat_id, [url], status_msg=status_msg)

    elif stage == "awaiting_urls":
        urls = [
            line.strip()
            for line in message.text.split("\n")
            if line.strip().startswith(("http://", "https://", "magnet:?"))
        ]
        if not urls:
            bot_reply = await message.reply(
                "⚠️ No valid URLs found. Send URLs starting with http://, https://, or magnet:?"
            )
            asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))
            asyncio.create_task(delete_message_after_delay(bot_reply, Config.MESSAGE_DELETE_DELAY))
            return
        asyncio.create_task(log_to_dump_channel(client, message, urls))
        status_msg = await message.reply(f"✅ Found {len(urls)} URL(s). Starting...")
        asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))
        await process_urls(client, message, chat_id, urls, status_msg=status_msg)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
async def main():
    Paths.DOWN_PATH.mkdir(parents=True, exist_ok=True)

    twitter_cookies = parse_cookies(Config.TWITTER_COOKIES)
    try:
        create_gallery_config(twitter_cookies)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not create gallery-dl config: {exc}")
    await asyncio.to_thread(load_trackers)

    await bot.start()
    me = await bot.get_me()
    print(f"\n{'=' * 60}\n🤖 Bot @{me.username} is running!\n{'=' * 60}")
    print(f"🍪 Twitter Auth: {'✅ Configured' if twitter_cookies.get('auth_token') else '❌ Missing'}")
    print(f"⚙️  Auto Cleanup: {'✅' if Config.AUTO_CLEANUP else '❌'}")
    print(f"📸 Album Mode: {'✅' if Config.SEND_AS_ALBUM else '❌'}")
    print(f"📝 Custom Captions: {'✅' if Config.ENABLE_CUSTOM_CAPTIONS else '❌'}")
    print(f"📥 Downloads: {Paths.DOWN_PATH}")
    print(f"{'=' * 60}\n🚀 Ready to accept commands!\n{'=' * 60}\n")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        print("\n⏹️  Stopping bot...")
    finally:
        await bot.stop()
        print("✅ Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
