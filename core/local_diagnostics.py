"""Local CLI diagnostics for the original MeetingConverter attempt."""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import contextmanager, suppress
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.feedback import (
    FEEDBACK_DIR_ENV,
    FEEDBACK_OUT_ENV,
    FEEDBACK_STATE_ROOT_ENV,
    describe_error,
    feedback_io_path,
    resolve_run_identity,
    resolve_state_root,
)

_ROOT = Path(__file__).resolve().parents[1]
_LOGGER = logging.getLogger(__name__)
_LOGGER.propagate = False
_LOGGER.setLevel(logging.WARNING)
_ROTATE_BYTES = 1024 * 1024


def _stderr_notice(code: str, error_type: str) -> None:
    if sys.stderr is None:
        return
    with suppress(OSError, ValueError):
        print(f"meeting-converter {code} error_type={error_type}", file=sys.stderr)


class _DiagnosticHandler(RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        error_type = sys.exc_info()[0]
        _stderr_notice("diagnostic_log_unavailable", error_type.__name__ if error_type else "OSError")


class _DiagnosticFormat(logging.Formatter):
    def __init__(self, run_id: str, attempt_id: str):
        super().__init__()
        self.run_id = run_id
        self.attempt_id = attempt_id

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "timestamp": self.formatTime(record),
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            **record.mc_diagnostic,
        }, ensure_ascii=True)


def _log_directory() -> Path:
    env = os.environ
    if not env.get(FEEDBACK_STATE_ROOT_ENV, "").strip():
        for name in (FEEDBACK_OUT_ENV, FEEDBACK_DIR_ENV):
            location = env.get(name, "").strip()
            if location:
                path = Path(location)
                return (path.parent if name == FEEDBACK_OUT_ENV else path) / "logs"
    return resolve_state_root(env) / "logs"


@contextmanager
def cli_diagnostics(name: str):
    """Attach a rotating file only to the CLI failure stream."""
    try:
        directory = feedback_io_path(_log_directory())
        directory.mkdir(parents=True, exist_ok=True)
        handler = _DiagnosticHandler(
            directory / f"{name}.jsonl", maxBytes=_ROTATE_BYTES, backupCount=2,
            encoding="utf-8", delay=True,
        )
        handler.setFormatter(_DiagnosticFormat(*resolve_run_identity(os.environ)))
    except (OSError, ValueError) as error:
        _stderr_notice("diagnostic_log_unavailable", type(error).__name__)
        yield
        return

    _LOGGER.addHandler(handler)
    try:
        yield
    finally:
        _LOGGER.removeHandler(handler)
        with suppress(OSError):
            handler.close()


def record_failure(stage: str, error: BaseException) -> None:
    """Retain cause types and the innermost owner frame without exception text."""
    if not _LOGGER.handlers:
        return
    location = stage
    frame = error.__traceback__
    while frame is not None:
        try:
            relative = Path(frame.tb_frame.f_code.co_filename).relative_to(_ROOT)
        except ValueError:
            pass
        else:
            location = f"{relative.as_posix()}:{frame.tb_lineno}"
        frame = frame.tb_next
    _LOGGER.warning("failure", extra={
        "mc_diagnostic": {"stage": stage, **describe_error(error, location)}
    })
