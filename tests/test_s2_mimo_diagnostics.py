"""S2-MC-MIMO-DIAGNOSTICS: MiMo 错误边界的脱敏诊断与冷读。

卡面要求三件事：

1. 用真实 ``MiMoEngine`` / 普通转录入口 + 确定性 transport 替身复现
   “首错后成功”和“重试耗尽”，合成凭据只出现在输入；
2. MiMo 返回或抛出时投影尝试序号、异常类型、HTTP 状态和本仓源码位置，
   业务层继续拿到 ``EngineError``（原类型）及可用归因；
3. 原进程退出后由独立进程按 owner 公开端口冷读 F4 观察，且不重新转录、
   不改变费用事实。

本文件只使用临时目录、合成 WAV 与合成凭据；transport 替身是唯一的
``urlopen``，不会访问真实网络。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import subprocess
import sys
import traceback
import urllib.error
from pathlib import Path

import pytest
from f4_child_runner import MIMO_SYNTHETIC_KEY, MIMO_VENDOR_BODY

from engines.mimo import MiMoEngine
from exceptions import EngineError

REPO = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve().parent / "f4_child_runner.py"

#: 合成凭据：只作为输入，不得出现在日志、失败消息或 F4 观察里。
SYNTHETIC_KEY = MIMO_SYNTHETIC_KEY
#: 模拟供应商正文（含同一合成凭据）：不得离开 transport 边界。
VENDOR_BODY = MIMO_VENDOR_BODY
VENDOR_MARKER = "S2-MIMO-VENDOR-BODY"
#: 合成音频的 base64 形态：不得出现在日志或观察里。
AUDIO_MARKER = base64.b64encode(b"stub audio for mimo transport").decode("ascii")

_ALLOWED_ENV = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME",
    "USERPROFILE", "SYSTEMDRIVE", "COMSPEC", "APPDATA", "LOCALAPPDATA",
}
_FEEDBACK_VARS = (
    "RESEARCH_FEEDBACK_OUT",
    "RESEARCH_FEEDBACK_DIR",
    "RESEARCH_FEEDBACK_RUN_ID",
    "RESEARCH_FEEDBACK_ATTEMPT_ID",
    "RESEARCH_FEEDBACK_STATE_ROOT",
)
IDENTITY_FIELDS = (
    "owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id",
)


# ── 单元边界：真实引擎 + 确定性 transport ───────────────────────


class _Response:
    def __init__(self, content: str):
        self._payload = json.dumps(
            {"choices": [{"message": {"content": content}}]}
        ).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


def _http_error(status: int = 503) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://mimo.invalid/v1/chat/completions",
        status,
        VENDOR_BODY,
        None,
        None,
    )


def _assert_no_secret(text: str) -> None:
    assert SYNTHETIC_KEY not in text
    assert VENDOR_BODY not in text
    assert VENDOR_MARKER not in text
    assert AUDIO_MARKER not in text


class TestMiMoBoundaryDiagnostics:
    def test_retry_warning_projects_sanitized_fields_without_traceback(
        self, mocker, caplog
    ):
        engine = MiMoEngine(
            api_key=SYNTHETIC_KEY,
            base_url="https://mimo.invalid/v1/chat/completions",
        )
        mocker.patch(
            "engines.mimo.urllib.request.urlopen",
            side_effect=[_http_error(503), _Response("ok after retry")],
        )
        mocker.patch("time.sleep")

        with caplog.at_level(logging.DEBUG, logger="engines.mimo"):
            result = engine._call_api("data:audio/wav;base64,AAAA", "zh")

        assert result == "ok after retry"
        retries = [
            record
            for record in caplog.records
            if "MiMo API 重试" in record.getMessage()
        ]
        assert len(retries) == 1
        message = retries[0].getMessage()
        assert "attempt=1/3" in message
        assert "error_type=HTTPError" in message
        assert "http_status=503" in message
        assert "location=engines/mimo.py" in message
        assert retries[0].exc_info is None, "重试日志不再物化原始 traceback"
        _assert_no_secret(caplog.text)

    def test_exhaustion_raises_original_type_with_sanitized_attribution(
        self, mocker, caplog
    ):
        engine = MiMoEngine(
            api_key=SYNTHETIC_KEY,
            base_url="https://mimo.invalid/v1/chat/completions",
        )
        mocker.patch(
            "engines.mimo.urllib.request.urlopen",
            side_effect=[_http_error(500), _http_error(500), _http_error(500)],
        )
        mocker.patch("time.sleep")

        with caplog.at_level(logging.DEBUG, logger="engines.mimo"):
            with pytest.raises(EngineError) as caught:
                engine._call_api("data:audio/wav;base64,AAAA", "zh")

        error = caught.value
        message = str(error)
        assert "attempts=3" in message
        assert "error_type=HTTPError" in message
        assert "http_status=500" in message
        assert "location=engines/mimo.py" in message
        _assert_no_secret(message)

        # 业务层继续拿到原类型（EngineError）和结构化归因。
        assert isinstance(error, EngineError)
        assert error.attempts == 3
        assert error.error_type == "HTTPError"
        assert error.http_status == 500
        assert error.location.startswith("engines/mimo.py")
        assert error.cause_types == ["HTTPError"]

        # 原始供应商正文不得通过因果链或 traceback 泄露。
        assert error.__cause__ is None
        assert error.__suppress_context__ is True
        assert error.__context__ is None
        formatted = "".join(traceback.format_exception(error))
        _assert_no_secret(formatted)
        _assert_no_secret(caplog.text)

    def test_non_http_failure_projects_no_status(self, mocker):
        engine = MiMoEngine(
            api_key=SYNTHETIC_KEY,
            base_url="https://mimo.invalid/v1/chat/completions",
        )
        mocker.patch(
            "engines.mimo.urllib.request.urlopen",
            side_effect=[
                urllib.error.URLError(TimeoutError(VENDOR_BODY)),
                urllib.error.URLError(TimeoutError(VENDOR_BODY)),
                urllib.error.URLError(TimeoutError(VENDOR_BODY)),
            ],
        )
        mocker.patch("time.sleep")

        with pytest.raises(EngineError) as caught:
            engine._call_api("data:audio/wav;base64,AAAA", "zh")

        error = caught.value
        assert error.error_type == "URLError"
        assert error.http_status is None
        assert error.cause_types == ["URLError", "TimeoutError"]
        assert "http_status=" not in str(error)
        _assert_no_secret(str(error))
        _assert_no_secret("".join(traceback.format_exception(error)))

    def test_non_http_error_with_code_attribute_is_not_an_http_status(self, mocker):
        class ProviderError(Exception):
            code = 200
            cause_types = ["Spoofed"]

        engine = MiMoEngine(
            api_key=SYNTHETIC_KEY,
            base_url="https://mimo.invalid/v1/chat/completions",
        )
        mocker.patch(
            "engines.mimo.urllib.request.urlopen",
            side_effect=[ProviderError(VENDOR_BODY)] * 3,
        )
        mocker.patch("time.sleep")

        with pytest.raises(EngineError) as caught:
            engine._call_api("data:audio/wav;base64,AAAA", "zh")

        error = caught.value
        assert error.error_type == "ProviderError"
        assert error.http_status is None
        assert error.cause_types == ["ProviderError"], "原始异常的伪属性不参与归因"
        _assert_no_secret(str(error))

    def test_projection_only_trusts_engine_error_cause_types(self):
        from core.feedback import _exception_cause_chain
        from engines.fallback import _cause_types as fallback_cause_types

        class Spoof(Exception):
            cause_types = ["Fake"]

        assert _exception_cause_chain(Spoof()) == []
        assert fallback_cause_types(Spoof()) == []

        error = EngineError("sanitized")
        error.cause_types = ["HTTPError"]
        assert _exception_cause_chain(error) == ["HTTPError"]
        assert fallback_cause_types(error) == ["HTTPError"]

        error.cause_types = ["HTTPError", ""]
        assert _exception_cause_chain(error) == []
        assert fallback_cause_types(error) == []

        error.cause_types = []
        error.__cause__ = ValueError("real cause")
        assert _exception_cause_chain(error) == ["ValueError"], \
            "空列表不得短路真实因果链"
        assert fallback_cause_types(error) == ["ValueError"]


# ── 真实入口：子进程 + 真实 MiMoEngine + transport 替身 ─────────


def _child_env(root: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k.upper() in _ALLOWED_ENV}
    env["PYTHONUTF8"] = "1"
    for name in _FEEDBACK_VARS:
        env.pop(name, None)
    env["RESEARCH_FEEDBACK_OUT"] = str(root / "feedback.jsonl")
    env["RESEARCH_FEEDBACK_RUN_ID"] = "s2-mimo-run"
    env["RESEARCH_FEEDBACK_ATTEMPT_ID"] = "s2-mimo-attempt"
    return env


def _run_child(root: Path, scenario: str, *, timeout: float = 90) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-B", "-X", "utf8", str(RUNNER),
        "--child", str(REPO), str(root), scenario,
    ]
    with subprocess.Popen(
        command, cwd=str(root), env=_child_env(root),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ) as child:
        stdout, stderr = child.communicate(timeout=timeout)
    return {
        "exit": child.returncode,
        "stdout": stdout.decode("utf-8", "replace"),
        "stderr": stderr.decode("utf-8", "replace"),
    }


def _read_jsonl(path: Path) -> list:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _operation_rows(root: Path) -> list:
    rows = _read_jsonl(root / "feedback.jsonl")
    return [row for row in rows if str(row.get("step_id", "")).startswith("meeting-operation/")]


def _one_check(rows: list, check_id: str) -> dict:
    matches = [row for row in rows if row.get("check_id") == check_id]
    assert len(matches) == 1, f"期望恰好一行 {check_id}，实际 {len(matches)}: {matches}"
    return matches[0]


def _details_rows(root: Path) -> list:
    return _read_jsonl(root / "feedback.jsonl.details.jsonl")


def _finished_details(root: Path) -> dict:
    records = [row for row in _details_rows(root) if row.get("phase") == "finished"]
    assert records, "必须有一条 finished 步骤日志"
    return records[-1]


def _transport_calls(root: Path) -> list:
    return _read_jsonl(root / "mimo-calls.jsonl")


def _digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _reconcile_request(row: dict) -> dict:
    row = dict(row, origin_owner=row.get("origin_owner") or row["owner"])
    occurrence = _digest([row[field] for field in IDENTITY_FIELDS])
    body = {"occurrence_id": occurrence, "observation": row}
    key = _digest(["reconcile", "meeting-converter", occurrence])
    return {
        "schema_version": "feedback-action/1",
        "kind": "reconcile",
        "owner": "meeting-converter",
        "action_id": key,
        "method": "lookup",
        "payload": body,
        "request_digest": _digest(["meeting-converter", "reconcile", key, body]),
    }


def _cold_reconcile(root: Path, row: dict) -> dict:
    """独立进程按 owner 公开端口冷读同一次发生（不调用转录）。"""
    request = _reconcile_request(row)
    env = {k: v for k, v in os.environ.items() if k.upper() in _ALLOWED_ENV}
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [
            sys.executable, "-B", str(REPO / "feedback_owner.py"),
            "--db", str(root / "owner.sqlite"),
            "--sidecar", str(root / "feedback.jsonl"),
            "reconcile",
        ],
        input=json.dumps(request).encode("utf-8"),
        cwd=str(root), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return json.loads(proc.stdout.decode("utf-8"))


class TestRealEntryDiagnostics:
    def test_retry_then_success_keeps_artifact_and_sanitized_observation(self, tmp_path):
        root = tmp_path / "retry-success"
        root.mkdir()
        (root / "audio.wav").write_bytes(b"stub audio for mimo transport")

        result = _run_child(root, "mimo-retry-success")

        assert result["exit"] == 0
        original = root / "out" / "audio_原文.txt"
        assert original.is_file(), "首错后成功必须真实产出原文"
        assert "Revenue grew" in original.read_text(encoding="utf-8")
        _assert_no_secret(result["stdout"])
        _assert_no_secret(result["stderr"])

        calls = _transport_calls(root)
        assert [call["attempt"] for call in calls] == [1, 2]
        assert calls[0]["error_type"] == "HTTPError"
        assert calls[0]["http_status"] == 503
        assert calls[1].get("ok") is True
        assert all(call["audio_b64_present"] is True for call in calls), \
            "真实引擎把合成音频编码进了 outbound payload"

        rows = _operation_rows(root)
        assert _one_check(rows, "transcription-started")["actual"] == "engine_started"
        assert _one_check(rows, "requested-outputs")["actual"] == "original_current"
        assert _one_check(rows, "publication-outcome")["actual"] == "published_current"
        details = _finished_details(root)
        assert details["errors"] == []
        assert details["engine"]["fallback_engaged"] is False
        _assert_no_secret((root / "feedback.jsonl").read_text(encoding="utf-8"))
        _assert_no_secret((root / "feedback.jsonl.details.jsonl").read_text(encoding="utf-8"))

        # 成功路径也按 owner 公开端口冷读：终态成功、费用未知、调用数不变。
        before_calls = (root / "mimo-calls.jsonl").read_text(encoding="utf-8")
        reply = _cold_reconcile(root, _one_check(rows, "requested-outputs"))
        assert reply["state"] == "done"
        assert reply["result"]["job_status"] == "succeeded"
        assert reply["result"]["cost_state"] == "unknown"
        assert (root / "mimo-calls.jsonl").read_text(encoding="utf-8") == before_calls
        assert not (root / "owner.sqlite").exists()

    def test_exhaustion_fails_without_leaking_vendor_text(self, tmp_path):
        root = tmp_path / "retry-exhausted"
        root.mkdir()
        (root / "audio.wav").write_bytes(b"stub audio for mimo transport")

        result = _run_child(root, "mimo-retry-exhausted")

        assert result["exit"] == 1
        assert not (root / "out" / "audio_原文.txt").exists()
        _assert_no_secret(result["stdout"])
        _assert_no_secret(result["stderr"])
        assert "attempts=3" in result["stdout"]
        assert "error_type=HTTPError" in result["stdout"]
        assert "http_status=500" in result["stdout"]
        assert "location=engines/mimo.py" in result["stdout"]

        calls = _transport_calls(root)
        assert [call["attempt"] for call in calls] == [1, 2, 3]
        assert all(call["audio_b64_present"] is True for call in calls)

        rows = _operation_rows(root)
        assert _one_check(rows, "transcription-started")["actual"] == "engine_started"
        assert _one_check(rows, "requested-outputs")["actual"] == "transcription_failed"
        outcome = _one_check(rows, "publication-outcome")
        assert outcome["actual"] == "transcription_failed"
        assert outcome["disposition"] == "deviation"
        assert _one_check(rows, "cost-receipt")["actual"] == "cost_unknown"

        details = _finished_details(root)
        assert [entry["error_type"] for entry in details["errors"]] == ["EngineError"]
        assert details["errors"][0]["cause_types"] == ["HTTPError"]
        assert details["errors"][0]["location"] == "core/pipeline.py#transcribe_one"
        assert details["engine"]["fallback_engaged"] is False
        _assert_no_secret((root / "feedback.jsonl").read_text(encoding="utf-8"))
        _assert_no_secret((root / "feedback.jsonl.details.jsonl").read_text(encoding="utf-8"))

    def test_fallback_log_after_exhaustion_is_sanitized(self, tmp_path):
        root = tmp_path / "fallback-success"
        root.mkdir()
        (root / "audio.wav").write_bytes(b"stub audio for mimo transport")

        result = _run_child(root, "mimo-fallback-success")

        assert result["exit"] == 0
        original = root / "out" / "audio_原文.txt"
        assert original.is_file()
        assert "Revenue grew" in original.read_text(encoding="utf-8")
        _assert_no_secret(result["stdout"])
        _assert_no_secret(result["stderr"])

        assert len(_transport_calls(root)) == 3, "主引擎三次尝试后耗尽"
        assert all(
            call["audio_b64_present"] is True for call in _transport_calls(root)
        )
        assert len((root / "engine-calls").read_text(encoding="utf-8").splitlines()) == 1

        rows = _operation_rows(root)
        fallback = _one_check(rows, "engine-fallback")
        assert fallback["actual"] == "fallback_engaged"
        assert _one_check(rows, "publication-outcome")["actual"] == "published_degraded"
        details = _finished_details(root)
        assert details["engine"]["fallback_engaged"] is True
        assert details["engine"]["primary_error"]["error_type"] == "EngineError"
        assert details["engine"]["primary_error"]["cause_types"] == ["HTTPError"]
        _assert_no_secret((root / "feedback.jsonl").read_text(encoding="utf-8"))
        _assert_no_secret((root / "feedback.jsonl.details.jsonl").read_text(encoding="utf-8"))

    def test_missing_input_keeps_the_original_cli_contract(self, tmp_path):
        root = tmp_path / "missing-input"
        root.mkdir()

        result = _run_child(root, "no-input")

        assert result["exit"] == 1
        assert "错误: 未找到音频文件" in result["stdout"]
        assert "Traceback" not in result["stdout"]
        assert "Traceback" not in result["stderr"]
        rows = _read_jsonl(root / "feedback.jsonl")
        outcome = _one_check(rows, "startup-outcome")
        assert outcome["actual"] == "request_rejected"

    def test_cold_read_reconciles_without_retranscribing(self, tmp_path):
        root = tmp_path / "cold-read"
        root.mkdir()
        (root / "audio.wav").write_bytes(b"stub audio for mimo transport")
        result = _run_child(root, "mimo-retry-exhausted")
        assert result["exit"] == 1

        rows = _operation_rows(root)
        observed = _one_check(rows, "requested-outputs")
        before_calls = (root / "mimo-calls.jsonl").read_text(encoding="utf-8")
        before_observations = (root / "feedback.jsonl").read_bytes()

        reply = _cold_reconcile(root, observed)

        assert reply["state"] == "done"
        assert reply["result"]["job_status"] == "failed"
        assert reply["result"]["cost_state"] == "unknown"
        assert reply["result"]["step_id"] == observed["step_id"]
        assert (root / "mimo-calls.jsonl").read_text(encoding="utf-8") == before_calls, \
            "冷读不得再次调用供应商"
        assert (root / "feedback.jsonl").read_bytes() == before_observations, \
            "冷读不得改写原观察"
        assert not (root / "owner.sqlite").exists(), "只读对账不建收据库"
