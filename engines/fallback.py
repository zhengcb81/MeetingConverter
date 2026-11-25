"""engines/fallback.py - 引擎回退包装：主引擎失败时自动降级到备用引擎。

主失败的稳定原因（脱敏异常类别链）与备用引擎是否真的被启用，通过
:meth:`drain_engine_events` 交给反馈投影；异常正文照旧走本仓日志，不进入
跨仓观察。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from core.local_diagnostics import record_failure
from engines.base import TranscriptionResult, UnsupportedFormatError
from exceptions import explicit_cause_types

logger = logging.getLogger(__name__)


def _cause_types(error: BaseException) -> List[str]:
    """脱敏因果链：外层之外的底层异常类别，循环与超长链有界。

    若异常自带已脱敏的 ``cause_types``（例如 MiMo 切断原始链前投影的
    归因），优先使用它，避免安全处理丢掉底层类别。
    """
    explicit = explicit_cause_types(error)
    if explicit is not None:
        return explicit
    chain: List[str] = []
    seen: set = set()
    current: Optional[BaseException] = error
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


class FallbackEngine:
    """主引擎失败（不支持格式或异常）时回退到备用引擎。"""

    def __init__(self, primary, fallback_factory: Callable):
        self._primary = primary
        self._fallback_factory = fallback_factory
        self._fallback = None
        self._events: List[Dict[str, Any]] = []

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        # 事件按次清理：一次 transcribe 调用对应一份本次调用的事实。
        self._events = []
        try:
            return self._primary.transcribe(audio_path, language, initial_prompt)
        except UnsupportedFormatError as e:
            self._note_primary_failure(e)
            logger.info(f"格式不支持，回退到备用引擎: {audio_path}")
            return self._engage_fallback(audio_path, language, initial_prompt)
        except Exception as e:
            self._note_primary_failure(e)
            logger.warning("主引擎失败(%s)，回退到备用引擎", type(e).__name__)
            record_failure("engine_fallback", e)
            return self._engage_fallback(audio_path, language, initial_prompt)

    def drain_engine_events(self) -> List[Dict[str, Any]]:
        """取走并清空本次调用积累的降级事件（结构化、脱敏）。"""
        events, self._events = self._events, []
        return events

    def _note_primary_failure(self, error: BaseException) -> None:
        self._events.append(
            {
                "event": "primary_failed",
                "error_type": type(error).__name__,
                "cause_types": _cause_types(error),
            }
        )

    def _engage_fallback(
        self,
        audio_path: str,
        language: Optional[str],
        initial_prompt: Optional[str],
    ) -> TranscriptionResult:
        if self._fallback is None:
            try:
                self._fallback = self._fallback_factory()
            except Exception as exc:
                self._events.append(
                    {
                        "event": "fallback_unavailable",
                        "error_type": type(exc).__name__,
                        "cause_types": _cause_types(exc),
                    }
                )
                raise
            self._events.append(
                {
                    "event": "fallback_engaged",
                    "engine": type(self._fallback).__name__,
                }
            )
        return self._fallback.transcribe(audio_path, language, initial_prompt)
