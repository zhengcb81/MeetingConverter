"""engines/fallback.py - 引擎回退包装：主引擎失败时自动降级到备用引擎。"""

from __future__ import annotations

from typing import Callable, Optional

from engines.base import TranscriptionResult, UnsupportedFormatError


class FallbackEngine:
    """主引擎失败（不支持格式或异常）时回退到备用引擎。"""

    def __init__(self, primary, fallback_factory: Callable):
        self._primary = primary
        self._fallback_factory = fallback_factory
        self._fallback = None

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        try:
            return self._primary.transcribe(audio_path, language, initial_prompt)
        except UnsupportedFormatError:
            return self._get_fallback().transcribe(audio_path, language, initial_prompt)

    def _get_fallback(self):
        if self._fallback is None:
            self._fallback = self._fallback_factory()
        return self._fallback
