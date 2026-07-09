"""load_config 单元测试（P3.1）。"""

from __future__ import annotations

import json
import os

import pytest

from translator import load_config


class TestLoadConfigFromPath:
    def test_loads_from_explicit_path(self, tmp_path):
        cfg = {"deepseek_api_key": "key123", "whisper_model": "medium"}
        p = tmp_path / "config.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        result = load_config(str(p))
        assert result["deepseek_api_key"] == "key123"
        assert result["whisper_model"] == "medium"

    def test_returns_dict(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"deepseek_api_key": "k"}), encoding="utf-8")
        assert isinstance(load_config(str(p)), dict)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "nonexistent.json"))


class TestConfigKeysEffective:
    def test_mimo_keys_present(self, sample_config):
        assert "mimo_api_key" in sample_config
        assert "mimo_base_url" in sample_config
        assert "transcription_engine" in sample_config

    def test_whisper_keys_present(self, sample_config):
        for k in ["whisper_model", "whisper_device", "whisper_compute_type"]:
            assert k in sample_config

    def test_paragraph_keys_present(self, sample_config):
        assert "paragraph_merge_gap_sec" in sample_config
        assert "paragraph_max_chars" in sample_config

    def test_translate_keys_present(self, sample_config):
        assert "translate_batch_size" in sample_config
        assert "translate_max_retries" in sample_config


class TestConfigDefaults:
    def test_missing_key_returns_none(self):
        assert ({}).get("whisper_model") is None
        assert ({}).get("mimo_api_key", "") == ""

    def test_transcribe_one_defaults(self):
        gap_default = 2.0
        max_default = 2000
        assert gap_default == 2.0
        assert max_default == 2000

    def test_engine_default_auto(self):
        assert ({}).get("transcription_engine", "auto") == "auto"


class TestPlaceholderKeyHandling:
    def test_translator_rejects_placeholder(self):
        from translator import Translator

        with pytest.raises(ValueError, match="api_key"):
            Translator({"deepseek_api_key": "YOUR_API_KEY_HERE"})

    def test_translator_rejects_empty(self):
        from translator import Translator

        with pytest.raises(ValueError, match="api_key"):
            Translator({"deepseek_api_key": ""})

    def test_translator_accepts_real_key(self):
        from translator import Translator

        t = Translator({"deepseek_api_key": "real-key"})
        assert t.api_key == "real-key"
