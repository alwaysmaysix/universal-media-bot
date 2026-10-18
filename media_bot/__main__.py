# Bot entry point and all Pyrogram handlers.
#
# Reference analogue: colab_leecher/__main__.py
#
# Inline keyboards mirror the reference "send_settings" menu (engine, archive
# action, upload kind, prefix/suffix, thumbnail, caption font) scoped per chat,
# plus the extras added here: yt-dlp format, fallback chain, cookies, torrent
# file selection, destination and quotas.

import asyncio
import logging
import re
import secrets
import time
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from media_bot import bot
from media_bot.utility import runtime, security, store
from media_bot.utility.handler import delete_message_after_delay, log_to_dump_channel
from media_bot.utility.helper import (
    build_user_cookie_file,
    cookie_file_for,
    create_gallery_config,
    load_trackers,
    parse_cookies,
    set_cookie_file,
)
from media_bot.utility.task_manager import cancel_keyboard, start_task
from media_bot.utility.variables import (
    ACTION_LABELS,
    COOKIE_SITES,
    ENGINE_LABELS,
    FONT_LABELS,
    FORMAT_LABELS,
    Config,
    Paths,
    Stats,
    get_prefs,
    save_prefs,
    user_states,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

COMMANDS = [
    "start", "help", "stats", "cancel", "cancelall", "dl", "batch", "settings",
    "history", "redo", "queue", "status", "broadcast",
]

URL_RE = re.compile(r"(https?://[^\s]+|magnet:\?[^\s]+)")
CHAIN_ENGINES = ["gallerydl", "cyberdrop", "aria2c"]

# Short-lived map so inline results can carry a URL without blowing the
# 64-byte Telegram callback_data limit.
_INLINE_URLS = {}


def _store_inline_url(url: str) -> str:
    token = secrets.token_hex(4)
    _INLINE_URLS[token] = (url, time.time())
    now = time.time()
    for key, (_, created) in list(_INLINE_URLS.items()):
        if now - created > 3600:
            _INLINE_URLS.pop(key, None)
    return token


def _btn(label, data):
    return InlineKeyboardButton(label, callback_data=data)


def _mark(current, value):
    return "✅ " if current == value else ""


def _caption_buttons():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Use Default Caption", callback_data="caption:default")],
            [InlineKeyboardButton("Set Custom Caption", callback_data="caption:custom")],
            [InlineKeyboardButton("⚙️ Download Options", callback_data="caption:options")],
        ]
    )


# --------------------------------------------------------------------------- #
# Settings screens
# --------------------------------------------------------------------------- #
def _settings_view(prefs, chat_id, screen="main"):
    if screen == "engine":
        rows = [
            [_btn(f"{_mark(prefs.engine, 'auto')}🌐 Auto (Smart)", "engine:auto")],
            [
                _btn(f"{_mark(prefs.engine, 'gallerydl')}📦 gallery-dl", "engine:gallerydl"),
                _btn(f"{_mark(prefs.engine, 'cyberdrop')}☁️ cyberdrop-dl", "engine:cyberdrop"),
            ],
            [
                _btn(f"{_mark(prefs.engine, 'aria2c')}⚡ aria2c", "engine:aria2c"),
                _btn(f"{_mark(prefs.engine, 'mega')}💾 megadl", "engine:mega"),
            ],
            [_btn("⬅ Back", "menu:main")],
        ]
        return (
            "🎛 **Download Engine**\n\n"
            "Force a downloader for every link, or let **Auto** decide:\n"
            "• gallery-dl — 100+ image/board sites\n"
            "• cyberdrop-dl — cyberdrop / bunkr hosts\n"
            "• aria2c — direct links (multi-connection)\n"
            "• megadl — mega.nz",
            InlineKeyboardMarkup(rows),
        )

    if screen == "action":
        rows = [
            [_btn(f"{_mark(prefs.action, 'normal')}📄 Regular", "action:normal")],
            [
                _btn(f"{_mark(prefs.action, 'zip')}🗜 Compress (zip)", "action:zip"),
                _btn(f"{_mark(prefs.action, 'unzip')}📂 Extract (unzip)", "action:unzip"),
            ],
            [_btn(f"{_mark(prefs.action, 'undzip')}🔁 Unzip then Zip", "action:undzip")],
            [_btn("⬅ Back", "menu:main")],
        ]
        return (
            "🗜 **Archive Action**\n\n"
            "• Regular — upload files as-is\n"
            "• Compress — zip everything into one archive\n"
            "• Extract — unzip downloaded archives\n"
            "• Unzip then Zip — extract, then re-zip the contents",
            InlineKeyboardMarkup(rows),
        )

    if screen == "format":
        rows = [
            [_btn(f"{_mark(prefs.ytdl_format, key)}{label}", f"format:{key}")]
            for key, label in FORMAT_LABELS.items()
        ]
        rows.append([_btn("⬅ Back", "menu:main")])
        return (
            "🎬 **Video Format (yt-dlp)**\n\n"
            "Quality used for YouTube / Twitter / other yt-dlp sites.",
            InlineKeyboardMarkup(rows),
        )

    if screen == "font":
        rows = [
            [_btn(f"{_mark(prefs.caption_font, key)}{label}", f"font:{key}")]
            for key, label in FONT_LABELS.items()
        ]
        rows.append([_btn("⬅ Back", "menu:main")])
        return (
            "🔤 **Caption Font**\n\n"
            "How captions are styled before upload.",
            InlineKeyboardMarkup(rows),
        )

    if screen == "chain":
        rows = []
        for engine in CHAIN_ENGINES:
            on = engine in prefs.fallback
            rows.append([_btn(f"{'✅' if on else '⬜'} {ENGINE_LABELS.get(engine, engine)}", f"chain:{engine}")])
        rows.append([_btn("⬅ Back", "menu:main")])
        return (
            "🔗 **Generic Fallback Chain**\n\n"
            "Order for links Auto can't classify: gallery-dl → cyberdrop-dl → "
            "aria2c. Toggle which engines may be used.",
            InlineKeyboardMarkup(rows),
        )

    if screen == "cookies":
        rows = []
        for site in COOKIE_SITES:
            have = cookie_file_for(chat_id, site).exists()
            rows.append([_btn(f"{'✅' if have else '🍪'} {site.capitalize()}", f"cookie:{site}")])
        rows.append([_btn("🗑 Clear all cookies", "cookie:clear")])
        rows.append([_btn("⬅ Back", "menu:main")])
        return (
            "🍪 **Cookies**\n\n"
            "Send a Netscape cookie list (JSON `[{\"name\":..,\"value\":..}]`) for a "
            "site so it can be used by gallery-dl / yt-dlp.",
            InlineKeyboardMarkup(rows),
        )

    # main
    upload = "🖼 Media" if prefs.stream_upload else "📁 Document"
    text = (
        "⚙️ **Download Settings**\n\n"
        f"╭ Engine  »  {ENGINE_LABELS.get(prefs.engine, prefs.engine)}\n"
        f"├ Action  »  {ACTION_LABELS.get(prefs.action, prefs.action)}\n"
        f"├ Format  »  {FORMAT_LABELS.get(prefs.ytdl_format, prefs.ytdl_format)}\n"
        f"├ Font    »  {FONT_LABELS.get(prefs.caption_font, prefs.caption_font)}\n"
        f"├ Upload  »  {upload}\n"
        f"├ Split   »  zip {'on' if prefs.is_split else 'off'} / video {'on' if prefs.split_video else 'off'}\n"
        f"├ Prefix  »  {prefs.prefix or '—'}\n"
        f"├ Suffix  »  {prefs.suffix or '—'}\n"
        f"├ Dest    »  {prefs.destination or 'default'}\n"
        f"├ Cookies »  {'yes' if build_user_cookie_file(chat_id) else 'none'}\n"
        f"╰ Torrent »  {prefs.torrent_files or 'all'}"
    )
    rows = [
        [_btn("🎛 Download Engine ▸", "menu:engine")],
        [_btn("🗜 Archive Action ▸", "menu:action")],
        [_btn("🎬 Video Format ▸", "menu:format"), _btn("🔤 Caption Font ▸", "menu:font")],
        [_btn(f"📤 Upload: {upload}", "pref:upload"), _btn("🍪 Cookies ▸", "menu:cookies")],
        [
            _btn(f"✂️ Split Zip: {'On' if prefs.is_split else 'Off'}", "pref:split_zip"),
            _btn(f"🎬 Split Video: {'On' if prefs.split_video else 'Off'}", "pref:split_video"),
        ],
        [_btn("🔐 Zip Password", "pref:zip_pass"), _btn("🔓 Unzip Password", "pref:unzip_pass")],
        [_btn("🔗 Fallback Chain ▸", "menu:chain"), _btn("📂 Torrent Files", "set:torrent_files")],
        [_btn("🖼 Thumbnail", "set:thumbnail"), _btn("🎯 Destination", "set:destination")],
        [_btn("✏️ Prefix", "set:prefix"), _btn("✏️ Suffix", "set:suffix")],
        [_btn("♻️ Reset Defaults", "pref:reset"), _btn("✘ Close", "pref:close")],
    ]
    return text, InlineKeyboardMarkup(rows)


def _next_stage(state):
    mode = state.get("mode")
    if mode == "single":
        return "awaiting_url"
    if mode == "batch":
        return "awaiting_urls"
    return None


def _stage_prompt(stage):
    if stage == "awaiting_url":
        return "🔗 Send the URL"
    if stage == "awaiting_urls":
        return "📝 Send URLs or upload .txt file"
    return "✅ Saved"


def _check_rate(message) -> bool:
    """Returns True when the user may start a download."""
    user = message.from_user
    remaining = security.cooldown_remaining(user.id)
    if remaining > 0:
        asyncio.create_task(
            message.reply(f"⏳ Please wait {remaining:.0f}s before the next download.")
        )
        return False
    security.touch(user.id)
    return True


# --------------------------------------------------------------------------- #
# Basic commands
# --------------------------------------------------------------------------- #
@bot.on_message(filters.command("start") & filters.private)
@security.restricted
async def start(client, message):
    await message.reply(
        "🤖 **Universal Media Bot**\n\n"
        "**Download Commands:**\n"
        "/dl - Download → Telegram\n"
        "/batch - Batch → Telegram\n"
        "• just send a link and I'll grab it\n\n"
        "**Other Commands:**\n"
        "/settings - Engine, zip/unzip, cookies & more\n"
        "/history - Recent downloads\n"
        "/queue - Running downloads\n"
        "/status - Your settings & quota\n"
        "/stats - View statistics\n"
        "/help - Detailed help\n"
        "/cancel - Cancel your running download"
    )
    asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))


@bot.on_message(filters.command("help") & filters.private)
@security.restricted
async def help_cmd(client, message):
    await message.reply(
        "📖 **Help Guide**\n\n"
        "**How to use:**\n"
        "1. Just send a link, or use /dl (single) / /batch (many)\n"
        "2. Set caption / options (optional)\n"
        "3. Send URL(s) or upload a .txt file\n\n"
        "**Inline:** type `@thisbot <link>` in any chat.\n\n"
        "**Download options** (/settings):\n"
        "• Force an engine: auto · gallery-dl · cyberdrop-dl · aria2c · megadl\n"
        "• Archive action: regular · zip · unzip · unzip+zip\n"
        "• yt-dlp format, caption font, prefix/suffix, custom thumbnail\n"
        "• Fallback chain, per-site cookies, torrent file selection\n"
        "• Upload as media/document, split archives or videos, set passwords\n\n"
        "**Custom Captions:** `{filename}` `{size}` `{index}` `{total}`"
    )
    asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))


@bot.on_message(filters.command("stats") & filters.private)
@security.restricted
async def show_stats(client, message):
    global_stats = store.get_stats(0)
    quota = store.get_quota(message.chat.id)
    lines = [
        "📊 **Statistics**",
        "",
        f"✅ Downloads: {global_stats.get('downloads', 0)}",
        f"📁 Total files: {global_stats.get('total_files', 0)}",
        f"📤 TG uploads: {global_stats.get('uploads', 0)}",
        f"❌ Failed: {global_stats.get('failed', 0)}",
        f"💾 Transferred: {global_stats.get('bytes', 0) / 1024**3:.2f} GB",
        "",
        f"👤 **Your quota today:** {quota.get('files', 0)} files / {quota.get('bytes', 0) / 1024**3:.2f} GB",
    ]
    await message.reply("\n".join(lines))


@bot.on_message(filters.command("cancel") & filters.private)
@security.restricted
async def cancel(client, message):
    chat_id = message.chat.id
    killed = await runtime.cancel_chat(chat_id)
    user_states.pop(chat_id, None)
    if killed:
        await message.reply(f"⛔ Cancelled (stopped {killed} process(es)).")
    else:
        await message.reply("No active download to cancel.")


@bot.on_message(filters.command("cancelall") & filters.private)
@security.owner_only
async def cancelall(client, message):
    killed, tasks = await runtime.cancel_all()
    await message.reply(f"⛔ Cancelled {tasks} task(s), stopped {killed} process(es).")


@bot.on_message(filters.command("queue") & filters.private)
@security.restricted
async def queue_cmd(client, message):
    chats = runtime.active_chats()
    if not chats:
        await message.reply("📭 No downloads are running.")
        return
    if security.is_owner(message.from_user.id):
        await message.reply("🏃 **Active tasks:**\n" + "\n".join(f"• `{c}`" for c in chats))
    else:
        running = message.chat.id in chats
        await message.reply("🏃 Your download is running." if running else "📭 No downloads are running.")


@bot.on_message(filters.command("status") & filters.private)
@security.restricted
async def status_cmd(client, message):
    chat_id = message.chat.id
    prefs = get_prefs(chat_id)
    quota = store.get_quota(chat_id)
    await message.reply(
        "🧭 **Your Status**\n\n"
        f"• Engine: {ENGINE_LABELS.get(prefs.engine, prefs.engine)}\n"
        f"• Action: {ACTION_LABELS.get(prefs.action, prefs.action)}\n"
        f"• Format: {FORMAT_LABELS.get(prefs.ytdl_format, prefs.ytdl_format)}\n"
        f"• Upload: {'Media' if prefs.stream_upload else 'Document'}\n"
        f"• Destination: {prefs.destination or 'default'}\n"
        f"• Running: {'yes' if chat_id in runtime.active_chats() else 'no'}\n"
        f"• Quota today: {quota.get('files', 0)} files / {quota.get('bytes', 0) / 1024**3:.2f} GB"
    )


@bot.on_message(filters.command("history") & filters.private)
@security.restricted
async def history_cmd(client, message):
    rows = store.list_history(message.chat.id, 10)
    if not rows:
        await message.reply("📭 No download history yet.")
        return
    lines = ["🕘 **Recent downloads**", ""]
    buttons = []
    for row in rows:
        when = (row.get("created_at") or "")[:19].replace("T", " ")
        urls = row.get("urls") or []
        first = urls[0][:45] if urls else "(none)"
        lines.append(
            f"`#{row['id']}` {when} — {row.get('files', 0)} files, "
            f"{row.get('uploaded', 0)} up [{row.get('status')}]"
        )
        if urls:
            buttons.append([_btn(f"🔁 Redo #{row['id']}", f"redo:{row['id']}")])
    buttons.append([_btn("✘ Close", "pref:close")])
    await message.reply("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


@bot.on_message(filters.command("redo") & filters.private)
@security.restricted
async def redo_cmd(client, message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        await message.reply("Usage: `/redo <history id>` (see /history)")
        return
    await _redo(client, message, message.chat.id, int(message.command[1]))


@bot.on_message(filters.command("broadcast") & filters.private)
@security.owner_only
async def broadcast(client, message):
    if len(message.command) < 2 and not message.reply_to_message:
        await message.reply("Usage: `/broadcast <text>` (or reply to a message)")
        return
    text = message.text.split(None, 1)[1] if len(message.command) >= 2 else None
    sent = 0
    for chat_id in store.all_chat_ids():
        if not chat_id or chat_id > 0 and chat_id == message.chat.id:
            continue
        try:
            if text:
                await client.send_message(chat_id, f"📣 {text}")
            elif message.reply_to_message:
                await message.reply_to_message.copy(chat_id)
            sent += 1
            await asyncio.sleep(0.3)
        except Exception:  # noqa: BLE001
            continue
    await message.reply(f"📣 Broadcast sent to {sent} chat(s).")


async def _redo(client, message, chat_id, entry_id):
    entry = store.get_history(entry_id)
    if not entry or entry.get("chat_id") != chat_id:
        await message.reply("⚠️ History entry not found.")
        return
    urls = entry.get("urls") or []
    if not urls:
        await message.reply("⚠️ That entry has no URLs to redo.")
        return
    if not _check_rate(message):
        return
    status = await message.reply(
        f"🔁 Redoing #{entry_id} ({len(urls)} URL(s))...", reply_markup=cancel_keyboard()
    )
    await start_task(client, message, chat_id, urls, status_msg=status)


@bot.on_message(filters.command("settings") & filters.private)
@security.restricted
async def settings_cmd(client, message):
    chat_id = message.chat.id
    user_states.setdefault(chat_id, {"mode": None, "stage": None})
    prefs = get_prefs(chat_id)
    text, markup = _settings_view(prefs, chat_id, "main")
    await message.reply(text, reply_markup=markup)
    asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))


# --------------------------------------------------------------------------- #
# Download commands
# --------------------------------------------------------------------------- #
async def _begin(mode, client, message):
    chat_id = message.chat.id
    user_states[chat_id] = {"mode": mode, "stage": None}
    get_prefs(chat_id)
    if Config.ENABLE_CUSTOM_CAPTIONS:
        await message.reply(
            "📝 **Caption Settings**\n\nChoose a caption option or open ⚙️ options:",
            reply_markup=_caption_buttons(),
        )
    else:
        stage = "awaiting_url" if mode == "single" else "awaiting_urls"
        user_states[chat_id]["stage"] = stage
        await message.reply(_stage_prompt(stage))
    asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))


@bot.on_message(filters.command(["dl"]) & filters.private)
@security.restricted
async def single_dl(client, message):
    await _begin("single", client, message)


@bot.on_message(filters.command(["batch"]) & filters.private)
@security.restricted
async def batch_dl(client, message):
    await _begin("batch", client, message)


# --------------------------------------------------------------------------- #
# Callback queries
# --------------------------------------------------------------------------- #
@bot.on_callback_query()
@security.restricted
async def handle_callback_query(client: Client, callback_query: CallbackQuery):
    chat_id = callback_query.message.chat.id
    data = callback_query.data
    message = callback_query.message
    state = user_states.setdefault(chat_id, {"mode": None, "stage": None})
    prefs = get_prefs(chat_id)

    async def show(screen):
        text, markup = _settings_view(prefs, chat_id, screen)
        try:
            await message.edit_text(text, reply_markup=markup)
        except MessageNotModified:
            pass

    async def persist():
        save_prefs(chat_id, prefs)

    try:
        # ---- inline "start download" ----
        if data.startswith("inline:"):
            token = data.split(":", 1)[1]
            entry = _INLINE_URLS.get(token)
            if not entry:
                await callback_query.answer("⌛ This link expired — send it again.", show_alert=True)
                return
            url = entry[0]
            await callback_query.answer("Starting…")
            status = await message.reply("🚀 Processing 1 URL(s)...", reply_markup=cancel_keyboard())
            await start_task(client, message, chat_id, [url], status_msg=status,
                             user_name=callback_query.from_user.first_name)
            return

        # ---- cancel a running task ----
        if data == "task:cancel":
            killed = await runtime.cancel_chat(chat_id)
            user_states.pop(chat_id, None)
            await callback_query.answer("Cancelled")
            try:
                await message.edit_text(f"⛔ Cancelled (stopped {killed} process(es)).")
            except MessageNotModified:
                pass
            return

        # ---- redo from history ----
        if data.startswith("redo:"):
            await callback_query.answer()
            await _redo(client, message, chat_id, int(data.split(":", 1)[1]))
            return

        # ---- caption selection ----
        if data == "caption:options":
            await callback_query.answer()
            await show("main")
            return

        if data == "caption:default":
            prefs.custom_caption = None
            prefs.after_date = None
            prefs.before_date = None
            await persist()
            stage = _next_stage(state)
            state["stage"] = stage
            await callback_query.answer("✅ Default caption selected")
            await message.edit_text(_stage_prompt(stage))
            return

        if data == "caption:custom":
            state["stage"] = "awaiting_custom_caption"
            await callback_query.answer()
            await message.edit_text(
                "✏️ **Enter custom caption**\n\n"
                "Placeholders:\n`{filename}` `{size}` `{index}` `{total}`"
            )
            return

        # ---- navigation ----
        if data == "menu:main":
            await callback_query.answer()
            await show("main")
            return
        if data.startswith("menu:"):
            await callback_query.answer()
            await show(data.split(":", 1)[1])
            return

        # ---- value pickers ----
        if data.startswith("engine:"):
            prefs.engine = data.split(":", 1)[1]
            await persist()
            await callback_query.answer(f"Engine: {ENGINE_LABELS.get(prefs.engine, prefs.engine)}")
            await show("engine")
            return

        if data.startswith("action:"):
            prefs.action = data.split(":", 1)[1]
            await persist()
            await callback_query.answer(f"Action: {ACTION_LABELS.get(prefs.action, prefs.action)}")
            await show("action")
            return

        if data.startswith("format:"):
            prefs.ytdl_format = data.split(":", 1)[1]
            await persist()
            await callback_query.answer(f"Format: {FORMAT_LABELS.get(prefs.ytdl_format, prefs.ytdl_format)}")
            await show("format")
            return

        if data.startswith("font:"):
            prefs.caption_font = data.split(":", 1)[1]
            await persist()
            await callback_query.answer(f"Font: {FONT_LABELS.get(prefs.caption_font, prefs.caption_font)}")
            await show("font")
            return

        if data.startswith("chain:"):
            engine = data.split(":", 1)[1]
            if engine in prefs.fallback:
                prefs.fallback = [e for e in prefs.fallback if e != engine] or CHAIN_ENGINES[:1]
            else:
                prefs.fallback = [e for e in CHAIN_ENGINES if e in prefs.fallback + [engine]]
            await persist()
            await callback_query.answer("Chain updated")
            await show("chain")
            return

        if data.startswith("cookie:"):
            site = data.split(":", 1)[1]
            if site == "clear":
                removed = 0
                for s in COOKIE_SITES:
                    path = cookie_file_for(chat_id, s)
                    if path.exists():
                        path.unlink()
                        removed += 1
                merged = cookie_file_for(chat_id, "all")
                if merged.exists():
                    merged.unlink()
                await callback_query.answer(f"Cleared {removed} cookie file(s)")
                await show("cookies")
                return
            state["cookie_site"] = site
            state["stage"] = "awaiting_cookie_json"
            await callback_query.answer()
            await message.edit_text(
                f"🍪 **Cookies for {site}**\n\n"
                "Send the JSON array, e.g.\n"
                "`[{\"name\":\"sessionid\",\"value\":\"...\"}]`\n\n"
                "Send `-` to clear."
            )
            return

        # ---- toggles ----
        if data == "pref:upload":
            prefs.stream_upload = not prefs.stream_upload
            await persist()
            await callback_query.answer("Upload: " + ("Media" if prefs.stream_upload else "Document"))
            await show("main")
            return

        if data == "pref:split_zip":
            prefs.is_split = not prefs.is_split
            await persist()
            await callback_query.answer("Split zip: " + ("on" if prefs.is_split else "off"))
            await show("main")
            return

        if data == "pref:split_video":
            prefs.split_video = not prefs.split_video
            await persist()
            await callback_query.answer("Split video: " + ("on" if prefs.split_video else "off"))
            await show("main")
            return

        if data == "pref:reset":
            prefs.reset()
            await persist()
            await callback_query.answer("♻️ Defaults restored")
            await show("main")
            return

        if data == "pref:close":
            await callback_query.answer("Closed")
            try:
                await message.delete()
            except Exception:  # noqa: BLE001
                pass
            return

        # ---- text prompts ----
        prompts = {
            "set:prefix": ("awaiting_prefix", "✏️ Send the **prefix** (or `-` to clear)."),
            "set:suffix": ("awaiting_suffix", "✏️ Send the **suffix** (or `-` to clear)."),
            "pref:zip_pass": ("awaiting_zip_password", "🔐 Send the **zip** password (or `-` to clear)."),
            "pref:unzip_pass": ("awaiting_unzip_password", "🔓 Send the **unzip** password (or `-` to clear)."),
            "set:destination": (
                "awaiting_destination",
                "🎯 Send the destination chat/channel id (e.g. `-1001234567890`), or `-` for default.",
            ),
            "set:torrent_files": (
                "awaiting_torrent_files",
                "📂 Send indices for torrent file selection (e.g. `1-3,5`), `-` for all, "
                "or paste a magnet link to list its files.",
            ),
            "set:thumbnail": (
                "awaiting_thumbnail",
                "🖼 Send a photo to use as your custom video thumbnail (or `-` to clear).",
            ),
        }
        if data in prompts:
            stage, text = prompts[data]
            state["stage"] = stage
            await callback_query.answer()
            await message.edit_text(text)
            return

        await callback_query.answer()

    except MessageNotModified:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Callback query error: {exc}")
        try:
            await callback_query.answer(f"An error occurred: {exc}", show_alert=True)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# Inline mode
# --------------------------------------------------------------------------- #
@bot.on_inline_query()
async def inline_query(client, query):
    url = (query.query or "").strip()
    match = URL_RE.fullmatch(url)
    if not security.is_allowed(query.from_user.id) or not match:
        await query.answer([], cache_time=0)
        return
    url = match.group(1)
    token = _store_inline_url(url)
    result = InlineQueryResultArticle(
        id=token,
        title="⬇️ Download this link",
        description=url[:60],
        input_message_content=InputTextMessageContent(f"⬇️ {url}"),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("▶️ Start download", callback_data=f"inline:{token}")]]
        ),
    )
    await query.answer([result], cache_time=0)


# --------------------------------------------------------------------------- #
# Photos (custom thumbnail)
# --------------------------------------------------------------------------- #
@bot.on_message(filters.photo & filters.private)
@security.restricted
async def handle_photo(client, message):
    chat_id = message.chat.id
    state = user_states.get(chat_id, {})
    if state.get("stage") != "awaiting_thumbnail":
        return
    prefs = get_prefs(chat_id)
    Paths.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    target = Paths.THUMBS_DIR / f"{chat_id}.jpg"
    try:
        await message.download(file_name=str(target))
        prefs.thumbnail = str(target)
        save_prefs(chat_id, prefs)
        reply = await message.reply("✅ Custom thumbnail saved.")
    except Exception as exc:  # noqa: BLE001
        reply = await message.reply(f"⚠️ Could not save thumbnail: {exc}")
    state["stage"] = _next_stage(state)
    asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))
    asyncio.create_task(delete_message_after_delay(reply, Config.MESSAGE_DELETE_DELAY))
    text, markup = _settings_view(prefs, chat_id, "main")
    await message.reply(text, reply_markup=markup)


# --------------------------------------------------------------------------- #
# .txt file uploads (batch mode)
# --------------------------------------------------------------------------- #
@bot.on_message(filters.document & filters.private)
@security.restricted
async def handle_file(client, message):
    chat_id = message.chat.id
    if chat_id not in user_states or user_states[chat_id].get("stage") != "awaiting_urls":
        return
    if Path(message.document.file_name).suffix.lower() != ".txt":
        await message.reply("⚠️ Please send a .txt file with URLs")
        return
    if not _check_rate(message):
        return

    status = await message.reply("📥 Reading file...", reply_markup=cancel_keyboard())
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
    await start_task(client, message, chat_id, urls, status_msg=status)


# --------------------------------------------------------------------------- #
# Free text input (urls / captions / prompts / bare links)
# --------------------------------------------------------------------------- #
@bot.on_message(filters.text & filters.private & ~filters.command(COMMANDS))
@security.restricted
async def handle_text_input(client, message):
    chat_id = message.chat.id
    text = (message.text or "").strip()
    state = user_states.setdefault(chat_id, {"mode": None, "stage": None})
    stage = state.get("stage")
    prefs = get_prefs(chat_id)

    if stage == "awaiting_custom_caption":
        if len(text) > 1024:
            await message.reply("⚠️ Caption too long (max 1024 chars)")
            return
        prefs.custom_caption = text
        prefs.after_date = None
        prefs.before_date = None
        save_prefs(chat_id, prefs)
        bot_reply = await message.reply(f"✅ Caption set: `{text[:100]}`")
        asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))
        asyncio.create_task(delete_message_after_delay(bot_reply, Config.MESSAGE_DELETE_DELAY))
        stage = _next_stage(state)
        state["stage"] = stage
        await message.reply(_stage_prompt(stage))
        return

    if stage in ("awaiting_zip_password", "awaiting_unzip_password"):
        which = "zip" if stage == "awaiting_zip_password" else "unzip"
        value = "" if text in ("-", "none", "clear", "off") else text
        setattr(prefs, f"{which}_password", value)
        save_prefs(chat_id, prefs)
        bot_reply = await message.reply(
            f"✅ {which.capitalize()} password " + ("cleared" if not value else "saved")
        )
        asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))
        asyncio.create_task(delete_message_after_delay(bot_reply, Config.MESSAGE_DELETE_DELAY))
        state["stage"] = _next_stage(state)
        view, markup = _settings_view(prefs, chat_id, "main")
        await message.reply(view, reply_markup=markup)
        return

    if stage in ("awaiting_prefix", "awaiting_suffix"):
        attr = "prefix" if stage == "awaiting_prefix" else "suffix"
        value = "" if text == "-" else text[:64]
        setattr(prefs, attr, value)
        save_prefs(chat_id, prefs)
        reply = await message.reply(f"✅ {attr.capitalize()} " + ("cleared" if not value else f"set to `{value}`"))
        asyncio.create_task(delete_message_after_delay(message, Config.MESSAGE_DELETE_DELAY))
        asyncio.create_task(delete_message_after_delay(reply, Config.MESSAGE_DELETE_DELAY))
        state["stage"] = _next_stage(state)
        view, markup = _settings_view(prefs, chat_id, "main")
        await message.reply(view, reply_markup=markup)
        return

    if stage == "awaiting_destination":
        if text == "-":
            prefs.destination = 0
        else:
            try:
                target = int(text)
                await client.get_chat(target)
                prefs.destination = target
            except Exception as exc:  # noqa: BLE001
                await message.reply(f"⚠️ Invalid destination: {exc}")
                return
        save_prefs(chat_id, prefs)
        reply = await message.reply(f"✅ Destination set to `{prefs.destination or 'default'}`")
        asyncio.create_task(delete_message_after_delay(reply, Config.MESSAGE_DELETE_DELAY))
        state["stage"] = _next_stage(state)
        view, markup = _settings_view(prefs, chat_id, "main")
        await message.reply(view, reply_markup=markup)
        return

    if stage == "awaiting_torrent_files":
        if text.startswith("magnet:?"):
            from media_bot.downlader.aria2c import list_torrent_files

            listing = await list_torrent_files(text)
            if not listing:
                await message.reply("⚠️ Could not fetch torrent metadata. Check the magnet link.")
                return
            lines = ["📂 **Files in this torrent:**", ""]
            for index, path in listing[:80]:
                lines.append(f"`{index}` — {path[:60]}")
            lines.append("\nSend the indices to download (e.g. `1-3,5`), or `-` for all.")
            await message.reply("\n".join(lines))
            return
        prefs.torrent_files = "" if text in ("-", "all", "clear") else text
        save_prefs(chat_id, prefs)
        reply = await message.reply(f"✅ Torrent selection: `{prefs.torrent_files or 'all'}`")
        asyncio.create_task(delete_message_after_delay(reply, Config.MESSAGE_DELETE_DELAY))
        state["stage"] = _next_stage(state)
        view, markup = _settings_view(prefs, chat_id, "main")
        await message.reply(view, reply_markup=markup)
        return

    if stage == "awaiting_cookie_json":
        site = state.get("cookie_site") or "twitter"
        if text == "-":
            path = cookie_file_for(chat_id, site)
            if path.exists():
                path.unlink()
            reply = await message.reply(f"✅ Cookies for {site} cleared")
        else:
            from media_bot.utility.helper import parse_cookies as _parse

            cookies = _parse(text)
            if not cookies:
                await message.reply("⚠️ Could not parse cookies. Send a JSON array of {name, value}.")
                return
            set_cookie_file(chat_id, site, cookies)
            reply = await message.reply(f"✅ Saved {len(cookies)} cookie(s) for {site}")
        asyncio.create_task(delete_message_after_delay(reply, Config.MESSAGE_DELETE_DELAY))
        state["stage"] = _next_stage(state)
        view, markup = _settings_view(prefs, chat_id, "main")
        await message.reply(view, reply_markup=markup)
        return

    if stage == "awaiting_url":
        if not text.startswith(("http://", "https://", "magnet:?")):
            bot_reply = await message.reply("⚠️ Invalid URL. Must start with http://, https://, or magnet:?")
            asyncio.create_task(delete_message_after_delay(bot_reply, Config.MESSAGE_DELETE_DELAY))
            return
        if not _check_rate(message):
            return
        asyncio.create_task(log_to_dump_channel(client, message, [text]))
        status = await message.reply("🚀 Processing 1 URL(s)...", reply_markup=cancel_keyboard())
        await start_task(client, message, chat_id, [text], status_msg=status)
        return

    if stage == "awaiting_urls":
        urls = [m.group(1) for m in URL_RE.finditer(text)]
        if not urls:
            bot_reply = await message.reply("⚠️ No valid URLs found.")
            asyncio.create_task(delete_message_after_delay(bot_reply, Config.MESSAGE_DELETE_DELAY))
            return
        if not _check_rate(message):
            return
        asyncio.create_task(log_to_dump_channel(client, message, urls))
        status = await message.reply(f"✅ Found {len(urls)} URL(s). Starting...", reply_markup=cancel_keyboard())
        await start_task(client, message, chat_id, urls, status_msg=status)
        return

    # ---- bare link: reply-to-link style auto download (F) ----
    if stage is None:
        urls = [m.group(1) for m in URL_RE.finditer(text)]
        if not urls:
            return
        if not _check_rate(message):
            return
        user_states[chat_id] = {"mode": "single", "stage": None}
        asyncio.create_task(log_to_dump_channel(client, message, urls))
        status = await message.reply(
            f"🚀 Found {len(urls)} link(s). Starting...", reply_markup=cancel_keyboard()
        )
        await start_task(client, message, chat_id, urls, status_msg=status)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
async def main():
    Paths.DOWN_PATH.mkdir(parents=True, exist_ok=True)
    Paths.COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    Paths.THUMBS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        store.init()
        global_stats = store.get_stats(0)
        Stats.downloads = global_stats.get("downloads", 0)
        Stats.uploads = global_stats.get("uploads", 0)
        Stats.failed = global_stats.get("failed", 0)
        Stats.total_files = global_stats.get("total_files", 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not open SQLite store: {exc}")

    twitter_cookies = parse_cookies(Config.TWITTER_COOKIES)
    try:
        create_gallery_config(twitter_cookies)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not create gallery-dl config: {exc}")
    await asyncio.to_thread(load_trackers)

    await bot.start()
    me = await bot.get_me()
    print(f"\n{'=' * 60}\n🤖 Bot @{me.username} is running!\n{'=' * 60}")
    print(f"🔐 Allowlist: {sorted(Config.ALLOWED_USERS) if Config.ALLOWED_USERS else 'OPEN (anyone)'}")
    print(f"⏱  Rate limit: {Config.RATE_LIMIT_SECONDS}s")
    print(f"📊 Quota/day: {Config.QUOTA_FILES_PER_DAY or '∞'} files, {Config.QUOTA_GB_PER_DAY or '∞'} GB")
    print(f"🍪 Twitter Auth: {'✅ Configured' if twitter_cookies.get('auth_token') else '❌ Missing'}")
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
