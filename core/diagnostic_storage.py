"""Append and rotate one owned JSONL stream under a process-wide file lock."""

from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path

from core.feedback_runtime import feedback_io_path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


@contextmanager
def _lock(path: Path):
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a+b") as lock:
        deadline = time.monotonic() + 2.0
        while True:
            try:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
            else:
                break
        # The handle is scoped to this append. Closing it also unlocks after a failure.
        yield


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _rotate(path: Path, incoming: int, maximum: int) -> None:
    pending = path.with_name(path.name + ".rotate")
    recent = path.with_name(path.name + ".1")
    oldest = path.with_name(path.name + ".2")
    try:
        size = _size(path)
        if not pending.exists() and size and size + incoming > maximum:
            path.replace(pending)
        if pending.exists():
            if recent.exists():
                recent.replace(oldest)
            pending.replace(recent)
    except PermissionError:
        # A Windows reader can hold any of the three generations. The active bytes
        # and any staged generation survive; a later append finishes the rotation.
        return


def append_jsonl(path: Path, line: bytes, *, rotate_bytes: int | None = None) -> None:
    """Serialize with callers in other processes. Isolate a torn historical last line."""
    path = feedback_io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock(path):
        if rotate_bytes is not None:
            _rotate(path, len(line), rotate_bytes)
        with path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell():
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) != b"\n":
                    line = b"\n" + line
            handle.write(line)
