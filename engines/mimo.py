"""engines/mimo.py - MiMo-V2.5-ASR 引擎，基于小米 MiMo 开放平台 API。

API 文档: https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/Speech-Recognition
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from typing import List, Optional

from audio_utils import (
    MAX_BASE64_MB,
    cleanup_chunks,
    detect_format,
    estimate_base64_size_mb,
    get_audio_duration,
    split_by_silence,
)
from engines.base import TranscriptionResult, UnsupportedFormatError
from exceptions import MAX_CAUSE_TYPES, EngineError
from text_merger import merge_text_into_paragraphs

logger = logging.getLogger(__name__)

MIMO_API_URL = "https://api.xiaomimimo.com/v1/chat/completions"
MIMO_MODEL = "mimo-v2.5-asr"
MIME_MAP = {"wav": "audio/wav", "mp3": "audio/mpeg"}


def _http_status(error: BaseException) -> Optional[int]:
    """从 HTTPError 取状态；其他异常即使带 code/status 也不当作 HTTP 状态。"""
    if isinstance(error, urllib.error.HTTPError):
        code = error.code
        if isinstance(code, int) and 100 <= code <= 599:
            return code
    return None


def _source_location(error: BaseException) -> str:
    """本仓源码位置：只保留 ``engines/mimo.py:<line>``，不带绝对路径。

    供应商/标准库的帧不进入位置字段；取本文件里最深的一帧，便于定位到
    真正发起调用的那一行。
    """
    location = "engines/mimo.py#_call_api"
    tb = error.__traceback__
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename.replace("\\", "/")
        if filename.endswith("/engines/mimo.py") or filename == "engines/mimo.py":
            location = f"engines/mimo.py:{tb.tb_lineno}"
        tb = tb.tb_next
    return location


def _cause_chain(error: BaseException) -> List[str]:
    """原始异常的完整脱敏因果链（含自身类别，不含消息正文）。

    这个链会成为 ``EngineError.cause_types``：对业务层而言，原始异常就是
    EngineError 的底层原因，因此自身类别也在其中。投影侧只取底层部分时
    由投影侧自行截取。
    """
    chain: List[str] = []
    seen: set = set()
    current: Optional[BaseException] = error
    while (
        current is not None
        and id(current) not in seen
        and len(chain) < MAX_CAUSE_TYPES
    ):
        seen.add(id(current))
        name = type(current).__name__
        if name not in chain:
            chain.append(name)
        following = current.__cause__
        if following is None and not current.__suppress_context__:
            following = current.__context__
        current = following
    if isinstance(error, urllib.error.URLError) and isinstance(
        error.reason, BaseException
    ):
        name = type(error.reason).__name__
        if name not in chain:
            # 立即原因比最深的嵌套原因更贴近本次 transport 失败；链满时
            # 让位给它，保证总数仍不超过公共上限。
            if len(chain) >= MAX_CAUSE_TYPES:
                chain.pop()
            chain.append(name)
    return chain


def _diagnostic_fields(error: BaseException, prefix: str) -> str:
    """一次失败的可公开字段：尝试序号、异常类型、HTTP 状态与源码位置。"""
    fields = [prefix, f"error_type={type(error).__name__}"]
    status = _http_status(error)
    if status is not None:
        fields.append(f"http_status={status}")
    fields.append(f"location={_source_location(error)}")
    return " ".join(fields)


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
        try:
            parts = []
            for chunk_path, _start, _end in chunks:
                fmt = detect_format(chunk_path) or "mp3"
                audio_data = self._encode_audio(chunk_path, fmt)
                parts.append(self._call_api(audio_data, language))
            return "".join(parts)
        finally:
            cleanup_chunks(chunks)

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
        max_retries = 3
        failure = None
        for attempt in range(max_retries):
            try:
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
            except Exception as e:
                # 只投影可公开的字段：供应商正文、请求原文和凭据留在
                # transport 边界内，不进入重试日志、失败消息或 traceback。
                diagnostic = _diagnostic_fields(
                    e, f"attempt={attempt + 1}/{max_retries}"
                )
                if attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        "MiMo API 重试 %d/%d (%ds): %s",
                        attempt + 1,
                        max_retries,
                        wait,
                        diagnostic,
                    )
                    time.sleep(wait)
                else:
                    failure_text = _diagnostic_fields(
                        e, f"attempts={max_retries}"
                    )
                    logger.error(
                        "MiMo API 失败（%d次重试后）: %s",
                        max_retries,
                        failure_text,
                    )
                    failure = EngineError(
                        f"MiMo API 失败（{max_retries}次重试后）: {failure_text}"
                    )
                    # 业务层仍拿到原类型 EngineError；归因放在结构化属性上。
                    failure.attempts = max_retries
                    failure.error_type = type(e).__name__
                    failure.http_status = _http_status(e)
                    failure.location = _source_location(e)
                    failure.cause_types = _cause_chain(e)
                    # 跳出 except 后再抛：连 __context__ 也不保留原始异常，
                    # 下游任何 traceback 形式都无法重新物化供应商正文。
                    break
        if failure is None:  # pragma: no cover - 循环必然以 return 或 failure 结束
            raise EngineError("MiMo API 失败（未知原因）")
        raise failure from None
