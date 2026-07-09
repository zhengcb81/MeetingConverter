"""共享测试 fixtures。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def tmp_output_dir(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    return out


@pytest.fixture
def sample_text():
    return (
        "Our revenue in the third quarter reached 12.5 billion yuan, "
        "representing a year-over-year growth of 30%. Gross margin improved "
        "to 21.5%. We expect strong momentum to continue into Q4."
    )


@pytest.fixture
def whisper_segments():
    """模拟 faster-whisper 返回的 segment 序列（生成器）。"""
    segs = [
        SimpleNamespace(start=0.0, end=2.5, text="Our revenue in the third quarter "),
        SimpleNamespace(start=2.5, end=5.0, text="reached 12.5 billion yuan, "),
        SimpleNamespace(
            start=5.0, end=7.5, text="representing year-over-year growth of 30%."
        ),
        SimpleNamespace(start=7.5, end=8.0, text="   "),
    ]
    return iter(segs)


@pytest.fixture
def whisper_info():
    return SimpleNamespace(
        language="en",
        language_probability=0.98,
        duration=8.0,
    )


@pytest.fixture
def mock_whisper_model(mocker, whisper_segments, whisper_info):
    """构造一个已配置好的 faster-whisper 模型 mock。"""
    model = mocker.MagicMock()
    model.transcribe.return_value = (whisper_segments, whisper_info)
    return model


@pytest.fixture
def sample_config():
    return {
        "deepseek_api_key": "test-key",
        "deepseek_base_url": "https://api.deepseek.com",
        "deepseek_model": "deepseek-v4-flash",
        "whisper_model": "small",
        "whisper_device": "cpu",
        "whisper_compute_type": "int8",
        "language": None,
        "paragraph_merge_gap_sec": 2.0,
        "paragraph_max_chars": 2000,
        "translate_batch_size": 5,
        "translate_max_retries": 3,
        "mimo_api_key": "test-mimo-key",
        "mimo_base_url": "https://api.xiaomimimo.com",
        "transcription_engine": "auto",
    }


@pytest.fixture
def sample_companies_yaml(tmp_path):
    data = {
        "小米集团": {
            "en": "Xiaomi Corporation",
            "ticker": "1810.HK",
            "sector": "消费电子",
            "aliases": ["Xiaomi", "小米"],
            "corrections": {"U7": "YU7"},
        },
        "小米": {
            "en": "Xiaomi",
            "ticker": "N/A",
            "sector": "other",
            "corrections": {},
        },
    }
    path = tmp_path / "companies.yaml"
    import yaml

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True)
    return path
