"""模块级 apply_corrections 单元测试（P3.2/P5.2）。"""

from __future__ import annotations

from translator import apply_corrections


class TestApplyCorrectionsBasic:
    def test_no_corrections_returns_original(self):
        assert apply_corrections("hello world", None) == "hello world"

    def test_empty_corrections_returns_original(self):
        assert apply_corrections("hello world", {}) == "hello world"

    def test_empty_text_returns_original(self):
        assert apply_corrections("", {"U7": "SU7"}) == ""

    def test_simple_replacement(self):
        assert (
            apply_corrections("I drove the U7 today", {"U7": "SU7"})
            == "I drove the SU7 today"
        )

    def test_no_match_returns_original(self):
        assert apply_corrections("no match here", {"U7": "SU7"}) == "no match here"


class TestEnglishWordBoundary:
    def test_word_boundary_protects_substring(self):
        text = "SU7 is already correct, but U7 needs fixing"
        result = apply_corrections(text, {"U7": "SU7"})
        assert "SU7 is already correct" in result
        assert "SU7 needs fixing" in result
        assert "SUSU7" not in result

    def test_case_sensitive(self):
        assert apply_corrections("u7 and U7", {"U7": "SU7"}) == "u7 and SU7"

    def test_multiple_occurrences(self):
        assert apply_corrections("U7 U7 U7", {"U7": "SU7"}) == "SU7 SU7 SU7"

    def test_punctuation_adjacent(self):
        assert (
            apply_corrections("saw the U7, then U7.", {"U7": "SU7"})
            == "saw the SU7, then SU7."
        )


class TestChineseReplacement:
    def test_chinese_key_replaces(self):
        assert (
            apply_corrections("小米发布了新车", {"小米": "小米集团"})
            == "小米集团发布了新车"
        )

    def test_chinese_long_key_priority(self):
        result = apply_corrections(
            "小米集团财报", {"小米": "Xiaomi", "小米集团": "Xiaomi Corp"}
        )
        assert result == "Xiaomi Corp财报"

    def test_chinese_mixed_with_english(self):
        result = apply_corrections("Q3营收同比增长30%", {"营收": "revenue"})
        assert "Q3revenue同比增长30%" == result


class TestCleanOutputSimplified:
    """P3.4: _clean_output 仅 trim，不再误删合法翻译。"""

    def test_normal_translation_preserved(self, sample_config):
        from translator import Translator

        t = Translator(sample_config)
        assert t._clean_output("这是一段正常翻译") == "这是一段正常翻译"

    def test_starts_with_jiehe_preserved(self, sample_config):
        from translator import Translator

        t = Translator(sample_config)
        assert (
            t._clean_output("结合公司背景，营收增长30%") == "结合公司背景，营收增长30%"
        )

    def test_starts_with_step_preserved(self, sample_config):
        from translator import Translator

        t = Translator(sample_config)
        assert t._clean_output("第一步：分析财务数据") == "第一步：分析财务数据"

    def test_empty_returns_empty(self, sample_config):
        from translator import Translator

        t = Translator(sample_config)
        assert t._clean_output("") == ""
        assert t._clean_output(None) == ""

    def test_whitespace_stripped(self, sample_config):
        from translator import Translator

        t = Translator(sample_config)
        assert t._clean_output("  \n 翻译结果  \n") == "翻译结果"
