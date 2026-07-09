"""引擎工厂单元测试。"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from engines.factory import create_engine
from engines.whisper import WhisperEngine
from engines.mimo import MiMoEngine
from engines.fallback import FallbackEngine
from engines.base import TranscriptionEngine


@pytest.fixture
def fake_faster_whisper(mocker):
    """注入假的 faster_whisper 模块，避免真实依赖。"""
    fake_module = MagicMock()
    mocker.patch.dict(sys.modules, {"faster_whisper": fake_module})
    return fake_module


class TestCreateEngineWhisper:
    def test_returns_whisper_engine(self, fake_faster_whisper):
        engine = create_engine("whisper")
        assert isinstance(engine, WhisperEngine)
        assert isinstance(engine, TranscriptionEngine)

    def test_constructs_whisper_model_with_params(self, fake_faster_whisper):
        create_engine(
            "whisper",
            whisper_model="medium",
            whisper_device="cuda",
            whisper_compute_type="float16",
        )
        fake_faster_whisper.WhisperModel.assert_called_once_with(
            "medium", device="cuda", compute_type="float16"
        )

    def test_default_params(self, fake_faster_whisper):
        create_engine("whisper")
        fake_faster_whisper.WhisperModel.assert_called_once_with(
            "small", device="cpu", compute_type="int8"
        )


class TestCreateEngineMimo:
    def test_returns_mimo_engine(self, sample_config):
        engine = create_engine("mimo", sample_config)
        assert isinstance(engine, MiMoEngine)
        assert isinstance(engine, TranscriptionEngine)

    def test_missing_key_raises(self, fake_faster_whisper):
        with pytest.raises(ValueError, match="API key"):
            create_engine("mimo", {"mimo_api_key": ""})

    def test_placeholder_key_raises(self, fake_faster_whisper):
        with pytest.raises(ValueError, match="API key"):
            create_engine("mimo", {"mimo_api_key": "YOUR_API_KEY_HERE"})

    def test_uses_custom_base_url(self, sample_config):
        sample_config["mimo_base_url"] = "https://custom.mimo.com"
        engine = create_engine("mimo", sample_config)
        assert engine._base_url == "https://custom.mimo.com"


class TestCreateEngineAuto:
    def test_with_mimo_key_returns_fallback(self, sample_config, fake_faster_whisper):
        engine = create_engine("auto", sample_config)
        assert isinstance(engine, FallbackEngine)
        assert isinstance(engine, TranscriptionEngine)

    def test_without_mimo_key_returns_whisper(self, fake_faster_whisper):
        engine = create_engine("auto", {"mimo_api_key": ""})
        assert isinstance(engine, WhisperEngine)
        assert not isinstance(engine, FallbackEngine)

    def test_placeholder_key_falls_back_to_whisper(self, fake_faster_whisper):
        engine = create_engine("auto", {"mimo_api_key": "YOUR_API_KEY_HERE"})
        assert isinstance(engine, WhisperEngine)

    def test_no_config_returns_whisper(self, fake_faster_whisper):
        engine = create_engine("auto")
        assert isinstance(engine, WhisperEngine)


class TestCreateEngineInvalid:
    def test_unknown_engine_raises(self, fake_faster_whisper):
        with pytest.raises(ValueError, match="未知引擎"):
            create_engine("nonexistent")
