"""config_validator.py - 配置验证工具。"""

from __future__ import annotations

from exceptions import ConfigError


def validate_config(config: dict) -> None:
    """验证配置有效性，无效时抛 ConfigError。"""
    # API key 格式
    deepseek_key = config.get("deepseek_api_key", "")
    if deepseek_key and deepseek_key == "YOUR_API_KEY_HERE":
        raise ConfigError("deepseek_api_key 未配置（仍为默认占位符）")

    # URL 格式
    base_url = config.get("deepseek_base_url", "")
    if base_url and not base_url.startswith(("http://", "https://")):
        raise ConfigError(f"deepseek_base_url 格式无效: {base_url}")

    mimo_url = config.get("mimo_base_url", "")
    if mimo_url and not mimo_url.startswith(("http://", "https://")):
        raise ConfigError(f"mimo_base_url 格式无效: {mimo_url}")

    # 数值范围
    merge_gap = config.get("paragraph_merge_gap_sec", 2.0)
    if not isinstance(merge_gap, (int, float)) or merge_gap < 0:
        raise ConfigError(f"paragraph_merge_gap_sec 必须为非负数: {merge_gap}")

    max_chars = config.get("paragraph_max_chars", 2000)
    if not isinstance(max_chars, int) or max_chars < 100:
        raise ConfigError(f"paragraph_max_chars 必须 >= 100: {max_chars}")

    batch_size = config.get("translate_batch_size", 5)
    if not isinstance(batch_size, int) or batch_size < 1:
        raise ConfigError(f"translate_batch_size 必须 >= 1: {batch_size}")

    max_retries = config.get("translate_max_retries", 3)
    if not isinstance(max_retries, int) or max_retries < 0:
        raise ConfigError(f"translate_max_retries 必须 >= 0: {max_retries}")
