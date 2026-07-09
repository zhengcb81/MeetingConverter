"""MiMoEngine 单元测试。"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

import pytest

from engines.base import TranscriptionResult, UnsupportedFormatError
from engines.mimo import MiMoEngine


class TestMiMoInit:
    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="API key"):
            MiMoEngine(api_key="")

    def test_default_base_url(self):
        eng = MiMoEngine(api_key="key")
        assert "xiaomimimo.com" in eng._base_url

    def test_custom_base_url(self):
        eng = MiMoEngine(api_key="key", base_url="https://custom.example.com")
        assert eng._base_url == "https://custom.example.com"


class TestEncodeAudio:
    def test_wav_data_url(self, tmp_path):
        f = tmp_path / "a.wav"
        f.write_bytes(b"RIFFdata")
        eng = MiMoEngine(api_key="key")
        result = eng._encode_audio(f, "wav")
        assert result.startswith("data:audio/wav;base64,")
        b64_part = result.split(",", 1)[1]
        assert base64.b64decode(b64_part) == b"RIFFdata"

    def test_mp3_data_url(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"ID3data")
        eng = MiMoEngine(api_key="key")
        result = eng._encode_audio(f, "mp3")
        assert result.startswith("data:audio/mpeg;base64,")


class TestBuildPayload:
    def test_structure(self):
        eng = MiMoEngine(api_key="key")
        payload = eng._build_payload("data:audio/wav;base64,abc", "zh")
        assert payload["model"] == "mimo-v2.5-asr"
        msg = payload["messages"][0]
        assert msg["role"] == "user"
        content = msg["content"][0]
        assert content["type"] == "input_audio"
        assert content["input_audio"]["data"] == "data:audio/wav;base64,abc"
        assert payload["asr_options"]["language"] == "zh"

    def test_auto_language(self):
        eng = MiMoEngine(api_key="key")
        payload = eng._build_payload("data", None)
        assert payload["asr_options"]["language"] == "auto"

    def test_auto_language_explicit(self):
        eng = MiMoEngine(api_key="key")
        payload = eng._build_payload("data", "auto")
        assert payload["asr_options"]["language"] == "auto"


class TestCallApi:
    def test_returns_content(self, mocker, tmp_path):
        eng = MiMoEngine(api_key="key", base_url="https://api.example.com")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "识别结果文本"}}]}
        ).encode("utf-8")
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_resp)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mocker.patch("engines.mimo.urllib.request.urlopen", return_value=mock_ctx)
        result = eng._call_api("data:audio/wav;base64,abc", "zh")
        assert result == "识别结果文本"

    def test_api_key_header(self, mocker):
        eng = MiMoEngine(api_key="my-secret-key")
        mock_req = mocker.patch("engines.mimo.urllib.request.Request")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "x"}}]}
        ).encode("utf-8")
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_resp)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mocker.patch("engines.mimo.urllib.request.urlopen", return_value=mock_ctx)
        eng._call_api("data", None)
        headers = mock_req.call_args[1]["headers"]
        assert headers["api-key"] == "my-secret-key"
        assert "Bearer" not in headers.get("api-key", "")


class TestTranscribe:
    @pytest.fixture
    def audio_file(self, tmp_path):
        f = tmp_path / "meeting.mp3"
        f.write_bytes(b"\x00" * 1024)
        return f

    def test_unsupported_format_raises(self, audio_file):
        unsupported = audio_file.with_suffix(".m4a")
        unsupported.write_bytes(b"\x00" * 1024)
        eng = MiMoEngine(api_key="key")
        with pytest.raises(UnsupportedFormatError):
            eng.transcribe(str(unsupported))

    def test_supported_format_returns_result(self, mocker, audio_file):
        eng = MiMoEngine(api_key="key")
        mocker.patch.object(eng, "_call_api", return_value="营收增长30%。利润提升。")
        mocker.patch("engines.mimo.get_audio_duration", return_value=60.0)
        mocker.patch("engines.mimo.estimate_base64_size_mb", return_value=0.001)
        result = eng.transcribe(str(audio_file), language="zh")
        assert isinstance(result, TranscriptionResult)
        assert result.language == "zh"
        assert result.language_probability == 1.0
        assert result.duration == 60.0
        assert len(result.segments) >= 1
        assert "营收增长" in result.segments[0].text

    def test_auto_language_returns_auto(self, mocker, audio_file):
        eng = MiMoEngine(api_key="key")
        mocker.patch.object(eng, "_call_api", return_value="文本")
        mocker.patch("engines.mimo.get_audio_duration", return_value=10.0)
        mocker.patch("engines.mimo.estimate_base64_size_mb", return_value=0.001)
        result = eng.transcribe(str(audio_file))
        assert result.language == "auto"

    def test_chunked_transcription(self, mocker, tmp_path):
        f = tmp_path / "long.mp3"
        f.write_bytes(b"\x00" * (12 * 1024 * 1024))
        eng = MiMoEngine(api_key="key")
        chunk1 = tmp_path / "chunk0.mp3"
        chunk1.write_bytes(b"\x00")
        chunk2 = tmp_path / "chunk1.mp3"
        chunk2.write_bytes(b"\x00")
        mocker.patch("engines.mimo.estimate_base64_size_mb", return_value=12.0)
        mocker.patch(
            "engines.mimo.split_by_silence",
            return_value=[(chunk1, 0.0, 100.0), (chunk2, 100.0, 200.0)],
        )
        mocker.patch("engines.mimo.get_audio_duration", return_value=200.0)
        mocker.patch.object(eng, "_call_api", side_effect=["第一段。", "第二段。"])
        result = eng.transcribe(str(f), language="zh")
        assert "第一段" in result.segments[0].text
        assert "第二段" in "".join(s.text for s in result.segments)
        assert eng._call_api.call_count == 2
