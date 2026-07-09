"""engines - 语音识别引擎抽象层。"""

from __future__ import annotations

from engines.base import Segment, TranscriptionResult, TranscriptionEngine
from engines.whisper import WhisperEngine

__all__ = [
    "Segment",
    "TranscriptionResult",
    "TranscriptionEngine",
    "WhisperEngine",
]
