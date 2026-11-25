"""MeetingConverter 的文件读取、缺省值与显式校验入口。"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, fields
from typing import Any, Mapping, Optional, Union

from exceptions import ConfigError

DEFAULT_MIMO_URL = "https://api.xiaomimimo.com/v1/chat/completions"


@dataclass
class Config:
    """应用配置，带默认值和类型安全访问。"""

    # DeepSeek 翻译配置
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"

    # MiMo ASR 配置
    mimo_api_key: str = ""
    mimo_base_url: str = DEFAULT_MIMO_URL

    # Whisper 配置
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # 转写配置
    transcription_engine: str = "auto"
    language: Optional[str] = None
    paragraph_merge_gap_sec: float = 2.0
    paragraph_max_chars: int = 2000

    # 翻译配置
    translate_batch_size: int = 5
    translate_max_retries: int = 3
    translate_api_timeout: int = 120
    translate_paragraph_delay: float = 0.3

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Config:
        """从字典构造配置，忽略未知键。"""
        known = {item.name for item in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> Config:
        """加载并显式验证配置。"""
        settings = cls.from_dict(load_config(config_path))
        _validate(settings)
        return settings

    def validate_transcription(self) -> None:
        """Check settings consumed regardless of the selected engine."""
        _validate_nonnegative_number("paragraph_merge_gap_sec", self.paragraph_merge_gap_sec)
        _validate_integer("paragraph_max_chars", self.paragraph_max_chars, minimum=100)

    def validate_translation(self) -> None:
        """Check translation settings only when translation is configured for use."""
        if self.deepseek_api_key == "YOUR_API_KEY_HERE":
            raise ConfigError("deepseek_api_key 未配置（仍为默认占位符）")
        _validate_url("deepseek_base_url", self.deepseek_base_url)
        _validate_integer("translate_batch_size", self.translate_batch_size, minimum=1)
        _validate_integer("translate_max_retries", self.translate_max_retries, minimum=0)
        _validate_integer("translate_api_timeout", self.translate_api_timeout, minimum=1)
        _validate_nonnegative_number("translate_paragraph_delay", self.translate_paragraph_delay)

    def validate_mimo(self) -> None:
        """Check the endpoint when a MiMo engine is selected."""
        _validate_url("mimo_base_url", self.mimo_base_url)


def load_config(config_path: Optional[str] = None) -> dict:
    """读取原始配置，显式路径优先，其次是项目自有 config.json。"""
    paths = (config_path, os.path.join(os.path.dirname(__file__) or ".", "config.json"))
    for path in paths:
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as stream:
                return json.load(stream)
    raise FileNotFoundError("找不到配置文件，请确保项目目录下 config.json 存在")


def normalize_config(values: Optional[Union[Config, Mapping[str, Any]]] = None) -> Config:
    """应用本仓缺省值。各调用入口校验自己使用的配置。"""
    if isinstance(values, Config):
        return values
    if values is not None and not isinstance(values, Mapping):
        raise ConfigError("配置必须是 JSON 对象")
    return Config.from_dict(values or {})


def load_and_validate(config_path: Optional[str] = None) -> Config:
    """加载、验证并返回配置对象。"""
    return Config.load(config_path)


def validate_config(config: Mapping[str, Any]) -> None:
    """保留旧字典入口的显式配置校验。"""
    _validate(normalize_config(config))


def _validate(config: Config) -> None:
    config.validate_transcription()
    config.validate_translation()
    config.validate_mimo()


def _validate_url(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise ConfigError(f"{name} 格式无效")


def _validate_integer(name: str, value: Any, *, minimum: int) -> None:
    if type(value) is not int or value < minimum:
        raise ConfigError(f"{name} 必须为整数且 >= {minimum}")


def _validate_nonnegative_number(name: str, value: Any) -> None:
    if (
        type(value) not in (int, float)
        or (isinstance(value, float) and not math.isfinite(value))
        or value < 0
    ):
        raise ConfigError(f"{name} 必须为有限的非负数")
