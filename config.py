"""config.py - 配置数据类，类型安全的配置访问。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from translator import load_config
from config_validator import validate_config
from exceptions import ConfigError


@dataclass
class Config:
    """应用配置，带默认值和类型安全访问。"""

    # DeepSeek 翻译配置
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"

    # MiMo ASR 配置
    mimo_api_key: str = ""
    mimo_base_url: str = "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"

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
    def from_dict(cls, data: dict) -> Config:
        """从字典构造配置，忽略未知键。"""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    @classmethod
    def load(cls, config_path: str = None) -> Config:
        """加载并验证配置。"""
        raw = load_config(config_path)
        validate_config(raw)
        return cls.from_dict(raw)


def load_and_validate(config_path: str = None) -> Config:
    """加载、验证并返回配置对象。"""
    return Config.load(config_path)
