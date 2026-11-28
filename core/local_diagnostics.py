"""Local diagnostics for the original MeetingConverter invocation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from functools import lru_cache, wraps
from pathlib import Path

from core.diagnostic_storage import append_jsonl
from core.feedback_runtime import (
    ADAPTER_VERSION,
    FEEDBACK_DIR_ENV,
    FEEDBACK_OUT_ENV,
    FEEDBACK_STATE_ROOT_ENV,
    diagnostic_trace,
    redact_diagnostic,
    resolve_run_identity,
    resolve_state_root,
)

_ROOT = Path(__file__).resolve().parents[1]
_IMPLEMENTATION_FILES = (
    "core/diagnostic_storage.py", "core/feedback.py", "core/feedback_runtime.py",
    "core/local_diagnostics.py", "core/pipeline.py", "core/provider_exchange.py",
    "engines/mimo.py", "feedback_owner.py", "transcribe.py", "translator.py",
)
_ROTATE_BYTES = 1024 * 1024


def _stderr_notice(error_type: str) -> None:
    if sys.stderr is None:
        return
    with suppress(OSError, ValueError):
        print(f"meeting-converter diagnostic_log_unavailable error_type={error_type}", file=sys.stderr)


class DiagnosticFormatter(logging.Formatter):
    """Keep user-facing progress useful without echoing transport credentials."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_diagnostic(super().format(record))


@lru_cache(maxsize=1)
def _implementation_sha256() -> str | None:
    try:
        sources = {name: hashlib.sha256((_ROOT / name).read_bytes()).hexdigest() for name in _IMPLEMENTATION_FILES}
    except OSError:
        return None
    content = json.dumps(sources, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(content).hexdigest()


def _paths(name: str) -> tuple[Path, ...]:
    env = os.environ
    state = resolve_state_root(env)
    explicit = []
    for key in (FEEDBACK_OUT_ENV, FEEDBACK_DIR_ENV):
        configured = env.get(key, "").strip()
        if configured:
            path = Path(configured)
            explicit.append(path.parent if key == FEEDBACK_OUT_ENV else path)
    roots = [state, *explicit] if env.get(FEEDBACK_STATE_ROOT_ENV, "").strip() else explicit or [state]
    return tuple(dict.fromkeys(root / "logs" / f"{name}.jsonl" for root in roots))


class _Journal:
    def __init__(self, name: str):
        self._destinations = _paths(name)
        self._run, self._attempt = resolve_run_identity(os.environ)
        self._failure_reported = False

    def write(self, fields: dict) -> None:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self._run,
            "attempt_id": self._attempt,
            "implementation": ADAPTER_VERSION,
            "projection_version": ADAPTER_VERSION,
            "implementation_sha256": _implementation_sha256(),
            **fields,
        }
        try:
            line = (json.dumps(row, ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
        except (TypeError, ValueError, RecursionError) as error:
            self._report_unavailable(type(error).__name__)
            return
        failure = "OSError"
        for destination in self._destinations:
            try:
                append_jsonl(destination, line, rotate_bytes=_ROTATE_BYTES)
            except (OSError, ValueError) as error:
                failure = type(error).__name__
            else:
                return
        self._report_unavailable(failure)

    def _report_unavailable(self, error_type: str) -> None:
        if not self._failure_reported:
            self._failure_reported = True
            _stderr_notice(error_type)


@dataclass(frozen=True)
class _Scope:
    journal: _Journal
    step_id: str | None = None
    input_id: str | None = None


_STEP: ContextVar[_Scope | None] = ContextVar("meeting_step", default=None)


@contextmanager
def cli_diagnostics(name: str):
    """Bind this invocation without attaching a handler to process-global logging."""
    token = _STEP.set(_Scope(_Journal(name)))
    try:
        yield
    finally:
        _STEP.reset(token)


@contextmanager
def operation_scope(step_id: str, input_id: str):
    scope = _STEP.get() or _Scope(_Journal("library"))
    token = _STEP.set(replace(scope, step_id=step_id, input_id=input_id))
    try:
        yield
    finally:
        _STEP.reset(token)


def record_event(stage: str, phase: str, **facts) -> None:
    """Write caller-owned status and input references without raw content."""
    scope = _STEP.get() or _Scope(_Journal("library"))
    identity = {} if scope.step_id is None else {"step_id": scope.step_id, "input_id": scope.input_id}
    scope.journal.write({**identity, **facts, "stage": stage, "phase": phase})


def record_failure(
    stage: str, error: BaseException, *,
    notice: tuple[logging.Logger, str] | None = None,
    notice_context: dict | None = None,
    **facts,
) -> None:
    """Record the cause and owner stack without provider bodies or credentials."""
    trace = diagnostic_trace(error, stage)
    record_event(stage, "error", **facts, **trace)
    if notice is not None:
        logger, message = notice
        logger.warning("%s", redact_diagnostic(message), extra=notice_context)


def diagnosed_command(name: str):
    """Record the existing entry point while preserving its result/exit semantics."""
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            with cli_diagnostics(name):
                record_event("command", "started")
                try:
                    result = function(*args, **kwargs)
                except SystemExit as exc:
                    if exc.code:
                        record_failure("command", exc)
                    record_event("command", "exited", exit_code=exc.code if type(exc.code) is int else None)
                    raise
                except Exception as exc:
                    record_failure("command", exc)
                    raise
                else:
                    record_event("command", "exited", exit_code=result if type(result) is int else 0)
                    return result
        return run
    return decorate
