"""audio_utils 单元测试。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

import audio_utils
from audio_utils import (
    detect_format,
    estimate_base64_size_mb,
    _parse_silence_starts,
    _choose_split_points,
    get_audio_duration,
    split_by_silence,
)
from exceptions import AudioProcessError, EngineError


class TestDetectFormat:
    def test_wav(self):
        assert detect_format("a.wav") == "wav"

    def test_mp3(self):
        assert detect_format("a.mp3") == "mp3"

    def test_uppercase(self):
        assert detect_format("A.WAV") == "wav"

    def test_unsupported_returns_none(self):
        assert detect_format("a.m4a") is None
        assert detect_format("a.flac") is None

    def test_no_extension(self):
        assert detect_format("noext") is None


class TestEstimateBase64Size:
    def test_known_size(self, tmp_path):
        f = tmp_path / "test.wav"
        f.write_bytes(b"\x00" * (3 * 1024 * 1024))
        size = estimate_base64_size_mb(f)
        assert size == pytest.approx(4.0, rel=0.01)


class TestParseSilenceStarts:
    def test_parses_timestamps(self):
        output = (
            "[silencedetect @ 0x1] silence_start: 10.5\n"
            "[silencedetect @ 0x1] silence_end: 11.2 | silence_duration: 0.7\n"
            "[silencedetect @ 0x1] silence_start: 30.0\n"
        )
        assert _parse_silence_starts(output) == [10.5, 30.0]

    def test_no_matches(self):
        assert _parse_silence_starts("nothing here") == []

    def test_multiple(self):
        output = "silence_start: 1.0\nsilence_start: 2.0\nsilence_start: 3.0"
        assert _parse_silence_starts(output) == [1.0, 2.0, 3.0]


class TestChooseSplitPoints:
    def test_short_audio_no_split(self):
        assert _choose_split_points([], 60.0, 120.0) == [(0.0, 60.0)]

    def test_splits_at_silence(self):
        result = _choose_split_points([50.0, 110.0], 150.0, 60.0)
        assert result[0] == (0.0, 50.0)
        assert result[-1][1] == 150.0
        for i in range(len(result) - 1):
            assert result[i][1] == result[i + 1][0]
        for start, end in result:
            assert end - start <= 60.0

    def test_no_silence_hard_splits(self):
        result = _choose_split_points([], 150.0, 60.0)
        assert len(result) == 3
        assert result == [(0.0, 60.0), (60.0, 120.0), (120.0, 150.0)]
        for start, end in result:
            assert end - start <= 60.0


class TestGetAudioDuration:
    def test_calls_ffprobe(self, mocker):
        mock_run = mocker.patch("audio_utils.subprocess.run")
        mock_run.return_value = CompletedProcess(["ffprobe"], 0, stdout=b"123.45\n")
        dur = get_audio_duration("fake.mp3")
        assert dur == 123.45
        assert mock_run.call_args[0][0][0] == "ffprobe"
        assert mock_run.call_args.kwargs["timeout"] > 0

    @pytest.mark.parametrize("entry", ["nonzero", "timeout"])
    def test_handles_failed_ffprobe_subprocess(self, monkeypatch, entry):
        run = subprocess.run
        script = (
            "print(123.45); raise SystemExit(4)" if entry == "nonzero"
            else "import time; time.sleep(10)"
        )

        def substitute_ffprobe(args, **kwargs):
            assert args[0] == "ffprobe"
            assert kwargs["stdin"] == subprocess.DEVNULL
            assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
            return run([sys.executable, "-B", "-c", script], **kwargs)

        monkeypatch.setattr(audio_utils.subprocess, "run", substitute_ffprobe)
        with pytest.raises(AudioProcessError, match="ffprobe") as found:
            if entry == "nonzero":
                get_audio_duration("input.wav")
            else:
                get_audio_duration("input.wav", timeout=0.3)
        assert found.value.stage == "duration_probe"
        assert found.value.returncode == (4 if entry == "nonzero" else None)
        if entry == "timeout":
            assert isinstance(found.value.__cause__, subprocess.TimeoutExpired)

    @pytest.mark.parametrize("output", [b"unknown", b"nan", b"-1"])
    def test_rejects_invalid_duration_from_successful_ffprobe(self, mocker, output):
        mocker.patch("audio_utils.subprocess.run", return_value=CompletedProcess(
            ["ffprobe"], 0, stdout=output
        ))
        with pytest.raises(AudioProcessError, match="ffprobe"):
            get_audio_duration("input.wav")


class TestSplitBySilence:
    def test_short_audio_no_split(self, mocker, tmp_path):
        f = tmp_path / "short.mp3"
        f.write_bytes(b"\x00" * 1024)
        mocker.patch("audio_utils.get_audio_duration", return_value=60.0)
        mocker.patch("audio_utils._estimate_max_chunk_duration", return_value=120.0)
        result = split_by_silence(f)
        assert len(result) == 1
        assert result[0] == (f, 0.0, 60.0)

    def test_long_audio_splits(self, mocker, tmp_path):
        f = tmp_path / "long.mp3"
        f.write_bytes(b"\x00" * (10 * 1024 * 1024))
        mocker.patch("audio_utils.get_audio_duration", return_value=300.0)
        mocker.patch("audio_utils._estimate_max_chunk_duration", return_value=100.0)
        mocker.patch("audio_utils.tempfile.tempdir", str(tmp_path))

        def run(args, **kwargs):
            if "silencedetect=noise=-30dB:d=0.5" in args:
                return CompletedProcess(
                    args, 0, stderr=b"silence_start: 100.0\nsilence_start: 200.0"
                )
            Path(args[-1]).write_bytes(b"synthetic chunk")
            return CompletedProcess(args, 0, stderr=b"")

        mocker.patch("audio_utils.subprocess.run", side_effect=run)
        result = split_by_silence(f)
        assert len(result) >= 2
        assert result[0][1] == 0.0
        assert result[-1][2] == 300.0

    @pytest.mark.parametrize("failed_stage", ["detection", "cut", "empty"])
    def test_failed_ffmpeg_discards_only_owned_files(self, mocker, tmp_path, failed_stage):
        source = tmp_path / "source.mp3"
        source.write_bytes(b"synthetic original")
        mocker.patch("audio_utils.tempfile.tempdir", str(tmp_path))
        mocker.patch("audio_utils.get_audio_duration", return_value=10.0)
        mocker.patch("audio_utils._estimate_max_chunk_duration", return_value=5.0)
        cut_calls = []

        def run(args, **kwargs):
            if "silencedetect=noise=-30dB:d=0.5" in args:
                return CompletedProcess(args, int(failed_stage == "detection"), stderr=b"")
            chunk = Path(args[-1])
            cut_calls.append(chunk)
            if len(cut_calls) == 1:
                chunk.write_bytes(b"synthetic first chunk")
                return CompletedProcess(args, 0, stderr=b"")
            return CompletedProcess(args, int(failed_stage == "cut"), stderr=b"")

        mocker.patch("audio_utils.subprocess.run", side_effect=run)
        with pytest.raises(EngineError, match="ffmpeg"):
            split_by_silence(source)
        assert source.read_bytes() == b"synthetic original"
        assert list(tmp_path.glob("mimo_chunk_*")) == []
        assert len(cut_calls) == (0 if failed_stage == "detection" else 2)
