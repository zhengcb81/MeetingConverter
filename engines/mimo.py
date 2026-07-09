"""engines/mimo.py - MiMo-V2.5-ASR 引擎，基于小米 MiMo 开放平台 API。

API 文档: https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/Speech-Recognition
"""

from __future__ import annotations

import base64
import json
import urllib.request
import urllib.error
from typing import Optional

from audio_utils import (
    detect_format,
    estimate_base64_size_mb,
    get_audio_duration,
    split_by_silence,
    MAX_BASE64_MB,
)
from engines.base import Segment, TranscriptionResult, UnsupportedFormatError
from text_merger import merge_text_into_paragraphs

MIMO_API_URL = "https://api.xiaomimimo.com/v1/chat/completions"
MIMO_MODEL = "mimo-v2.5-asr"
MIME_MAP = {"wav": "audio/wav", "mp3": "audio/mpeg"}


class MiMoEngine:
    """小米 MiMo-V2.5-ASR 语音识别引擎。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = MIMO_API_URL,
        model: str = MIMO_MODEL,
        max_chars: int = 2000,
    ):
        if not api_key:
            raise ValueError("MiMo API key 未配置")
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._max_chars = max_chars

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        fmt = detect_format(audio_path)
        if fmt is None:
            raise UnsupportedFormatError(
                f"MiMo 不支持该格式: {audio_path}（仅 wav/mp3）"
            )

        size_mb = estimate_base64_size_mb(audio_path)
        if size_mb > MAX_BASE64_MB:
            text = self._transcribe_chunked(audio_path, language)
        else:
            audio_data = self._encode_audio(audio_path, fmt)
            text = self._call_api(audio_data, language)

        duration = get_audio_duration(audio_path)
        segments = merge_text_into_paragraphs(text, self._max_chars)
        detected_lang = language if language and language != "auto" else "auto"
        return TranscriptionResult(
            language=detected_lang,
            language_probability=1.0,
            duration=duration,
            segments=segments,
            paragraph_level=True,
        )

    def _transcribe_chunked(self, audio_path: str, language: Optional[str]) -> str:
        chunks = split_by_silence(audio_path)
        parts = []
        for chunk_path, _start, _end in chunks:
            fmt = detect_format(chunk_path) or "mp3"
            audio_data = self._encode_audio(chunk_path, fmt)
            parts.append(self._call_api(audio_data, language))
        return "".join(parts)

    def _encode_audio(self, path, fmt: str) -> str:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = MIME_MAP.get(fmt, "audio/mpeg")
        return f"data:{mime};base64,{b64}"

    def _build_payload(self, audio_data_url: str, language: Optional[str]) -> dict:
        asr_lang = language if language and language != "auto" else "auto"
        return {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": audio_data_url},
                        }
                    ],
                }
            ],
            "asr_options": {"language": asr_lang},
        }

    def _call_api(self, audio_data_url: str, language: Optional[str]) -> str:
        payload = self._build_payload(audio_data_url, language)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._base_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "api-key": self._api_key,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
