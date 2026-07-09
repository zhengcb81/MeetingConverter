"""FallbackEngine 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from engines.base import TranscriptionResult, UnsupportedFormatError
from engines.fallback import FallbackEngine


class TestFallbackEngine:
    def test_primary_succeeds_no_fallback(self):
        primary = MagicMock()
        expected = TranscriptionResult(
            language="zh", language_probability=1.0, duration=60.0, segments=[]
        )
        primary.transcribe.return_value = expected
        fallback_factory = MagicMock()
        engine = FallbackEngine(primary, fallback_factory)
        result = engine.transcribe("a.mp3")
        assert result is expected
        fallback_factory.assert_not_called()

    def test_unsupported_format_triggers_fallback(self):
        primary = MagicMock()
        primary.transcribe.side_effect = UnsupportedFormatError("m4a")
        fallback = MagicMock()
        expected = TranscriptionResult(
            language="en", language_probability=0.9, duration=60.0, segments=[]
        )
        fallback.transcribe.return_value = expected
        fallback_factory = MagicMock(return_value=fallback)
        engine = FallbackEngine(primary, fallback_factory)
        result = engine.transcribe("a.m4a", language="en")
        assert result is expected
        fallback_factory.assert_called_once()

    def test_fallback_lazily_created(self):
        primary = MagicMock()
        primary.transcribe.side_effect = UnsupportedFormatError("m4a")
        fallback = MagicMock()
        expected = TranscriptionResult("en", 0.9, 60.0, [])
        fallback.transcribe.return_value = expected
        fallback_factory = MagicMock(return_value=fallback)
        engine = FallbackEngine(primary, fallback_factory)
        engine.transcribe("a.m4a")
        engine.transcribe("b.m4a")
        fallback_factory.assert_called_once()

    def test_passes_args_to_fallback(self):
        primary = MagicMock()
        primary.transcribe.side_effect = UnsupportedFormatError("m4a")
        fallback = MagicMock()
        fallback.transcribe.return_value = TranscriptionResult("zh", 1.0, 30.0, [])
        engine = FallbackEngine(primary, MagicMock(return_value=fallback))
        engine.transcribe("a.m4a", language="zh", initial_prompt="prompt")
        fallback.transcribe.assert_called_once_with("a.m4a", "zh", "prompt")
