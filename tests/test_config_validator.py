"""tests/test_config_validator.py - config_validator 单元测试。"""

from __future__ import annotations

import pytest

from config_validator import validate_config
from exceptions import ConfigError


class TestValidateConfig:
    def test_valid_config(self, sample_config):
        """有效配置不应抛异常。"""
        validate_config(sample_config)

    def test_placeholder_api_key_raises(self, sample_config):
        sample_config["deepseek_api_key"] = "YOUR_API_KEY_HERE"
        with pytest.raises(ConfigError, match="未配置"):
            validate_config(sample_config)

    def test_invalid_base_url_raises(self, sample_config):
        sample_config["deepseek_base_url"] = "not-a-url"
        with pytest.raises(ConfigError, match="格式无效"):
            validate_config(sample_config)

    def test_invalid_mimo_url_raises(self, sample_config):
        sample_config["mimo_base_url"] = "ftp://invalid"
        with pytest.raises(ConfigError, match="格式无效"):
            validate_config(sample_config)

    def test_negative_merge_gap_raises(self, sample_config):
        sample_config["paragraph_merge_gap_sec"] = -1.0
        with pytest.raises(ConfigError, match="非负数"):
            validate_config(sample_config)

    def test_small_max_chars_raises(self, sample_config):
        sample_config["paragraph_max_chars"] = 50
        with pytest.raises(ConfigError, match=">= 100"):
            validate_config(sample_config)

    def test_zero_batch_size_raises(self, sample_config):
        sample_config["translate_batch_size"] = 0
        with pytest.raises(ConfigError, match=">= 1"):
            validate_config(sample_config)

    def test_valid_urls(self, sample_config):
        sample_config["deepseek_base_url"] = "https://api.deepseek.com"
        sample_config["mimo_base_url"] = "http://localhost:8080"
        validate_config(sample_config)
