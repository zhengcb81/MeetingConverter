"""Translator 翻译路径单元测试（P3.2/P3.4）。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from translator import Translator, apply_corrections


@pytest.fixture
def translator(sample_config):
    return Translator(sample_config)


class TestTranslateParagraphNoShortCircuit:
    """P3.2: 始终送 LLM，不再因 _is_mostly_chinese 短路。"""

    def test_mixed_sent_translated(self, translator, mocker):
        mocker.patch.object(translator, "_call_api", return_value="公司Q3营收增长30%")
        result = translator.translate_paragraph("公司 Q3 revenue 同比增长30%")
        assert "营收" in result
        translator._call_api.assert_called_once()

    def test_pure_chinese_translated(self, translator, mocker):
        mocker.patch.object(translator, "_call_api", return_value="营收增长30%")
        result = translator.translate_paragraph("营收同比增长百分之三十")
        assert "营收" in result
        translator._call_api.assert_called_once()

    def test_pure_english_translated(self, translator, mocker):
        mocker.patch.object(translator, "_call_api", return_value="营收增长30%")
        result = translator.translate_paragraph("Revenue grew 30% year over year")
        assert "营收" in result
        translator._call_api.assert_called_once()

    def test_empty_text_returns_empty(self, translator, mocker):
        mock_api = mocker.patch.object(translator, "_call_api", return_value="x")
        assert translator.translate_paragraph("   ") == ""
        mock_api.assert_not_called()


class TestTranslateParagraphCorrections:
    def test_corrections_applied_after_translation(self, translator, mocker):
        mocker.patch.object(translator, "_call_api", return_value="I drove the U7")
        result = translator.translate_paragraph("原文", corrections={"U7": "SU7"})
        assert "SU7" in result
        assert "the SU7" in result

    def test_chinese_corrections_applied(self, translator, mocker):
        mocker.patch.object(translator, "_call_api", return_value="小米发布新车")
        result = translator.translate_paragraph(
            "原文", corrections={"小米": "小米集团"}
        )
        assert "小米集团" in result

    def test_no_corrections_passes_through(self, translator, mocker):
        mocker.patch.object(translator, "_call_api", return_value="营收增长")
        result = translator.translate_paragraph("orig", corrections=None)
        assert result == "营收增长"


class TestTranslateParagraphRetry:
    def test_retries_on_failure(self, translator, mocker):
        mocker.patch.object(
            translator, "_call_api", side_effect=[Exception("net"), "结果"]
        )
        mocker.patch("translator.time.sleep")
        result = translator.translate_paragraph("原文")
        assert result == "结果"
        assert translator._call_api.call_count == 2

    def test_returns_failure_marker_after_max_retries(self, translator, mocker):
        mocker.patch.object(translator, "_call_api", side_effect=Exception("boom"))
        mocker.patch("translator.time.sleep")
        result = translator.translate_paragraph("原文")
        assert "[翻译失败]" in result
        assert translator._call_api.call_count == translator.max_retries


class TestTranslateParagraphs:
    def test_translates_all(self, translator, mocker):
        mocker.patch.object(
            translator, "translate_paragraph", side_effect=["a", "b", "c"]
        )
        mocker.patch("translator.time.sleep")
        result = translator.translate_paragraphs(["p1", "p2", "p3"])
        assert result == ["a", "b", "c"]

    def test_progress_callback_invoked(self, translator, mocker):
        mocker.patch.object(translator, "translate_paragraph", return_value="x")
        mocker.patch("translator.time.sleep")
        calls = []
        translator.translate_paragraphs(
            ["p1", "p2"], progress_callback=lambda c, n: calls.append((c, n))
        )
        assert calls == [(1, 2), (2, 2)]


class TestCleanOutputOnlyTrim:
    """P3.4: _clean_output 退化为 strip。"""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("翻译结果", "翻译结果"),
            ("  翻译  ", "翻译"),
            ("结合公司背景分析", "结合公司背景分析"),
            ("第一步：分析", "第一步：分析"),
            ("\n\n结果\n\n", "结果"),
        ],
    )
    def test_clean(self, translator, text, expected):
        assert translator._clean_output(text) == expected

    def test_empty(self, translator):
        assert translator._clean_output("") == ""
        assert translator._clean_output(None) == ""
