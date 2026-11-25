"""engines/factory.py - 引擎工厂，根据配置与参数创建转写引擎。

支持模式:
    auto    - MiMo 优先，格式不支持/失败时回退 Whisper（默认）
    mimo    - 强制 MiMo，失败不回退
    whisper - 强制 Whisper
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Union

from config import Config, normalize_config


def create_engine(
    engine_choice: str = Config.transcription_engine,
    config: Optional[Union[Config, Mapping[str, Any]]] = None,
    whisper_model: str = Config.whisper_model,
    whisper_device: str = Config.whisper_device,
    whisper_compute_type: str = Config.whisper_compute_type,
):
    """创建转写引擎实例。

    参数:
        engine_choice: "auto"（默认）/"mimo"/"whisper"。
        config: 运行配置或原配置字典（读取 MiMo 选项）。
        whisper_model/device/compute_type: Whisper 模型参数。
    """
    if engine_choice == "whisper":
        return _create_whisper(whisper_model, whisper_device, whisper_compute_type)
    if engine_choice not in ("mimo", "auto"):
        raise ValueError(f"未知引擎: {engine_choice}（可选 auto/mimo/whisper）")

    settings = normalize_config(config)
    if engine_choice == "mimo":
        return _create_mimo(settings)
    return _create_auto(settings, whisper_model, whisper_device, whisper_compute_type)


def _create_mimo(config: Config):
    from engines.mimo import MiMoEngine

    api_key = config.mimo_api_key
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        raise ValueError("MiMo API key 未配置（config.mimo_api_key）")
    config.validate_mimo()
    return MiMoEngine(api_key=api_key, base_url=config.mimo_base_url)


def _create_whisper(model: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel
    from engines.whisper import WhisperEngine

    return WhisperEngine(WhisperModel(model, device=device, compute_type=compute_type))


def _create_auto(
    config: Config, whisper_model: str, whisper_device: str, whisper_compute_type: str
):
    from engines.fallback import FallbackEngine

    mimo_key = config.mimo_api_key
    if not mimo_key or mimo_key == "YOUR_API_KEY_HERE":
        return _create_whisper(whisper_model, whisper_device, whisper_compute_type)

    primary = _create_mimo(config)
    fallback_factory = lambda: _create_whisper(
        whisper_model, whisper_device, whisper_compute_type
    )
    return FallbackEngine(primary, fallback_factory)
