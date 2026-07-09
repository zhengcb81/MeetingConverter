"""text_merger 单元测试。"""

from __future__ import annotations

from text_merger import merge_text_into_paragraphs, _split_sentences, _hard_split
from engines.base import Segment


class TestSplitSentences:
    def test_chinese_enders(self):
        sents = _split_sentences("今天天气好。明天会更好！是吗？")
        assert sents == ["今天天气好。", "明天会更好！", "是吗？"]

    def test_english_enders(self):
        sents = _split_sentences("Revenue grew. Profit fell! What happened?")
        assert sents == ["Revenue grew.", " Profit fell!", " What happened?"]

    def test_newline_breaks(self):
        sents = _split_sentences("第一行\n第二行")
        assert sents == ["第一行\n", "第二行"]

    def test_no_ender_keeps_tail(self):
        sents = _split_sentences("无标点结尾")
        assert sents == ["无标点结尾"]


class TestHardSplit:
    def test_splits_at_max(self):
        result = _hard_split("abcdefghij", 3)
        assert result == ["abc", "def", "ghi", "j"]

    def test_short_unchanged(self):
        assert _hard_split("abc", 10) == ["abc"]


class TestMergeTextIntoParagraphs:
    def test_empty_text(self):
        assert merge_text_into_paragraphs("") == []
        assert merge_text_into_paragraphs("   ") == []

    def test_single_sentence(self):
        result = merge_text_into_paragraphs("一句话。")
        assert len(result) == 1
        assert isinstance(result[0], Segment)
        assert result[0].text == "一句话。"
        assert result[0].start == 0.0
        assert result[0].end == 0.0

    def test_accumulate_until_max_chars(self):
        text = "短句一。短句二。短句三。短句四。短句五。"
        result = merge_text_into_paragraphs(text, max_chars=12)
        assert len(result) >= 2
        assert all(len(s.text) <= 12 for s in result)

    def test_oversized_sentence_hard_split(self):
        long_sent = "A" * 50 + "。"
        result = merge_text_into_paragraphs(long_sent, max_chars=20)
        assert len(result) == 3
        assert all(len(s.text) <= 20 for s in result)

    def test_strips_whitespace(self):
        result = merge_text_into_paragraphs("  内容。  ")
        assert result[0].text == "内容。"

    def test_mixed_punctuation(self):
        text = "营收增长30%。EBITDA提升！guidance上调？继续持有。"
        result = merge_text_into_paragraphs(text, max_chars=100)
        assert len(result) == 1
        assert result[0].text == text

    def test_all_segments_zero_timestamp(self):
        result = merge_text_into_paragraphs("句一。句二。", max_chars=5)
        for seg in result:
            assert seg.start == 0.0
            assert seg.end == 0.0

    def test_consecutive_enders(self):
        result = merge_text_into_paragraphs("什么？！真的。")
        texts = [s.text for s in result]
        assert "什么？！" in "".join(texts) or any("什么" in t for t in texts)
