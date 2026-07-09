"""engines/whisper.py - faster-whisper 适配层，实现统一引擎接口。"""

from __future__ import annotations

from typing import Optional

from engines.base import Segment, TranscriptionResult, TranscriptionEngine


class WhisperEngine:
    """基于 faster-whisper (CTranslate2) 的转写引擎。"""

    def __init__(self, model):
        self._model = model

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        kwargs = {
            "beam_size": 5,
            "vad_filter": True,
            "vad_parameters": {"min_silence_duration_ms": 500},
        }
        if language:
            kwargs["language"] = language
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt

        segments_iter, info = self._model.transcribe(str(audio_path), **kwargs)
        segments = [
            Segment(start=s.start, end=s.end, text=s.text.strip())
            for s in segments_iter
            if s.text.strip()
        ]
        return TranscriptionResult(
            language=info.language,
            language_probability=info.language_probability,
            duration=info.duration,
            segments=segments,
        )
