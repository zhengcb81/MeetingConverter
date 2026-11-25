"""MeetingConverter 的文件读取、缺省值与显式校验入口。"""

from __future__ import annotations

import json
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


def load_config(config_path: Optional[str] = None) -> dict:
    """读取原始配置，显式路径优先，其次是项目自有 config.json。"""
    paths = (config_path, os.path.join(os.path.dirname(__file__) or ".", "config.json"))
    for path in paths:
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as stream:
                return json.load(stream)
    raise FileNotFoundError("找不到配置文件，请确保项目目录下 config.json 存在")


def normalize_config(values: Optional[Union[Config, Mapping[str, Any]]] = None) -> Config:
    """应用本仓缺省值，并复用已解析的运行配置。"""
    if isinstance(values, Config):
        return values
    return Config.from_dict(values or {})


def load_and_validate(config_path: Optional[str] = None) -> Config:
    """加载、验证并返回配置对象。"""
    return Config.load(config_path)


def validate_config(config: Mapping[str, Any]) -> None:
    """保留旧字典入口的显式配置校验。"""
    _validate(normalize_config(config))


def _validate(config: Config) -> None:
    if config.deepseek_api_key == "YOUR_API_KEY_HERE":
        raise ConfigError("deepseek_api_key 未配置（仍为默认占位符）")

    base_url = config.deepseek_base_url
    if base_url and not base_url.startswith(("http://", "https://")):
        raise ConfigError(f"deepseek_base_url 格式无效: {base_url}")

    mimo_url = config.mimo_base_url
    if mimo_url and not mimo_url.startswith(("http://", "https://")):
        raise ConfigError(f"mimo_base_url 格式无效: {mimo_url}")

    merge_gap = config.paragraph_merge_gap_sec
    if not isinstance(merge_gap, (int, float)) or merge_gap < 0:
        raise ConfigError(f"paragraph_merge_gap_sec 必须为非负数: {merge_gap}")

    max_chars = config.paragraph_max_chars
    if not isinstance(max_chars, int) or max_chars < 100:
        raise ConfigError(f"paragraph_max_chars 必须 >= 100: {max_chars}")

    batch_size = config.translate_batch_size
    if not isinstance(batch_size, int) or batch_size < 1:
        raise ConfigError(f"translate_batch_size 必须 >= 1: {batch_size}")

    retries = config.translate_max_retries
    if not isinstance(retries, int) or retries < 0:
        raise ConfigError(f"translate_max_retries 必须 >= 0: {retries}")
