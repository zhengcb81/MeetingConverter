"""engines/base.py - 转写引擎抽象接口与数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, runtime_checkable


@dataclass
class Segment:
    """单段转写片段。"""

    start: float
    end: float
    text: str


@dataclass
class TranscriptionResult:
    """一次转写的完整结果。"""

    language: str
    language_probability: float
    duration: float
    segments: List[Segment] = field(default_factory=list)
    paragraph_level: bool = False


class UnsupportedFormatError(Exception):
    """音频格式不被当前引擎支持，应回退到其他引擎。"""


@runtime_checkable
class TranscriptionEngine(Protocol):
    """语音识别引擎统一接口。"""

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> TranscriptionResult: ...
