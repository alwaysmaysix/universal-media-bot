# Access control and light rate limiting.
#
# The bot is private by default *if* you configure ALLOWED_USERS (or OWNER).
# With an empty allowlist it stays open to everyone, matching the previous
# behaviour, so existing deployments keep working.

import functools
import logging
import time

from media_bot.utility.variables import Config

logger = logging.getLogger(__name__)

_last_seen = {}          # user_id -> monotonic timestamp of last download start
_denied_once = set()     # user_id -> already told "not allowed"


def is_allowed(user_id) -> bool:
    if not Config.ALLOWED_USERS:
        return True
    return user_id == Config.OWNER or user_id in Config.ALLOWED_USERS


def is_owner(user_id) -> bool:
    return bool(Config.OWNER) and user_id == Config.OWNER


def cooldown_remaining(user_id) -> float:
    """Seconds left before this user may start another download."""
    if Config.RATE_LIMIT_SECONDS <= 0:
        return 0.0
    last = _last_seen.get(user_id, 0)
    return max(0.0, Config.RATE_LIMIT_SECONDS - (time.monotonic() - last))


def touch(user_id):
    _last_seen[user_id] = time.monotonic()


async def _deny(update):
    user = getattr(update, "from_user", None)
    uid = user.id if user else None
    text = "🚫 You are not authorised to use this bot."
    try:
        if hasattr(update, "answer") and not getattr(update, "reply_text", None):
            # CallbackQuery
            if hasattr(update, "data"):
                await update.answer(text, show_alert=True)
                return
        await update.reply(text)
    except Exception:  # noqa: BLE001
        pass
    if uid:
        _denied_once.add(uid)


def restricted(func):
    """Decorator: drop (and warn) unauthorised users."""

    @functools.wraps(func)
    async def wrapper(client, update, *args, **kwargs):
        user = getattr(update, "from_user", None)
        if user is not None and not is_allowed(user.id):
            uid = user.id
            if uid not in _denied_once:
                await _deny(update)
                logger.warning("Denied access to user %s", uid)
            return None
        return await func(client, update, *args, **kwargs)

    return wrapper


def owner_only(func):
    """Decorator: owner-only commands (broadcast, cancelall, ...)."""

    @functools.wraps(func)
    async def wrapper(client, update, *args, **kwargs):
        user = getattr(update, "from_user", None)
        if user is None or not is_owner(user.id):
            try:
                if hasattr(update, "data"):
                    await update.answer("⛔ Owner only.", show_alert=True)
                else:
                    await update.reply("⛔ This command is restricted to the owner.")
            except Exception:  # noqa: BLE001
                pass
            return None
        return await func(client, update, *args, **kwargs)

    return wrapper
