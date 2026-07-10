"""transcribe_one 集成测试（P3.2/P3.3）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from engines.base import Segment, TranscriptionResult
from core import transcribe_one


@pytest.fixture
def audio_file(tmp_path):
    f = tmp_path / "meeting.mp3"
    f.write_bytes(b"\x00" * 1024)
    return f


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.transcribe.return_value = TranscriptionResult(
        language="en",
        language_probability=0.95,
        duration=60.0,
        segments=[
            Segment(start=0.0, end=30.0, text="Revenue grew 30% year over year."),
            Segment(start=30.0, end=60.0, text="Gross margin improved to 21.5%."),
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
        result = transcribe_one(
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
