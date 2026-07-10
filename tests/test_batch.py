"""tests/test_batch.py - core.batch 单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.batch import get_audio_files, run_batch
from engines.base import Segment, TranscriptionResult


class TestGetAudioFiles:
    def test_single_mp3(self, tmp_path):
        f = tmp_path / "audio.mp3"
        f.write_bytes(b"\x00")
        result = get_audio_files(str(f))
        assert len(result) == 1
        assert result[0] == f

    def test_non_audio_extension_ignored(self, tmp_path):
        f = tmp_path / "readme.txt"
        f.write_text("hello")
        result = get_audio_files(str(f))
        assert len(result) == 0

    def test_directory_with_multiple_formats(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"\x00")
        (tmp_path / "b.wav").write_bytes(b"\x00")
        (tmp_path / "c.m4a").write_bytes(b"\x00")
        (tmp_path / "d.txt").write_text("ignore")
        result = get_audio_files(str(tmp_path))
        assert len(result) == 3
        extensions = {f.suffix for f in result}
        assert extensions == {".mp3", ".wav", ".m4a"}

    def test_nonexistent_path_returns_empty(self):
        result = get_audio_files("/nonexistent/path")
        assert result == []

    def test_sorted_output(self, tmp_path):
        (tmp_path / "b.mp3").write_bytes(b"\x00")
        (tmp_path / "a.mp3").write_bytes(b"\x00")
        result = get_audio_files(str(tmp_path))
        assert result[0].name == "a.mp3"
        assert result[1].name == "b.mp3"


class TestRunBatch:
    @pytest.fixture
    def audio_files(self, tmp_path):
        f1 = tmp_path / "meeting1.mp3"
        f1.write_bytes(b"\x00" * 1024)
        f2 = tmp_path / "meeting2.mp3"
        f2.write_bytes(b"\x00" * 1024)
        return [f1, f2]

    @pytest.fixture
    def mock_engine(self):
        engine = MagicMock()
        engine.transcribe.return_value = TranscriptionResult(
            language="en",
            language_probability=0.95,
            duration=30.0,
            segments=[Segment(0.0, 30.0, "Test content.")],
        )
        return engine

    def test_processes_all_files(self, mock_engine, audio_files, tmp_output_dir):
        stats = run_batch(
            mock_engine,
            audio_files,
            tmp_output_dir,
            translator_obj=None,
        )
        assert stats["processed"] == 2
        assert stats["skipped"] == 0
        assert stats["failures"] == 0

    def test_skip_existing(self, mock_engine, audio_files, tmp_output_dir):
        # Pre-create output for first file
        (tmp_output_dir / "meeting1_原文.txt").write_text("done")
        stats = run_batch(
            mock_engine,
            audio_files,
            tmp_output_dir,
            translator_obj=None,
            force=False,
        )
        assert stats["processed"] == 1
        assert stats["skipped"] == 1

    def test_failure_counts(self, audio_files, tmp_output_dir):
        engine = MagicMock()
        engine.transcribe.side_effect = RuntimeError("API error")
        stats = run_batch(
            engine,
            audio_files,
            tmp_output_dir,
            translator_obj=None,
        )
        assert stats["processed"] == 0
        assert stats["failures"] == 2

    def test_empty_file_list(self, tmp_output_dir):
        engine = MagicMock()
        stats = run_batch(engine, [], tmp_output_dir)
        assert stats["processed"] == 0

    def test_partial_failure(self, audio_files, tmp_output_dir):
        """一个文件成功，一个失败。"""
        call_count = 0
        original_side_effect = None

        def selective_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Second file fails")
            return TranscriptionResult(
                language="en",
                language_probability=0.95,
                duration=30.0,
                segments=[Segment(0.0, 30.0, "OK")],
            )

        engine = MagicMock()
        engine.transcribe.side_effect = selective_fail
        stats = run_batch(
            engine,
            audio_files,
            tmp_output_dir,
            translator_obj=None,
        )
        assert stats["processed"] == 1
        assert stats["failures"] == 1
