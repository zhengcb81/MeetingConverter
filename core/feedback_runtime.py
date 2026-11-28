"""Resolve the existing owner identity and project only safe execution diagnostics."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Any, Mapping

from exceptions import AudioProcessError, explicit_cause_types

ADAPTER_VERSION = "meeting-converter-feedback/1.1.0"
FEEDBACK_OUT_ENV = "RESEARCH_FEEDBACK_OUT"
FEEDBACK_DIR_ENV = "RESEARCH_FEEDBACK_DIR"
FEEDBACK_STATE_ROOT_ENV = "RESEARCH_FEEDBACK_STATE_ROOT"
FEEDBACK_RUN_ID_ENV = "RESEARCH_FEEDBACK_RUN_ID"
FEEDBACK_ATTEMPT_ID_ENV = "RESEARCH_FEEDBACK_ATTEMPT_ID"

_ROOT = Path(__file__).resolve().parents[1]
_PROCESS_RUN_ID = "run-" + uuid.uuid4().hex[:12]
_CREDENTIAL = re.compile(
    r"(?i)(\b(?:proxy-)?authorization[ \t]*:[\r\n \t]*(?:bearer|basic)[\r\n \t]+)\S+"
    r"(?:(?:\r\n|[\r\n])[ \t]+[^\r\n]*)*"
    r"|(?<=://)[^/@\s]+:[^/@\s]+(?=@)"
    r"|(?<![A-Za-z0-9])(?:sk-|tvly-|ghp_|AIza)[A-Za-z0-9_-]{12,}"
)


def redact_diagnostic(text: str) -> str:
    return _CREDENTIAL.sub(lambda found: (found[1] or "") + "[redacted]", text)


def safe_identity(identity: str) -> str:
    """Preserve ordinary coordinates and map credential-bearing ones deterministically."""
    if not _CREDENTIAL.search(identity):
        return identity
    return "redacted-" + hashlib.sha256(identity.encode("utf-8", errors="surrogatepass")).hexdigest()


def default_state_root() -> Path:
    return _ROOT / "output" / ".feedback"


def resolve_state_root(environ: Mapping[str, str]) -> Path:
    value = environ.get(FEEDBACK_STATE_ROOT_ENV)
    return Path(value.strip()) if isinstance(value, str) and value.strip() else default_state_root()


def resolve_run_identity(environ: Mapping[str, str]) -> tuple[str, str]:
    run_id = environ.get(FEEDBACK_RUN_ID_ENV)
    attempt_id = environ.get(FEEDBACK_ATTEMPT_ID_ENV)
    return (
        safe_identity(run_id) if isinstance(run_id, str) and run_id else _PROCESS_RUN_ID,
        safe_identity(attempt_id) if isinstance(attempt_id, str) and attempt_id else "attempt-1",
    )


def feedback_io_path(path: Path) -> Path:
    """Honor Windows long paths without changing a logical source coordinate."""
    if os.name != "nt":
        return path
    absolute = os.path.abspath(path)
    if absolute.startswith(("\\\\?\\", "\\\\.\\")):
        return Path(absolute)
    return Path("\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\") else "\\\\?\\" + absolute)


def cause_types(error: BaseException) -> list[str]:
    """脱敏的因果链：只取异常类别名，不含任何消息正文。

    外层异常的类别由 ``error_type`` 承担，这里只返回它的底层原因（``__cause__``
    优先，未抑制时 ``__context__`` 兜底），因此 TimeoutError 与另一个内因可以
    冷读分辨。若异常自带已脱敏的 ``cause_types``（例如 MiMo 在切断原始链前
    投影好的归因），优先使用它，避免为了安全而丢掉底层类别。
    """
    explicit = explicit_cause_types(error)
    if explicit is not None:
        return explicit
    chain: list[str] = []
    seen: set = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        name = type(current).__name__
        if name not in chain:
            chain.append(name)
        following = current.__cause__
        if following is None and not current.__suppress_context__:
            following = current.__context__
        current = following
    return chain[1:]


def describe_error(error: BaseException, location: str) -> dict[str, Any]:
    """一条脱敏异常记录：类别、脱敏因果链与本仓相对代码位置。"""
    facts = {
        "error_type": type(error).__name__,
        "cause_types": cause_types(error),
        "location": location,
    }
    if isinstance(error, AudioProcessError):
        facts.update(process=error.process, process_step=error.stage, process_exit=error.returncode)
    return facts


def diagnostic_trace(error: BaseException, location: str) -> dict[str, Any]:
    """Retain the owner traceback frames and exception classes without error bodies."""
    frames = []
    cursor = error.__traceback__
    while cursor is not None:
        source = Path(cursor.tb_frame.f_code.co_filename)
        try:
            owner_file = source.relative_to(_ROOT)
        except ValueError:
            pass
        else:
            frames.append(f"{owner_file.as_posix()}:{cursor.tb_lineno}")
        cursor = cursor.tb_next
    facts = describe_error(error, frames[-1] if frames else location)
    return {**facts, "frames": frames}
