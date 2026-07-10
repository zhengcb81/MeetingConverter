"""tests/test_pipeline.py - core.pipeline 单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.pipeline import Paragraph, merge_into_paragraphs, transcribe_one
from engines.base import Segment, TranscriptionResult


# ── Paragraph ─────────────────────────────────────────────────────


class TestParagraph:
    def test_empty_paragraph(self):
        p = Paragraph()
        assert p.start == 0.0
        assert p.end == 0.0
        assert p.text == ""
        assert p.segments == []

    def test_add_single_segment(self):
        p = Paragraph()
        p.add_segment(Segment(start=1.0, end=2.0, text="hello "))
        assert p.start == 1.0
        assert p.end == 2.0
        assert "hello" in p.text

    def test_add_multiple_segments_updates_end(self):
        p = Paragraph()
        p.add_segment(Segment(start=1.0, end=2.0, text="a "))
        p.add_segment(Segment(start=3.0, end=5.0, text="b "))
        assert p.start == 1.0
        assert p.end == 5.0
        assert len(p.segments) == 2

    def test_finalize_strips_text(self):
        p = Paragraph()
        p.add_segment(Segment(start=0.0, end=1.0, text="  hello  "))
        p.finalize()
        assert p.text == "hello"


# ── merge_into_paragraphs ─────────────────────────────────────────


class TestMergeIntoParagraphs:
    def test_empty_input(self):
        assert merge_into_paragraphs([]) == []

    def test_single_segment(self):
        segments = [Segment(start=0.0, end=1.0, text="Hello world.")]
        result = merge_into_paragraphs(segments)
        assert len(result) == 1
        assert "Hello world" in result[0].text

    def test_gap_triggers_split(self):
        segments = [
            Segment(start=0.0, end=1.0, text="First sentence."),
            Segment(start=5.0, end=6.0, text="Second sentence."),  # gap=4s
        ]
        result = merge_into_paragraphs(segments, gap_threshold=2.0)
        assert len(result) == 2

    def test_no_gap_merges(self):
        segments = [
            Segment(start=0.0, end=1.0, text="First."),
            Segment(start=1.1, end=2.0, text="Second."),
        ]
        result = merge_into_paragraphs(segments, gap_threshold=2.0)
        assert len(result) == 1

    def test_max_chars_triggers_split(self):
        long_text = "x" * 1500
        segments = [
            Segment(start=0.0, end=1.0, text=long_text),
            Segment(start=1.0, end=2.0, text="more text"),
        ]
        result = merge_into_paragraphs(segments, max_chars=2000)
        # After the long segment, current.text is ~1500 chars
        # Adding "more text" would make it >1500 but <2000, so no split
        # But if we set max_chars=1000, it should split
        result2 = merge_into_paragraphs(segments, max_chars=1000)
        assert len(result2) >= 2

    def test_empty_segments_skipped(self):
        segments = [
            Segment(start=0.0, end=1.0, text="Hello."),
            Segment(start=1.0, end=2.0, text="   "),  # whitespace only
            Segment(start=2.0, end=3.0, text="World."),
        ]
        result = merge_into_paragraphs(segments)
        assert len(result) == 1
        assert "Hello" in result[0].text
        assert "World" in result[0].text


# ── transcribe_one ────────────────────────────────────────────────


@pytest.fixture
def audio_file(tmp_path):
    f = tmp_path / "test.mp3"
    f.write_bytes(b"\x00" * 1024)
    return f


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.transcribe.return_value = TranscriptionResult(
        language="en",
        language_probability=0.95,
        duration=30.0,
        segments=[
            Segment(start=0.0, end=15.0, text="Revenue grew 30%."),
            Segment(start=15.0, end=30.0, text="Profit margins improved."),
        ],
    )
    return engine


class TestTranscribeOne:
    def test_skip_existing_file(self, mock_engine, audio_file, tmp_output_dir):
        # Pre-create the output file
        (tmp_output_dir / "test_原文.txt").write_text("existing")
        result = transcribe_one(
            mock_engine, audio_file, tmp_output_dir, force=False
        )
        assert result is None
        mock_engine.transcribe.assert_not_called()

    def test_force_reprocesses(self, mock_engine, audio_file, tmp_output_dir):
        (tmp_output_dir / "test_原文.txt").write_text("existing")
        result = transcribe_one(
            mock_engine, audio_file, tmp_output_dir, force=True
        )
        assert result is not None
        mock_engine.transcribe.assert_called_once()

    def test_returns_summary_dict(self, mock_engine, audio_file, tmp_output_dir):
        result = transcribe_one(
            mock_engine, audio_file, tmp_output_dir, translator_obj=None
        )
        assert result is not None
        assert "input" in result
        assert "paragraphs" in result
        assert "language" in result
        assert "duration" in result
        assert "elapsed" in result
        assert "text_length" in result
        assert result["language"] == "en"
        assert result["duration"] == 30.0
        assert result["paragraphs"] >= 1

    def test_creates_original_file(self, mock_engine, audio_file, tmp_output_dir):
        transcribe_one(mock_engine, audio_file, tmp_output_dir, translator_obj=None)
        orig = tmp_output_dir / "test_原文.txt"
        assert orig.exists()
        content = orig.read_text(encoding="utf-8")
        assert "Revenue grew 30%" in content

    def test_translation_failure_skips_translation_files(
        self, mock_engine, audio_file, tmp_output_dir
    ):
        """翻译失败时跳过翻译文件，但仍创建原文文件。"""
        from exceptions import TranslationError

        translator = MagicMock()
        translator.model = "test"
        translator.translate_paragraphs.side_effect = TranslationError("翻译失败")
        result = transcribe_one(
            mock_engine,
            audio_file,
            tmp_output_dir,
            translator_obj=translator,
        )
        # 原文文件应存在
        assert (tmp_output_dir / "test_原文.txt").exists()
        # 翻译文件不应存在
        assert not (tmp_output_dir / "test_翻译.txt").exists()
        assert not (tmp_output_dir / "test_中英对照.txt").exists()
        assert result is not None

    def test_engine_failure_propagates(self, audio_file, tmp_output_dir):
        """引擎转写失败应向上抛出。"""
        engine = MagicMock()
        engine.transcribe.side_effect = RuntimeError("Whisper crashed")
        with pytest.raises(RuntimeError, match="Whisper crashed"):
            transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)


class TestBoundaryCases:
    """边界情况测试。"""

    def test_empty_audio_file(self, tmp_output_dir):
        """空音频文件应由引擎处理（可能返回空结果或报错）。"""
        empty = tmp_output_dir.parent / "empty.mp3"
        empty.write_bytes(b"")
        engine = MagicMock()
        engine.transcribe.return_value = TranscriptionResult(
            language="en",
            language_probability=0.5,
            duration=0.0,
            segments=[],
        )
        result = transcribe_one(engine, empty, tmp_output_dir, translator_obj=None)
        assert result is not None
        assert result["paragraphs"] == 0

    def test_special_chars_in_filename(self, tmp_output_dir):
        """特殊字符文件名应正常处理。"""
        special = tmp_output_dir.parent / "会议 (2024) [Q3].mp3"
        special.write_bytes(b"\x00" * 1024)
        engine = MagicMock()
        engine.transcribe.return_value = TranscriptionResult(
            language="zh",
            language_probability=0.99,
            duration=10.0,
            segments=[Segment(0.0, 10.0, "测试内容")],
        )
        result = transcribe_one(engine, special, tmp_output_dir, translator_obj=None)
        assert result is not None
        orig = tmp_output_dir / "会议 (2024) [Q3]_原文.txt"
        assert orig.exists()

    def test_long_duration_audio(self, tmp_output_dir):
        """超长音频（>2小时）应正常处理。"""
        long_file = tmp_output_dir.parent / "long.mp3"
        long_file.write_bytes(b"\x00" * 1024)
        engine = MagicMock()
        engine.transcribe.return_value = TranscriptionResult(
            language="en",
            language_probability=0.95,
            duration=7200.0,  # 2 hours
            segments=[Segment(0.0, 7200.0, "Very long meeting content.")],
        )
        result = transcribe_one(engine, long_file, tmp_output_dir, translator_obj=None)
        assert result is not None
        assert result["duration"] == 7200.0
