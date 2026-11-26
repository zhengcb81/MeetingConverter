"""S1-01 regression tests: MiMo retry logging and feedback BaseException handling."""

from __future__ import annotations

import json
import logging
import urllib.error
from unittest.mock import MagicMock

import pytest

from core.feedback import FeedbackRecorder, OperationFeedback
from engines.mimo import MiMoEngine


def test_mimo_call_api_retries_and_logs_warning_instead_of_name_error(mocker, caplog):
    eng = MiMoEngine(api_key="test-key", base_url="https://api.example.com")
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"choices": [{"message": {"content": "ok after retry"}}]}
    ).encode("utf-8")
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_resp)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    mocker.patch(
        "engines.mimo.urllib.request.urlopen",
        side_effect=[urllib.error.URLError("transient network blip"), mock_ctx],
    )
    mocker.patch("time.sleep")

    with caplog.at_level(logging.WARNING, logger="engines.mimo"):
        result = eng._call_api("data:audio/wav;base64,abc", "zh")

    assert result == "ok after retry"
    retries = [rec for rec in caplog.records if "MiMo API 重试" in rec.getMessage()]
    assert len(retries) == 1, "首错后成功只应有一条重试日志"
    assert "attempt=1/3" in retries[0].getMessage()
    assert retries[0].exc_info is None, "S2 起重试日志不再物化原始 traceback"


def test_feedback_flush_propagates_keyboard_interrupt_and_logs_io_error(tmp_path, caplog):
    recorder = FeedbackRecorder(tmp_path / "obs.jsonl", run_id="s1-run", attempt_id="1")
    op = OperationFeedback(
        recorder,
        input_id="s1-input",
        requested_mode="original_current",
        force=False,
    )
    op._pending.append({"step_id": "s1", "check_id": "c1", "expected": "a", "actual": "a"})

    def _boom_kb(**kwargs):
        raise KeyboardInterrupt("user cancel")

    recorder.record = _boom_kb  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        op.flush()

    op._pending.append({"step_id": "s2", "check_id": "c2", "expected": "a", "actual": "a"})

    def _boom_io(**kwargs):
        raise OSError("disk full")

    recorder.record = _boom_io  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="core.feedback"):
        op.flush()

    report, = [record for record in caplog.records if hasattr(record, "mc_feedback_failure")]
    assert report.mc_feedback_failure["error_type"] == "OSError"
    assert report.exc_info is None and "disk full" not in report.getMessage()
