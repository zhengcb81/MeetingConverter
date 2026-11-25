"""transcribe_one 集成测试（P3.2/P3.3）。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core import transcribe_one
from engines.base import Segment, TranscriptionResult


@pytest.fixture
def audio_file(tmp_path):
    f = tmp_path / "meeting.mp3"
    f.write_bytes(b"\x00" * 1024)
    return f


@pytest.fixture
def mock_engine():
    """两段间隔 5 秒（> 现有 2 秒合并阈值），因此不会被合并成一段。

    旧 fixture 的第二段 start=30.0 与第一段 end=30.0 相接，间隔为 0，
    会被 ``merge_into_paragraphs`` 合并成一段；而译文夹具固定返回两段，
    于是已验收的 writer 正确地以 OutputCountMismatchError 拒绝了它。
    """
    engine = MagicMock()
    engine.transcribe.return_value = TranscriptionResult(
        language="en",
        language_probability=0.95,
        duration=60.0,
        segments=[
            Segment(start=0.0, end=30.0, text="Revenue grew 30% year over year."),
            Segment(start=35.0, end=60.0, text="Gross margin improved to 21.5%."),
        ],
    )
    return engine


@pytest.fixture
def mock_translator():
    t = MagicMock()
    t.model = "deepseek-v4-flash"
    t.translate_paragraphs.return_value = ["营收同比增长30%", "毛利率提升至21.5%"]
    return t


class TestNoTranslateOneFile:
    """P3.3: --no-translate 时 translator_obj=None，仅产 _原文.txt。"""

    def test_only_original_file_written(self, mock_engine, audio_file, tmp_output_dir):
        transcribe_one(
            mock_engine,
            audio_file,
            tmp_output_dir,
            translator_obj=None,
        )
        files = list(tmp_output_dir.iterdir())
        assert len(files) == 1
        assert files[0].name == "meeting_原文.txt"
        assert "Revenue grew 30%" in files[0].read_text(encoding="utf-8")

    def test_no_translation_file(self, mock_engine, audio_file, tmp_output_dir):
        transcribe_one(mock_engine, audio_file, tmp_output_dir, translator_obj=None)
        assert not (tmp_output_dir / "meeting_翻译.txt").exists()

    def test_no_bilingual_file(self, mock_engine, audio_file, tmp_output_dir):
        transcribe_one(mock_engine, audio_file, tmp_output_dir, translator_obj=None)
        assert not (tmp_output_dir / "meeting_中英对照.txt").exists()


class TestWithTranslateThreeFiles:
    """启用翻译时产 3 个文件。"""

    def test_three_files_written(
        self, mock_engine, mock_translator, audio_file, tmp_output_dir
    ):
        transcribe_one(
            mock_engine,
            audio_file,
            tmp_output_dir,
            translator_obj=mock_translator,
        )
        files = sorted(f.name for f in tmp_output_dir.iterdir())
        assert "meeting_原文.txt" in files
        assert "meeting_翻译.txt" in files
        assert "meeting_中英对照.txt" in files

    def test_translation_content(
        self, mock_engine, mock_translator, audio_file, tmp_output_dir
    ):
        transcribe_one(
            mock_engine,
            audio_file,
            tmp_output_dir,
            translator_obj=mock_translator,
        )
        content = (tmp_output_dir / "meeting_翻译.txt").read_text(encoding="utf-8")
        assert "营收同比增长30%" in content

    def test_bilingual_pairs(
        self, mock_engine, mock_translator, audio_file, tmp_output_dir
    ):
        transcribe_one(
            mock_engine,
            audio_file,
            tmp_output_dir,
            translator_obj=mock_translator,
        )
        content = (tmp_output_dir / "meeting_中英对照.txt").read_text(encoding="utf-8")
        assert "Revenue grew 30%" in content
        assert "营收同比增长30%" in content

    def test_translator_receives_two_paragraphs(
        self, mock_engine, mock_translator, audio_file, tmp_output_dir
    ):
        """译文夹具的两段对应真实的两段：translator 收到两段，不是合并后的一段。"""
        transcribe_one(
            mock_engine,
            audio_file,
            tmp_output_dir,
            translator_obj=mock_translator,
        )
        mock_translator.translate_paragraphs.assert_called_once()
        paragraphs = mock_translator.translate_paragraphs.call_args[0][0]
        assert len(paragraphs) == 2
        assert "Revenue grew 30%" in paragraphs[0]
        assert "Gross margin improved" in paragraphs[1]


class TestParagraphLevelEngine:
    """MiMo paragraph_level=True 时不重复合并。"""

    def test_paragraph_level_skips_merge(self, audio_file, tmp_output_dir):
        engine = MagicMock()
        engine.transcribe.return_value = TranscriptionResult(
            language="zh",
            language_probability=1.0,
            duration=60.0,
            segments=[Segment(0.0, 0.0, "第一段。"), Segment(0.0, 0.0, "第二段。")],
            paragraph_level=True,
        )
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        orig = (tmp_output_dir / "meeting_原文.txt").read_text(encoding="utf-8")
        assert "第一段" in orig
        assert "第二段" in orig


class TestMimoEngineFallback:
    """auto 模式：m4a 文件回退 Whisper（mock 验证回退触发）。"""

    def test_unsupported_format_falls_back(self, audio_file, tmp_output_dir, mocker):
        from engines.base import UnsupportedFormatError
        from engines.fallback import FallbackEngine

        primary = MagicMock()
        primary.transcribe.side_effect = UnsupportedFormatError("m4a")
        fallback = MagicMock()
        fallback.transcribe.return_value = TranscriptionResult(
            "en",
            0.9,
            60.0,
            [
                Segment(0.0, 30.0, "fallback result"),
            ],
        )
        engine = FallbackEngine(primary, lambda: fallback)
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        orig = (tmp_output_dir / "meeting_原文.txt").read_text(encoding="utf-8")
        assert "fallback result" in orig


class TestCorrectionsAppliedInTranscribe:
    """transcribe_one 流程中 corrections 经由 translator.apply_corrections 应用。"""

    def test_corrections_passed_through(
        self, mock_engine, mock_translator, audio_file, tmp_output_dir
    ):
        transcribe_one(
            mock_engine,
            audio_file,
            tmp_output_dir,
            translator_obj=mock_translator,
            corrections={"U7": "SU7"},
        )
        mock_translator.translate_paragraphs.assert_called_once()
        _, kwargs = mock_translator.translate_paragraphs.call_args
        assert kwargs["corrections"] == {"U7": "SU7"}


def test_cli_context_uses_owned_company_record_without_reading_external_graph(
    mock_engine, mock_translator, tmp_path, monkeypatch
):
    import builtins
    import sys
    from pathlib import Path

    import yaml

    import company
    import transcribe

    audio = tmp_path / "FinDeskAlias_20260701.mp3"
    audio.write_bytes(b"synthetic audio")
    output = tmp_path / "results"
    catalog = tmp_path / "companies.yaml"
    catalog.write_text(
        yaml.safe_dump(
            {
                "合成子午集团": {
                    "en": "Meridian Systems",
                    "aliases": ["FinDeskAlias"],
                    "ticker": "TEST",
                    "sector": "系统",
                    "products": ["合成产品"],
                    "notes": "合成注意事项",
                    "position": "本仓定位",
                    "sectors": ["本仓板块甲", "本仓板块乙"],
                    "corrections": {"AI leg": "AI segment"},
                }
            },
            allow_unicode=True,
        ),
        encoding="utf8",
    )
    external = tmp_path / "synthetic-home" / "company-wiki"
    external.mkdir(parents=True)
    graph = external / "graph.yaml"
    graph.write_text(
        "companies:\n  合成子午集团:\n    position: 外仓错误定位\n    sectors: [外仓错误板块]\n",
        encoding="utf8",
    )
    reads = []
    real_open = builtins.open

    def observe_reads(file, *args, **kwargs):
        if isinstance(file, (str, Path)) and Path(file) == graph:
            reads.append(file)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", observe_reads)
    monkeypatch.setattr(company, "COMPANIES_FILE", str(catalog))
    monkeypatch.setattr(company, "COMPANY_WIKI_PATH", str(external), raising=False)
    monkeypatch.setattr(transcribe, "load_config", lambda: {})
    monkeypatch.setattr(transcribe, "create_engine", lambda *args: mock_engine)
    monkeypatch.setattr(transcribe, "Translator", lambda cfg: mock_translator)
    monkeypatch.setenv("RESEARCH_FEEDBACK_DIR", str(tmp_path / "feedback"))
    monkeypatch.setenv("RESEARCH_FEEDBACK_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("RESEARCH_FEEDBACK_OUT", raising=False)
    monkeypatch.setattr(sys, "argv", ["transcribe.py", str(audio), "--output", str(output)])

    assert transcribe.main() == 0
    assert reads == []
    mock_engine.transcribe.assert_called_once()
    mock_translator.translate_paragraphs.assert_called_once()
    call = mock_translator.translate_paragraphs.call_args
    assert call.kwargs["company_context"].splitlines() == [
        "公司: 合成子午集团 (Meridian Systems)",
        "代码: TEST",
        "行业: 系统",
        "主要产品: 合成产品",
        "注意事项: 合成注意事项",
        "定位: 本仓定位",
        "板块: 本仓板块甲, 本仓板块乙",
    ]
    assert call.kwargs["corrections"] == {"AI leg": "AI segment"}
    assert sorted(path.name for path in output.iterdir()) == sorted(
        f"{audio.stem}_{role}.txt" for role in ("原文", "翻译", "中英对照")
    )
