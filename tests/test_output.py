"""tests/test_output.py - core.output 单元测试。"""

from __future__ import annotations

import pytest
from core.output import write_original, write_translated, write_bilingual
from core.pipeline import Paragraph
from engines.base import Segment


def _make_paragraph(start, end, text):
    p = Paragraph()
    p.start = start
    p.end = end
    p.text = text
    p.segments = [Segment(start=start, end=end, text=text)]
    return p


@pytest.fixture
def sample_paragraphs():
    return [
        _make_paragraph(0.0, 10.0, "Revenue grew 30% year over year."),
        _make_paragraph(10.0, 20.0, "Gross margin improved to 21.5%."),
    ]


@pytest.fixture
def sample_meta():
    return {
        "filename": "earnings_call.mp3",
        "language": "en",
        "language_prob": 0.95,
        "duration": 120.0,
        "elapsed": 5.3,
        "company_name": "Xiaomi",
        "translator_model": "deepseek-v4-flash",
    }


class TestWriteOriginal:
    def test_basic_content(self, sample_paragraphs, sample_meta, tmp_path):
        out = tmp_path / "original.txt"
        write_original(out, sample_paragraphs, sample_meta, timestamps=False)
        content = out.read_text(encoding="utf-8")
        assert "earnings_call.mp3" in content
        assert "Revenue grew 30%" in content
        assert "Gross margin improved" in content

    def test_with_timestamps(self, sample_paragraphs, sample_meta, tmp_path):
        out = tmp_path / "original.txt"
        write_original(out, sample_paragraphs, sample_meta, timestamps=True)
        content = out.read_text(encoding="utf-8")
        assert "[00:00:00 -> 00:00:10]" in content

    def test_header_info(self, sample_paragraphs, sample_meta, tmp_path):
        out = tmp_path / "original.txt"
        write_original(out, sample_paragraphs, sample_meta, timestamps=False)
        content = out.read_text(encoding="utf-8")
        assert "检测语言: en" in content
        assert "段落数量: 2" in content


class TestWriteTranslated:
    def test_basic_content(self, sample_paragraphs, sample_meta, tmp_path):
        translations = ["营收同比增长30%", "毛利率提升至21.5%"]
        out = tmp_path / "translated.txt"
        write_translated(out, sample_paragraphs, translations, sample_meta, timestamps=False)
        content = out.read_text(encoding="utf-8")
        assert "营收同比增长30%" in content
        assert "毛利率提升至21.5%" in content

    def test_company_name_in_header(self, sample_paragraphs, sample_meta, tmp_path):
        translations = ["t1", "t2"]
        out = tmp_path / "translated.txt"
        write_translated(out, sample_paragraphs, translations, sample_meta, timestamps=False)
        content = out.read_text(encoding="utf-8")
        assert "Xiaomi" in content


class TestWriteBilingual:
    def test_both_languages(self, sample_paragraphs, sample_meta, tmp_path):
        translations = ["营收同比增长30%", "毛利率提升至21.5%"]
        out = tmp_path / "bilingual.txt"
        write_bilingual(out, sample_paragraphs, translations, sample_meta, timestamps=False)
        content = out.read_text(encoding="utf-8")
        assert "【原文】" in content
        assert "【中文】" in content
        assert "Revenue grew 30%" in content
        assert "营收同比增长30%" in content
