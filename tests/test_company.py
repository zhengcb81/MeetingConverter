"""company.py 公司名匹配单元测试（P4.3）。"""

from __future__ import annotations

import pytest

from company import extract_company_from_filename, get_company_context, get_corrections


@pytest.fixture
def companies_with_substring(monkeypatch, tmp_path):
    """库中同时含'小米'与'小米集团'，用于测试子串优先级。"""
    import yaml

    data = {
        "小米": {
            "en": "Xiaomi",
            "ticker": "N/A",
            "sector": "other",
            "corrections": {"U7": "SU7"},
        },
        "小米集团": {
            "en": "Xiaomi Corporation",
            "ticker": "1810.HK",
            "sector": "消费电子",
            "corrections": {"可灵": "可灵AI"},
            "aliases": ["Xiaomi"],
        },
    }
    f = tmp_path / "companies.yaml"
    with open(f, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True)
    monkeypatch.setattr("company.COMPANIES_FILE", str(f))
    return f


class TestExactMatchPriority:
    def test_exact_name_returns_exact(self, companies_with_substring):
        assert extract_company_from_filename("小米集团") == "小米集团"

    def test_substring_prefers_longest(self, companies_with_substring):
        """查'小米集团财报20240101'应返回'小米集团'而非'小米'。"""
        result = extract_company_from_filename("小米集团财报20240101.mp3")
        assert result == "小米集团"


class TestContextLookup:
    def test_exact_company_context(self, companies_with_substring):
        ctx = get_company_context("小米集团")
        assert "1810.HK" in ctx
        assert "消费电子" in ctx

    def test_no_company_returns_empty(self):
        assert get_company_context(None) == ""
        assert get_company_context("") == ""

    def test_unknown_company_falls_back(self, companies_with_substring):
        ctx = get_company_context("完全不存在的公司")
        assert ctx == ""


class TestCorrectionsLookup:
    def test_exact_company_corrections(self, companies_with_substring):
        corrs = get_corrections("小米集团")
        assert corrs == {"可灵": "可灵AI"}

    def test_short_company_corrections(self, companies_with_substring):
        corrs = get_corrections("小米")
        assert corrs == {"U7": "SU7"}

    def test_no_corrections_for_unknown(self):
        assert get_corrections("不存在") == {}
        assert get_corrections(None) == {}


class TestAliasAndEnglishMatch:
    @pytest.fixture
    def alias_companies(self, monkeypatch, tmp_path):
        import yaml

        data = {
            "腾讯": {
                "en": "Tencent Holdings",
                "ticker": "0700.HK",
                "aliases": ["Tencent", "腾讯控股"],
            }
        }
        f = tmp_path / "companies.yaml"
        with open(f, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, allow_unicode=True)
        monkeypatch.setattr("company.COMPANIES_FILE", str(f))
        return f

    def test_english_first_word_match(self, alias_companies):
        assert extract_company_from_filename("Tencent_Q3_2024.mp3") == "腾讯"

    def test_alias_match(self, alias_companies):
        assert extract_company_from_filename("腾讯控股财报.mp3") == "腾讯"

    def test_no_match_extracts_name(self, alias_companies):
        result = extract_company_from_filename("某某公司20240101.mp3")
        assert result == "某某公司"


class TestFindCompanyKeyFallback:
    """companies.yaml 不存在时用 _FALLBACK。"""

    def test_fallback_data_used(self, monkeypatch, tmp_path):
        monkeypatch.setattr("company.COMPANIES_FILE", str(tmp_path / "noexist.yaml"))
        result = extract_company_from_filename("小米20240101.mp3")
        assert result in ("小米", "小米集团")
