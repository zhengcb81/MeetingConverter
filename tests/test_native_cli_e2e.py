"""Exercise the installed audio probe, real CLI, and a loopback provider."""

from __future__ import annotations

import json
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from subprocess_support import fixture_environment, run_child
from test_s2_mimo_diagnostics import _cold_reconcile, _one_check, _operation_rows

REPO = Path(__file__).resolve().parents[1]
SYNTHETIC_KEY = "offline-meeting-fixture-key"
TRANSCRIPT = "Revenue rose during the quarter."


@pytest.fixture
def provider(request):
    truncated = getattr(request, "param", False)
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            calls.append((self.path, self.headers["api-key"], json.loads(body)))
            response = json.dumps({"choices": [{"message": {"content": TRANSCRIPT}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response[:9] if truncated else response)
            self.close_connection = True

        def log_message(self, _format, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/asr", calls
        finally:
            server.shutdown()
            worker.join(timeout=3)
            assert not worker.is_alive()


def _wav(path):
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 8000)


def _command(tmp_path, script, *args):
    env = fixture_environment()
    env.update(
        RESEARCH_FEEDBACK_OUT=str(tmp_path / "feedback.jsonl"),
        RESEARCH_FEEDBACK_STATE_ROOT=str(tmp_path / "state"),
    )
    return run_child(
        [sys.executable, "-B", str(REPO / script), *map(str, args)],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )


def _transcribe(tmp_path, endpoint, *, audio_valid=True, config_kind="valid"):
    audio = tmp_path / "audio.wav"
    if audio_valid:
        _wav(audio)
    else:
        audio.write_bytes(b"this is not a WAV container")
    config = tmp_path / "selected.json"
    if config_kind == "valid":
        config.write_text(json.dumps({
            "transcription_engine": "whisper", "language": "zh",
            "mimo_base_url": endpoint, "mimo_api_key": SYNTHETIC_KEY,
        }), encoding="utf-8")
    elif config_kind == "malformed":
        config.write_text("{", encoding="utf-8")
    return _command(
        tmp_path, "transcribe.py", audio, "--config", config,
        "--output", tmp_path / "out", "--engine", "mimo", "--language", "en", "--no-translate",
    )


@pytest.mark.e2e_offline
def test_transcribe_cli_applies_overrides_to_an_explicit_config(tmp_path, provider):
    endpoint, calls = provider
    result = _transcribe(tmp_path, endpoint)
    assert result.returncode == 0, (result.stdout, result.stderr)
    (path, key, payload), = calls
    assert path == "/asr" and key == SYNTHETIC_KEY
    assert payload["asr_options"] == {"language": "en"}
    assert payload["messages"][0]["content"][0]["input_audio"]["data"].startswith("data:audio/wav;base64,")
    original = (tmp_path / "out" / "audio_原文.txt").read_text(encoding="utf-8")
    assert TRANSCRIPT in original
    assert not (tmp_path / "out" / "audio_翻译.txt").exists()


@pytest.mark.e2e_offline
@pytest.mark.parametrize("config_kind", ["malformed", "missing"])
def test_bad_explicit_config_stops_before_provider(tmp_path, provider, config_kind):
    endpoint, calls = provider
    result = _transcribe(tmp_path, endpoint, config_kind=config_kind)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "config.json" in result.stdout + result.stderr
    assert not calls
    assert not (tmp_path / "out").exists()


@pytest.mark.e2e_offline
def test_bad_audio_is_reported_by_native_ffprobe_before_any_post(tmp_path, provider):
    endpoint, calls = provider
    result = _transcribe(tmp_path, endpoint, audio_valid=False)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert not calls
    details = (tmp_path / "feedback.jsonl.details.jsonl").read_text(encoding="utf-8")
    assert "AudioProcessError" in details
    assert not tuple((tmp_path / "out").glob("*.txt"))


@pytest.mark.e2e_offline
@pytest.mark.parametrize("provider", [True], indirect=True)
def test_real_http_truncation_is_durable_and_does_not_repeat_post(tmp_path, provider):
    endpoint, calls = provider
    result = _transcribe(tmp_path, endpoint)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert len(calls) == 1
    sidecar = tmp_path / "feedback.jsonl"
    details = sidecar.with_suffix(".jsonl.details.jsonl").read_text(encoding="utf-8")
    assert "IncompleteRead" in details
    assert SYNTHETIC_KEY not in result.stdout + result.stderr + details
    assert not tuple((tmp_path / "out").glob("*.txt"))
    original = _one_check(_operation_rows(tmp_path), "action-started")
    first, second = (_cold_reconcile(tmp_path, original) for _ in range(2))
    assert first == second
    assert first["result"]["cost_state"] == "unknown"
    assert len(calls) == 1
