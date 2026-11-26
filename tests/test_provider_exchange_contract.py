import hashlib
from io import BytesIO
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

import pytest

from core.feedback import FEEDBACK_STATE_ROOT_ENV
from core.local_diagnostics import cli_diagnostics
from engines.mimo import MiMoEngine
from exceptions import TranslationError
from translator import Translator


class _Response(BytesIO):
    status = 200


@pytest.mark.parametrize("provider", ["mimo", "translate"])
def test_http_rejection_uses_the_same_attempt_and_closes_before_backoff(tmp_path, monkeypatch, provider):
    monkeypatch.setenv(FEEDBACK_STATE_ROOT_ENV, str(tmp_path))
    monkeypatch.setenv("RESEARCH_FEEDBACK_RUN_ID", "synthetic-run")
    monkeypatch.setenv("RESEARCH_FEEDBACK_ATTEMPT_ID", "synthetic-attempt")
    error_body = BytesIO(b"synthetic-response-private")
    rejected = urllib.error.HTTPError("https://example.invalid", 503, "synthetic-note-private", {}, error_body)
    success = _Response(b'{"choices":[{"message":{"content":"fixture output"}}]}')
    calls = []
    sleeps = []

    def open_request(request, timeout):
        calls.append(request.method)
        if len(calls) == 1:
            raise rejected
        return success

    monkeypatch.setattr(urllib.request, "urlopen", open_request)
    monkeypatch.setattr(time, "sleep", lambda delay: sleeps.append((delay, error_body.closed)))
    with cli_diagnostics("synthetic-exchange"):
        if provider == "mimo":
            result = MiMoEngine(api_key="fixture-key")._call_api("data:audio/wav;base64,AAAA", "zh")
        else:
            result = Translator({"deepseek_api_key": "fixture-key"}).translate_paragraph("fixture input")
    assert result == "fixture output"
    assert calls == ["POST", "POST"]
    assert sleeps == [(2, True)]
    assert success.closed

    raw = (tmp_path / "logs" / "synthetic-exchange.jsonl").read_bytes()
    assert b"synthetic-response-private" not in raw and b"synthetic-note-private" not in raw
    rows = [json.loads(line) for line in raw.splitlines()]
    assert {(row["run_id"], row["attempt_id"], row["stage"]) for row in rows} == {
        ("synthetic-run", "synthetic-attempt", provider + "_request"),
    }
    assert [(row["phase"], row.get("request_attempt"), row.get("http_status")) for row in rows] == [
        ("dispatch_started", 1, None), ("response_headers", 1, 503), ("error", 1, 503),
        ("dispatch_started", 2, None), ("response_headers", 2, 200),
    ]
    assert rows[2]["response_received"] is True and rows[2]["error_type"] == "HTTPError"


def test_translation_does_not_retry_after_success_headers_when_body_is_unusable(tmp_path, monkeypatch):
    monkeypatch.setenv(FEEDBACK_STATE_ROOT_ENV, str(tmp_path))
    response = _Response(b"{")
    calls = []

    def open_request(request, timeout):
        calls.append(request.method)
        return response

    monkeypatch.setattr(urllib.request, "urlopen", open_request)
    monkeypatch.setattr(time, "sleep", lambda delay: pytest.fail("post-response retry"))
    with cli_diagnostics("synthetic-body"), pytest.raises(TranslationError):
        Translator({"deepseek_api_key": "fixture-key"}).translate_paragraph("fixture input")
    assert calls == ["POST"] and response.closed
    rows = (tmp_path / "logs" / "synthetic-body.jsonl").read_bytes().splitlines()
    fault = json.loads(rows[-1])
    assert (fault["phase"], fault["request_attempt"], fault["http_status"], fault["error_type"]) == (
        "error", 1, 200, "JSONDecodeError",
    )


def test_local_log_binds_source_fingerprint_separately_from_projection_version(tmp_path, monkeypatch):
    from core import local_diagnostics

    monkeypatch.setenv(FEEDBACK_STATE_ROOT_ENV, str(tmp_path))
    with cli_diagnostics("synthetic-source"):
        local_diagnostics.record_event("fixture", "started")
    event = json.loads((tmp_path / "logs" / "synthetic-source.jsonl").read_bytes())
    fingerprint = event.get("implementation_sha256")
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    assert event["projection_version"] == local_diagnostics.ADAPTER_VERSION
    sources = local_diagnostics._IMPLEMENTATION_FILES
    repo = Path(local_diagnostics.__file__).resolve().parents[1]
    payload = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in sources}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    assert hashlib.sha256(canonical).hexdigest() == fingerprint
