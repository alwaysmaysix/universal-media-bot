# Runtime registries: per-chat task tracking, subprocess tracking and
# cooperative cancellation.
#
# Downloads are launched as background asyncio tasks. The chat id is carried in
# a ContextVar so every subprocess spawned inside a download can be registered
# against it and killed when the user cancels.

import asyncio
import contextvars
import logging
import os
import signal
from collections import defaultdict

logger = logging.getLogger(__name__)

_current_chat = contextvars.ContextVar("media_bot_chat", default=None)

_procs = defaultdict(set)          # chat_id -> {asyncio.subprocess.Process}
_tasks = {}                        # chat_id -> asyncio.Task

QUOTA_FILE = None  # placeholder kept for readability


# --------------------------------------------------------------------------- #
# Chat context
# --------------------------------------------------------------------------- #
def set_chat(chat_id):
    return _current_chat.set(chat_id)


def reset_chat(token):
    try:
        _current_chat.reset(token)
    except ValueError:
        pass


def current_chat():
    return _current_chat.get()


# --------------------------------------------------------------------------- #
# Task registry
# --------------------------------------------------------------------------- #
def register_task(chat_id, task: "asyncio.Task"):
    old = _tasks.get(chat_id)
    if old and not old.done() and old is not task:
        old.cancel()
    _tasks[chat_id] = task


def remove_task(chat_id, task=None):
    if task is None or _tasks.get(chat_id) is task:
        _tasks.pop(chat_id, None)


def get_task(chat_id):
    return _tasks.get(chat_id)


def active_chats():
    return [cid for cid, task in _tasks.items() if not task.done()]


def active_count():
    return len(active_chats())


# --------------------------------------------------------------------------- #
# Subprocess registry
# --------------------------------------------------------------------------- #
def _register(proc):
    bucket = _procs[current_chat()]
    # prune finished processes so the set does not grow forever
    for done in [p for p in bucket if p.returncode is not None]:
        bucket.discard(done)
    bucket.add(proc)
    return proc


def unregister(proc):
    for bucket in _procs.values():
        bucket.discard(proc)


async def spawn_exec(*args, **kwargs):
    """asyncio.create_subprocess_exec + registration for cancellation."""
    proc = await asyncio.create_subprocess_exec(*args, **kwargs)
    return _register(proc)


async def spawn_shell(cmd, **kwargs):
    """asyncio.create_subprocess_shell + registration for cancellation."""
    if os.name == "posix":
        kwargs.setdefault("start_new_session", True)
    proc = await asyncio.create_subprocess_shell(cmd, **kwargs)
    return _register(proc)


def _kill(proc):
    pid = getattr(proc, "pid", None)
    try:
        if os.name == "posix" and pid:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        pass
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def kill_chat_processes(chat_id):
    bucket = _procs.pop(chat_id, None)
    if not bucket:
        return 0
    for proc in list(bucket):
        if proc.returncode is None:
            _kill(proc)
    return len(bucket)


def kill_all_processes():
    total = 0
    for chat_id in list(_procs.keys()):
        total += kill_chat_processes(chat_id)
    return total


async def cancel_chat(chat_id):
    """Kill subprocesses and cancel the running task for a chat."""
    killed = kill_chat_processes(chat_id)
    task = _tasks.pop(chat_id, None)
    if task and not task.done():
        task.cancel()
    return killed


async def cancel_all():
    killed = kill_all_processes()
    tasks = list(_tasks.values())
    _tasks.clear()
    for task in tasks:
        if not task.done():
            task.cancel()
    return killed, len(tasks)
