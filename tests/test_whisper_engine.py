"""WhisperEngine 单元测试。"""

from __future__ import annotations

from engines.base import Segment, TranscriptionResult
from engines.whisper import WhisperEngine


class TestWhisperEngineTranscribe:
    def test_returns_transcription_result(self, mock_whisper_model):
        engine = WhisperEngine(mock_whisper_model)
        result = engine.transcribe("fake.mp3")
        assert isinstance(result, TranscriptionResult)

    def test_segments_converted_correctly(self, mock_whisper_model):
        engine = WhisperEngine(mock_whisper_model)
        result = engine.transcribe("fake.mp3")
        assert len(result.segments) == 3
        assert isinstance(result.segments[0], Segment)
        assert result.segments[0].start == 0.0
        assert result.segments[0].end == 2.5
        assert result.segments[0].text == "Our revenue in the third quarter"

    def test_whitespace_only_segments_filtered(self, mock_whisper_model):
        engine = WhisperEngine(mock_whisper_model)
        result = engine.transcribe("fake.mp3")
        assert all(s.text.strip() for s in result.segments)
        assert len(result.segments) == 3

    def test_language_and_probability_propagated(self, mock_whisper_model):
        engine = WhisperEngine(mock_whisper_model)
        result = engine.transcribe("fake.mp3")
        assert result.language == "en"
        assert result.language_probability == 0.98

    def test_duration_propagated(self, mock_whisper_model):
        engine = WhisperEngine(mock_whisper_model)
        result = engine.transcribe("fake.mp3")
        assert result.duration == 8.0

    def test_language_passed_to_model(self, mock_whisper_model):
        engine = WhisperEngine(mock_whisper_model)
        engine.transcribe("fake.mp3", language="zh")
        _, kwargs = mock_whisper_model.transcribe.call_args
        assert kwargs["language"] == "zh"

    def test_initial_prompt_passed_to_model(self, mock_whisper_model):
        engine = WhisperEngine(mock_whisper_model)
        engine.transcribe("fake.mp3", initial_prompt="financial terms: revenue")
        _, kwargs = mock_whisper_model.transcribe.call_args
        assert kwargs["initial_prompt"] == "financial terms: revenue"

    def test_no_language_omits_kwarg(self, mock_whisper_model):
        engine = WhisperEngine(mock_whisper_model)
        engine.transcribe("fake.mp3")
        _, kwargs = mock_whisper_model.transcribe.call_args
        assert "language" not in kwargs
        assert "initial_prompt" not in kwargs

    def test_default_transcribe_kwargs(self, mock_whisper_model):
        engine = WhisperEngine(mock_whisper_model)
        engine.transcribe("fake.mp3")
        _, kwargs = mock_whisper_model.transcribe.call_args
        assert kwargs["beam_size"] == 5
        assert kwargs["vad_filter"] is True
        assert kwargs["vad_parameters"] == {"min_silence_duration_ms": 500}

    def test_audio_path_coerced_to_str(self, mock_whisper_model, tmp_path):
        engine = WhisperEngine(mock_whisper_model)
        engine.transcribe(tmp_path / "fake.mp3")
        args, _ = mock_whisper_model.transcribe.call_args
        assert args[0] == str(tmp_path / "fake.mp3")

    def test_implements_engine_protocol(self, mock_whisper_model):
        from engines.base import TranscriptionEngine

        engine = WhisperEngine(mock_whisper_model)
        assert isinstance(engine, TranscriptionEngine)
