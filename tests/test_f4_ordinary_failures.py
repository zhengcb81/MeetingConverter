"""tests/test_f4_ordinary_failures.py — F4 普通入口的启动、翻译意图与回退覆盖。

每个用例都在真实 Python 子进程里调用普通 CLI 入口（``transcribe.main()``），
配置、状态根、工作目录、输出全部映射到同一测试专用临时根；父进程清除继承的
``RESEARCH_FEEDBACK_*`` 再测默认路径，另用显式 OUT 的用例覆盖既有单次文件
契约。替身只放在引擎与外部传输边界；断言全部在子进程退出后由本测试进程
**冷读**旁路/交付文件得出。

覆盖两条原发生（run ``f4-coverage-audit-20261121``，attempt ``baseline-e7b6c021``）：

- 第 23 行 ``initialization / native-failure-not-forwarded``：无输入、坏 CLI、
  输出目录错误、主引擎初始化失败四案要能区分请求拒绝、初始化与本地 I/O
  失败，且确知未调用时显示未发送；
- 第 24 行 ``fallback / degraded-work-hidden``：翻译器未能创建、主引擎失败后
  备用成功都要如实显示降级，两种同外层不同内因的异常可冷读分辨。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve().parent / "f4_child_runner.py"

#: 子进程环境白名单：清掉继承的反馈变量与一切密钥。
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

OLD_ORIGINAL = "旧原文-上一轮产物\n"
OLD_TRANSLATION = "旧译文-上一轮产物\n"
OLD_BILINGUAL = "旧对照-上一轮产物\n"


# ── 子进程与冷读辅助 ─────────────────────────────────────────────


def _child_env(root: Path, mode: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k.upper() in _ALLOWED_ENV}
    env["PYTHONUTF8"] = "1"
    for name in _FEEDBACK_VARS:
        env.pop(name, None)
    if mode in ("out", "both"):
        env["RESEARCH_FEEDBACK_OUT"] = str(root / "single" / "out.jsonl")
    if mode in ("dir", "both"):
        env["RESEARCH_FEEDBACK_DIR"] = str(root / "inbox")
    if mode == "default":
        env["RESEARCH_FEEDBACK_STATE_ROOT"] = str(root / "state")
    return env


def delivery_root(root: Path, mode: str) -> Path:
    if mode in ("out", "both"):
        return root / "single"
    if mode in ("dir", "both"):
        return root / "inbox"
    return root / "state" / "observations"


def _read_jsonl(path: Path) -> list:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def read_deliveries(root: Path, mode: str) -> list:
    """冷读一个目录里的全部交付文件（jsonl + ready + details）。"""
    directory = delivery_root(root, mode)
    out = []
    for path in sorted(directory.glob("feedback-*.jsonl")):
        if path.name.endswith(".details.jsonl"):
            continue
        ready = path.with_name(path.stem + ".ready")
        details = path.with_name(path.name + ".details.jsonl")
        out.append({
            "path": path,
            "rows": _read_jsonl(path),
            "ready": json.loads(ready.read_text(encoding="utf-8")) if ready.is_file() else None,
            "details_text": details.read_text(encoding="utf-8") if details.is_file() else "",
            "details_rows": _read_jsonl(details),
        })
    return out


def read_single_out(root: Path) -> dict:
    path = root / "single" / "out.jsonl"
    return {
        "path": path,
        "rows": _read_jsonl(path),
        "details_rows": _read_jsonl(path.with_name(path.name + ".details.jsonl")),
        "details_text": path.with_name(path.name + ".details.jsonl").read_text(encoding="utf-8")
        if path.with_name(path.name + ".details.jsonl").is_file() else "",
    }


def by_check(rows: list, check_id: str) -> list:
    return [row for row in rows if row.get("check_id") == check_id]


def one_check(rows: list, check_id: str) -> dict:
    matches = by_check(rows, check_id)
    assert len(matches) == 1, f"期望恰好一行 {check_id}，实际 {len(matches)}: {matches}"
    return matches[0]


def operation_rows(rows: list) -> list:
    return [row for row in rows if str(row.get("step_id", "")).startswith("meeting-operation/")]


def finished_details(delivery: dict) -> dict:
    records = [row for row in delivery["details_rows"] if row.get("phase") == "finished"]
    assert records, "必须有一条 finished 步骤日志"
    return records[-1]


def startup_details(delivery: dict) -> list:
    return [row for row in delivery["details_rows"] if row.get("phase") == "startup"]


def prepare_source(root: Path) -> None:
    (root / "audio.wav").write_bytes(b"stub audio for local engine")


def prepare_output(root: Path, state: str) -> None:
    out = root / "out"
    if state == "file":
        out.write_bytes(b"not a directory")
    elif state == "original":
        out.mkdir()
        (out / "audio_原文.txt").write_text(OLD_ORIGINAL, encoding="utf-8")
    elif state == "old-outputs":
        out.mkdir()
        (out / "audio_原文.txt").write_text(OLD_ORIGINAL, encoding="utf-8")
        (out / "audio_翻译.txt").write_text(OLD_TRANSLATION, encoding="utf-8")
        (out / "audio_中英对照.txt").write_text(OLD_BILINGUAL, encoding="utf-8")
    elif state == "original-is-dir":
        out.mkdir()
        (out / "audio_原文.txt").mkdir()


def run_child(root: Path, scenario: str, *, mode: str = "default", timeout: float = 60):
    root.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-B", "-X", "utf8", str(RUNNER),
        "--child", str(REPO), str(root), scenario,
    ]
    with subprocess.Popen(
        command, cwd=str(root), env=_child_env(root, mode),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ) as child:
        stdout, stderr = child.communicate(timeout=timeout)
    return {"exit": child.returncode, "stdout": stdout, "stderr": stderr}


def start_child(root: Path, scenario: str, *, mode: str = "default"):
    command = [
        sys.executable, "-B", "-X", "utf8", str(RUNNER),
        "--child", str(REPO), str(root), scenario,
    ]
    return subprocess.Popen(
        command, cwd=str(root), env=_child_env(root, mode),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def wait_for(path: Path, timeout: float = 20.0) -> None:
    until = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > until:
            raise RuntimeError(f"子进程没有到达预期信号: {path.name}")
        time.sleep(0.02)


def _digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def test_native_failure_has_a_redacted_cold_local_log(f4_root):
    prepare_source(f4_root)
    result = run_child(f4_root, "provider-fail")
    assert result["exit"] == 1
    owner_row = one_check(read_deliveries(f4_root, "default")[0]["rows"], "run-started")
    log_path = f4_root / "state" / "logs" / "transcribe.jsonl"
    text = log_path.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines()]
    error, = [row for row in rows if row["stage"] == "batch"]
    assert error["run_id"] == owner_row["run_id"]
    assert error["attempt_id"] == owner_row["attempt_id"]
    assert error["error_type"] == "RuntimeError"
    assert error["cause_types"] == ["TimeoutError"]
    assert "fixture-timeout" not in text
    assert "fixture upstream failed" not in text
    assert b"fixture-timeout" not in result["stderr"]


def test_native_diagnostics_keep_the_exit_when_log_directory_is_blocked(f4_root):
    (f4_root / "audio.wav").unlink()
    (f4_root / "state").mkdir()
    (f4_root / "state" / "logs").write_bytes(b"test prevents local logging")
    result = run_child(f4_root, "no-input")
    assert result["exit"] == 1
    assert "错误: 未找到音频文件" in result["stdout"].decode("utf-8")
    assert b"diagnostic_log_unavailable" in result["stderr"]
    assert str(f4_root).encode("utf-8") not in result["stderr"]
    startup = startup_details(read_deliveries(f4_root, "default")[0])
    assert startup[0]["exit_code"] == 1


def test_native_diagnostic_log_rotates_without_changing_parser_exit(f4_root):
    log_path = f4_root / "state" / "logs" / "transcribe.jsonl"
    log_path.parent.mkdir(parents=True)
    previous = b"old protected log\n" * (1024 * 64)
    log_path.write_bytes(previous)
    result = run_child(f4_root, "invalid-cli")
    assert result["exit"] == 2
    assert b"unrecognized arguments" in result["stderr"]
    assert log_path.with_suffix(".jsonl.1").read_bytes() == previous
    rows = _read_jsonl(log_path)
    error, = [row for row in rows if row["phase"] == "error"]
    assert error["stage"] == "parsing"
    assert error["error_type"] == "SystemExit"
    command = [row for row in rows if row["stage"] == "command"]
    assert [row["phase"] for row in command] == ["started", "exited"]
    assert command[0]["step_id"] == command[1]["step_id"]


def test_unavailable_stderr_never_routes_local_logging_notice_to_stdout(tmp_path, monkeypatch, capsys):
    from core.local_diagnostics import cli_diagnostics

    state = tmp_path / "diagnostic-state"
    state.mkdir()
    (state / "logs").touch()
    monkeypatch.setenv("RESEARCH_FEEDBACK_STATE_ROOT", str(state))
    with monkeypatch.context() as isolated:
        isolated.setattr(sys, "stderr", None)
        with cli_diagnostics("transcribe"):
            pass
    assert capsys.readouterr().out == ""


def reconcile_request(row: dict):
    """构造 feedback-action/1 的 reconcile 信封（与探针同构）。"""
    row = dict(row, origin_owner=row.get("origin_owner") or row["owner"])
    occurrence = _digest([row[field] for field in IDENTITY_FIELDS])
    body = {"occurrence_id": occurrence, "observation": row}
    key = _digest(["reconcile", "meeting-converter", occurrence])
    request = {
        "schema_version": "feedback-action/1", "kind": "reconcile",
        "owner": "meeting-converter", "action_id": key, "method": "lookup",
        "payload": body,
        "request_digest": _digest(["meeting-converter", "reconcile", key, body]),
    }
    return request, occurrence


def call_owner(root: Path, db: Path, sidecar: Path, action: str, payload: dict = None, *, directories=()) -> dict:
    env = {k: v for k, v in os.environ.items() if k.upper() in _ALLOWED_ENV}
    env["PYTHONUTF8"] = "1"
    argv = [sys.executable, "-B", str(REPO / "feedback_owner.py"), "--db", str(db),
            "--sidecar", str(sidecar)]
    for directory in directories:
        argv.extend(("--sidecar-dir", str(directory)))
    argv.append(action)
    body = None
    if action.startswith("get-") and payload:
        argv.append(payload["action_id"])
    elif payload is not None:
        body = json.dumps(payload).encode()
    proc = subprocess.run(
        argv, input=body, cwd=str(root), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return json.loads(proc.stdout.decode("utf-8"))


def engine_calls(root: Path) -> int:
    signal = root / "engine-calls"
    if not signal.is_file():
        return 0
    return len(signal.read_text(encoding="utf-8").splitlines())


@pytest.fixture
def f4_root(tmp_path):
    root = tmp_path / "f4"
    root.mkdir()
    prepare_source(root)
    return root


# ── 原发生 1：启动失败四案（默认交付，冷读） ─────────────────────


class TestStartupFailures:
    """无输入、坏 CLI、输出目录错误、引擎初始化失败都要有观察。"""

    def test_missing_input_is_a_request_rejection(self, f4_root):
        (f4_root / "audio.wav").unlink()
        result = run_child(f4_root, "no-input")
        assert result["exit"] == 1
        assert "未找到音频文件" in result["stdout"].decode("utf-8", "replace")

        deliveries = read_deliveries(f4_root, "default")
        assert len(deliveries) == 1, "默认启动也要留下交付"
        rows = deliveries[0]["rows"]
        assert one_check(rows, "run-started")["actual"] == "started"
        outcome = one_check(rows, "startup-outcome")
        assert outcome["actual"] == "request_rejected"
        assert outcome["disposition"] == "deviation"
        detail = startup_details(deliveries[0])[-1]
        assert detail["stage"] == "input"
        assert detail["exit_code"] == 1
        assert detail["invocations"] == {
            "engine_started": False, "translation_attempted": False,
        }, "确知未调用时显示未发送"
        assert not operation_rows(rows), "没有输入就没有逐文件操作"

    def test_unknown_flag_rejects_the_request_with_native_exit_code(self, f4_root):
        result = run_child(f4_root, "invalid-cli", mode="default")
        assert result["exit"] == 2, "argparse 的原生退出码保留"
        deliveries = read_deliveries(f4_root, "default")
        assert deliveries, "解析失败也要留下启动收据"
        rows = deliveries[0]["rows"]
        outcome = one_check(rows, "startup-outcome")
        assert outcome["actual"] == "request_rejected"
        detail = startup_details(deliveries[0])[-1]
        assert detail["stage"] == "parsing"
        assert detail["exit_code"] == 2

    def test_existing_file_as_output_dir_is_a_local_io_failure(self, f4_root):
        prepare_output(f4_root, "file")
        result = run_child(f4_root, "output-dir")
        assert result["exit"] == 1
        deliveries = read_deliveries(f4_root, "default")
        assert deliveries
        rows = deliveries[0]["rows"]
        outcome = one_check(rows, "startup-outcome")
        assert outcome["actual"] == "local_io_failed"
        detail = startup_details(deliveries[0])[-1]
        assert detail["stage"] == "output_dir"
        # Windows/POSIX 的 mkdir 撞上已有文件时抛 OSError 的具体子类。
        assert detail["errors"][0]["error_type"] in {"OSError", "FileExistsError", "NotADirectoryError"}
        assert detail["invocations"]["engine_started"] is False

    def test_engine_init_failure_is_distinct_from_rejection(self, f4_root):
        result = run_child(f4_root, "engine-init")
        assert result["exit"] == 1
        deliveries = read_deliveries(f4_root, "default")
        assert deliveries
        rows = deliveries[0]["rows"]
        outcome = one_check(rows, "startup-outcome")
        assert outcome["actual"] == "initialization_failed"
        assert outcome["disposition"] == "deviation"
        detail = startup_details(deliveries[0])[-1]
        assert detail["stage"] == "engine_init"
        assert detail["errors"][0]["error_type"] == "ValueError"
        assert detail["invocations"]["engine_started"] is False
        assert not operation_rows(rows)

    def test_successful_startup_carries_the_request_intent(self, f4_root):
        result = run_child(f4_root, "explicit-off")
        assert result["exit"] == 0
        deliveries = read_deliveries(f4_root, "default")
        detail = startup_details(deliveries[0])[-1]
        assert detail["engine"] == "auto"
        assert detail["translate_requested"] is False
        assert detail["invocations"]["engine_started"] is True


# ── 原发生 2 之一：翻译器未能创建（RED #1） ───────────────────────


class TestTranslationIntent:
    """请求翻译而翻译器不可用、主动关翻译、回退成功三案可冷读区分。"""

    def test_translator_unavailable_keeps_original_and_tells_why(self, f4_root):
        """RED #1：默认入口、默认请求翻译、翻译器初始化失败。"""
        result = run_child(f4_root, "translator-init")
        assert result["exit"] == 0
        original = f4_root / "out" / "audio_原文.txt"
        assert original.is_file(), "原文真实产出"
        assert "Revenue grew" in original.read_text(encoding="utf-8")

        deliveries = read_deliveries(f4_root, "default")
        assert len(deliveries) == 1
        delivery = deliveries[0]
        rows = operation_rows(delivery["rows"])
        requested = one_check(rows, "requested-outputs")
        assert requested["expected"] == "original_translated_bilingual_current", \
            "翻译是被请求的，不能因为翻译器缺席就改口"
        assert requested["actual"] == "translation_unavailable"
        assert requested["disposition"] == "deviation"

        original_row = one_check(rows, "writer-original")
        assert original_row["actual"] == "committed_this_round"
        finished = finished_details(delivery)
        writers = {w["role"]: w for w in finished["writers"]}
        assert writers["original"]["fingerprint_source"] == "committed_writer"
        assert writers["original"]["sha256"] == hashlib.sha256(
            original.read_bytes()
        ).hexdigest(), "writer 对当前文件实际提交的 SHA"

        translated_row = one_check(rows, "writer-translated")
        assert translated_row["actual"] == "not_run", "翻译没运行，不是没请求"

        outcome = one_check(rows, "publication-outcome")
        assert outcome["actual"] == "published_incomplete"
        assert outcome["disposition"] == "deviation"

        detail = finished
        assert detail["translation"]["requested"] is True
        assert detail["translation"]["ran"] is False
        assert detail["translation"]["unavailable_error_type"] == "ValueError"

    def test_explicit_no_translate_is_an_expected_choice(self, f4_root):
        result = run_child(f4_root, "explicit-off")
        assert result["exit"] == 0
        rows = operation_rows(read_deliveries(f4_root, "default")[0]["rows"])
        requested = one_check(rows, "requested-outputs")
        assert requested["expected"] == "original_current"
        assert requested["actual"] == "original_current"
        assert requested["disposition"] == "expected"
        assert one_check(rows, "publication-outcome")["actual"] == "published_current"
        translated = one_check(rows, "writer-translated")
        assert translated["actual"] == "not_requested"
        assert translated["disposition"] == "expected"

    def test_unavailable_translator_reads_differently_from_explicit_off(self, f4_root):
        first = f4_root.parent / "f4-unavailable"
        first.mkdir()
        prepare_source(first)
        run_child(first, "translator-init")
        second = f4_root.parent / "f4-explicit"
        second.mkdir()
        prepare_source(second)
        run_child(second, "explicit-off")

        unavailable = one_check(
            operation_rows(read_deliveries(first, "default")[0]["rows"]),
            "requested-outputs",
        )
        explicit = one_check(
            operation_rows(read_deliveries(second, "default")[0]["rows"]),
            "requested-outputs",
        )
        assert unavailable["actual"] == "translation_unavailable"
        assert explicit["actual"] == "original_current"
        assert unavailable["actual"] != explicit["actual"]

    def test_translation_failure_keeps_old_translations_marked(self, f4_root):
        prepare_output(f4_root, "old-outputs")
        result = run_child(f4_root, "translation-failure")
        assert result["exit"] == 0, "翻译失败不改业务退出码"
        translated_file = f4_root / "out" / "audio_翻译.txt"
        assert translated_file.read_text(encoding="utf-8") == OLD_TRANSLATION

        delivery = read_deliveries(f4_root, "default")[0]
        rows = operation_rows(delivery["rows"])
        translated = one_check(rows, "writer-translated")
        assert translated["actual"] == "previous_kept"
        writers = {w["role"]: w for w in finished_details(delivery)["writers"]}
        assert writers["translated"]["sha256"] == hashlib.sha256(
            translated_file.read_bytes()
        ).hexdigest(), "旧译文的 SHA 与盘上字节一致"
        assert writers["translated"]["this_round"] is False
        requested = one_check(rows, "requested-outputs")
        assert requested["actual"] == "previous_translations_only"
        assert requested["issue_key"] == "stale-output-success"


# ── 原发生 2 之二：引擎回退（RED #2） ────────────────────────────


class TestEngineFallback:
    """主引擎失败后备用成功要记录为降级，原因链可冷读分辨。"""

    def test_fallback_success_is_recorded_as_degraded(self, f4_root):
        result = run_child(f4_root, "fallback-timeout")
        assert result["exit"] == 0
        original = f4_root / "out" / "audio_原文.txt"
        assert "Revenue grew" in original.read_text(encoding="utf-8")
        assert engine_calls(f4_root) == 2, "主引擎尝试一次，备用引擎一次"

        delivery = read_deliveries(f4_root, "default")[0]
        rows = operation_rows(delivery["rows"])
        fallback = one_check(rows, "engine-fallback")
        assert fallback["expected"] == "primary_only"
        assert fallback["actual"] == "fallback_engaged"
        assert fallback["disposition"] == "deviation"

        outcome = one_check(rows, "publication-outcome")
        assert outcome["actual"] == "published_degraded", "成功回退记录为降级"
        assert outcome["disposition"] == "deviation"

        requested = one_check(rows, "requested-outputs")
        assert requested["actual"] == "original_current"
        assert requested["disposition"] == "expected", "产物与请求一致"

        detail = finished_details(delivery)
        assert detail["engine"]["fallback_engaged"] is True
        assert detail["engine"]["primary_error"]["error_type"] == "RuntimeError"
        assert "TimeoutError" in detail["engine"]["primary_error"]["cause_types"]

    def test_same_outer_failure_with_different_inner_cause_reads_differently(self, tmp_path):
        first = tmp_path / "timeout-case"
        first.mkdir()
        prepare_source(first)
        run_child(first, "fallback-timeout")
        second = tmp_path / "valueerror-case"
        second.mkdir()
        prepare_source(second)
        run_child(second, "fallback-valueerror")

        def primary_chain(root):
            delivery = read_deliveries(root, "default")[0]
            return finished_details(delivery)["engine"]["primary_error"]

        timeout_case = primary_chain(first)
        valueerror_case = primary_chain(second)
        # 外层异常类别在 error_type，cause_types 只含底层原因。
        assert timeout_case["error_type"] == "RuntimeError"
        assert timeout_case["cause_types"] == ["TimeoutError"]
        assert valueerror_case["error_type"] == "RuntimeError"
        assert valueerror_case["cause_types"] == ["ValueError"]
        assert timeout_case != valueerror_case, "同外层不同内因必须可分辨"

    def test_fallback_unavailable_is_a_transcription_failure(self, f4_root):
        result = run_child(f4_root, "fallback-unavailable")
        assert result["exit"] == 1
        assert engine_calls(f4_root) == 1, "备用创建失败：备用引擎没有运行"
        delivery = read_deliveries(f4_root, "default")[0]
        rows = operation_rows(delivery["rows"])
        fallback = one_check(rows, "engine-fallback")
        assert fallback["actual"] == "fallback_unavailable"
        outcome = one_check(rows, "publication-outcome")
        assert outcome["actual"] == "transcription_failed"
        detail = finished_details(delivery)
        assert detail["engine"]["fallback_engaged"] is False
        errors = {entry["error_type"] for entry in detail["errors"]}
        assert "OSError" in errors, "备用创建失败的原因"

    def test_plain_provider_failure_keeps_the_cause_chain(self, f4_root):
        result = run_child(f4_root, "provider-fail")
        assert result["exit"] == 1
        delivery = read_deliveries(f4_root, "default")[0]
        rows = operation_rows(delivery["rows"])
        outcome = one_check(rows, "publication-outcome")
        assert outcome["actual"] == "transcription_failed"
        assert not by_check(rows, "engine-fallback"), "没有回退就没有回退行"
        detail = finished_details(delivery)
        chain = [entry["error_type"] for entry in detail["errors"]]
        assert chain == ["RuntimeError"], "外层异常在原生异常类别里"
        assert "TimeoutError" in detail["errors"][0].get("cause_types", []), \
            "底层 TimeoutError 进入脱敏因果链"

    def test_normal_primary_success_has_no_fallback_row(self, f4_root):
        result = run_child(f4_root, "explicit-off")
        assert result["exit"] == 0
        rows = operation_rows(read_deliveries(f4_root, "default")[0]["rows"])
        assert not by_check(rows, "engine-fallback")
        assert one_check(rows, "transcription-started")["actual"] == "engine_started"


# ── 失败记录、强停与复用 ─────────────────────────────────────────


class TestFailureRecordsAndRecovery:
    """失败记录到原步骤；强停保留原尝试与未知用量；复用不触发远程服务。"""

    def test_writer_failure_records_the_failed_role(self, f4_root):
        prepare_output(f4_root, "original-is-dir")
        result = run_child(f4_root, "writer-fail")
        assert result["exit"] == 1
        delivery = read_deliveries(f4_root, "default")[0]
        rows = operation_rows(delivery["rows"])
        original = one_check(rows, "writer-original")
        assert original["actual"] == "failed"
        outcome = one_check(rows, "publication-outcome")
        assert outcome["actual"] == "write_failed"
        writers = {w["role"]: w for w in finished_details(delivery)["writers"]}
        assert writers["original"]["sha256"] is None, "失败的角色没有提交指纹"

    def test_reuse_triggers_no_engine_and_no_translation(self, f4_root):
        prepare_output(f4_root, "original")
        result = run_child(f4_root, "reuse")
        assert result["exit"] == 0
        assert not (f4_root / "engine-calls").exists(), "成功复用不触发远程服务"
        assert (f4_root / "out" / "audio_原文.txt").read_text(encoding="utf-8") == OLD_ORIGINAL
        delivery = read_deliveries(f4_root, "default")[0]
        rows = operation_rows(delivery["rows"])
        assert one_check(rows, "transcription-started")["actual"] == "engine_not_started"
        assert one_check(rows, "requested-outputs")["actual"] == "reused_existing"
        assert one_check(rows, "publication-outcome")["actual"] == "reused_existing"

    def _reconcile_twice(self, root, delivery, row):
        request, _ = reconcile_request(row)
        db = root / "action.db"
        sidecar = delivery["path"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(call_owner, root, db, sidecar, "reconcile", request)
                for _ in range(2)
            ]
            results = [future.result() for future in futures]
        return results

    def test_kill_keeps_attempt_unknown_usage_and_reconciles_without_rerun(self, f4_root):
        child = start_child(f4_root, "kill")
        try:
            wait_for(f4_root / "engine-calls")
            child.kill()
        finally:
            child.wait(timeout=15)
        deliveries = read_deliveries(f4_root, "default")
        assert len(deliveries) == 1
        delivery = deliveries[0]
        rows = delivery["rows"]
        assert one_check(rows, "run-started")["actual"] == "started"
        op_rows = operation_rows(rows)
        started = one_check(op_rows, "action-started")
        assert started["attempt_id"], "原 attempt 保留"
        assert not by_check(op_rows, "publication-outcome"), "没有可信终态"
        assert not by_check(op_rows, "cost-receipt"), "没有编造的用量"
        assert engine_calls(f4_root) == 1

        results = self._reconcile_twice(f4_root, delivery, started)
        for reply in results:
            assert reply["state"] == "done"
            assert reply["result"]["job_status"] == "unconfirmed"
            assert reply["result"]["cost_state"] == "unknown"
        assert results[0] == results[1]
        assert engine_calls(f4_root) == 1, "对账不重跑转录"

    def test_kill_after_terminal_leaves_unconfirmed_delivery_window(self, f4_root):
        child = start_child(f4_root, "kill-after-terminal")
        try:
            wait_for(f4_root / "terminal-written")
            child.kill()
        finally:
            child.wait(timeout=15)
        deliveries = read_deliveries(f4_root, "default")
        assert len(deliveries) == 1
        delivery = deliveries[0]
        # 数据已落而 ready 未发：终态行可读，交付标记缺失。
        assert delivery["ready"] is None
        rows = operation_rows(delivery["rows"])
        outcome = one_check(rows, "publication-outcome")
        assert outcome["actual"] == "published_current"
        assert engine_calls(f4_root) == 1

        results = self._reconcile_twice(f4_root, delivery, outcome)
        for reply in results:
            assert reply["state"] == "done"
            assert reply["result"]["job_status"] == "succeeded"
        assert engine_calls(f4_root) == 1, "对账后计数为零增量"

    def test_get_action_of_the_same_action_is_read_only(self, f4_root):
        child = start_child(f4_root, "kill")
        try:
            wait_for(f4_root / "engine-calls")
            child.kill()
        finally:
            child.wait(timeout=15)
        delivery = read_deliveries(f4_root, "default")[0]
        started = one_check(operation_rows(delivery["rows"]), "action-started")
        row = dict(started, origin_owner=started["owner"])
        occurrence = _digest([row[field] for field in IDENTITY_FIELDS])
        body = {"occurrence_id": occurrence, "observation": row}
        triage_id = _digest(["triage", "meeting-converter", occurrence])
        triage_request = {
            "schema_version": "feedback-action/1", "kind": "triage",
            "owner": "meeting-converter", "action_id": triage_id, "method": "submit",
            "payload": body,
            "request_digest": _digest(["meeting-converter", "triage", triage_id, body]),
        }
        db = f4_root / "action.db"
        triage = call_owner(f4_root, db, delivery["path"], "triage", triage_request)
        assert triage["result"]["decision"] == "expected", "仅开始无终态：正常登记，不派修"
        before = engine_calls(f4_root)
        first = call_owner(f4_root, db, delivery["path"], "get-action", {"action_id": triage_id})
        second = call_owner(f4_root, db, delivery["path"], "get-action", {"action_id": triage_id})
        assert first == second, "同一动作的 get-action 幂等"
        assert first["receipt"]["request"]["kind"] == "triage"
        assert engine_calls(f4_root) == before, "重复查询不新增调用"


# ── 直启发布接口：三组隔离运行与三个窗口 ─────────────────────────


class TestDirectStartDelivery:
    """显式 OUT、仅 DIR、默认状态根三组隔离；OUT 优先。"""

    def test_explicit_out_keeps_the_single_shot_file(self, f4_root):
        result = run_child(f4_root, "explicit-off", mode="out")
        assert result["exit"] == 0
        single = read_single_out(f4_root)
        assert single["rows"], "OUT 单次文件沿用既有格式"
        assert single["details_rows"], "既有明细格式保留"
        assert read_deliveries(f4_root, "out") == [], "OUT 模式不产生交付文件"
        assert not (f4_root / "state").exists()

    def test_dir_only_delivery_publishes_ready_files(self, f4_root):
        result = run_child(f4_root, "explicit-off", mode="dir")
        assert result["exit"] == 0
        deliveries = read_deliveries(f4_root, "dir")
        assert len(deliveries) == 1
        assert deliveries[0]["ready"] is not None, "正常退出有 ready 标记"
        assert not (f4_root / "state").exists(), "DIR 设置时不写默认状态根"

    def test_default_delivery_uses_the_mapped_state_root(self, f4_root):
        result = run_child(f4_root, "explicit-off")
        assert result["exit"] == 0
        deliveries = read_deliveries(f4_root, "default")
        assert len(deliveries) == 1
        assert deliveries[0]["path"].parent == f4_root / "state" / "observations"

    def test_out_wins_over_dir(self, f4_root):
        result = run_child(f4_root, "explicit-off", mode="both")
        assert result["exit"] == 0
        assert read_single_out(f4_root)["rows"], "两个变量都有值时 OUT 优先"
        assert read_deliveries(f4_root, "both") == []

    def test_finalize_without_published_observations_writes_no_ready(self, f4_root):
        """观察文件补投失败就不写 .ready：不留下指向不完整交付的确认标记。"""
        from core.feedback import DeliveringRecorder, reset_state

        reset_state()
        observations = f4_root / "state" / "observations"
        recorder = DeliveringRecorder(observations, run_id="run-finalize", attempt_id="attempt-1")
        # 只让观察文件发布失败：门槛必须只认观察文件，明细成功不算数。
        real_publish = DeliveringRecorder._publish

        def observations_fail(path, lines):
            if path == recorder.out_path:
                return False
            return real_publish(recorder, path, lines)

        recorder._publish = observations_fail
        recorder.record(
            step_id="mc-startup/x", check_id="run-started", expected="started",
            actual="started", disposition="expected", evidence_ref="mc-startup/x",
            details={"phase": "started", "step_id": "mc-startup/x"},
        )
        assert recorder.finalize_delivery() is False
        assert not recorder.out_path.exists(), "观察行从未落盘"
        assert recorder.details_path.is_file(), "明细照常落盘"
        assert not (observations / f"feedback-{recorder.delivery_id}.ready").exists()

    def test_ready_marker_binds_occurrence_without_paths_or_commands(self, f4_root):
        run_child(f4_root, "explicit-off")
        delivery = read_deliveries(f4_root, "default")[0]
        marker = delivery["ready"]
        assert marker["owner"] == "meeting-converter"
        assert marker["run_id"] and marker["attempt_id"]
        assert marker["schema_version"] == "feedback-delivery-ready/1"
        assert marker["observations"] == len(delivery["rows"])
        assert marker["details"] == len(delivery["details_rows"])
        assert marker["observations_sha256"] == hashlib.sha256(delivery["path"].read_bytes()).hexdigest()
        details_path = delivery["path"].with_name(delivery["path"].name + ".details.jsonl")
        assert marker["details_sha256"] == hashlib.sha256(details_path.read_bytes()).hexdigest()
        steps = marker["step_ids"]
        assert steps == sorted({row["step_id"] for row in delivery["rows"]})
        assert any(step.startswith("meeting-operation/") for step in steps)
        blob = json.dumps(marker, ensure_ascii=False)
        assert str(f4_root) not in blob
        assert "transcribe" not in blob
        assert "--" not in blob

    def test_unwritable_inbox_keeps_original_outcome_in_owner_recovery(self, f4_root):
        state = f4_root / "state"
        state.mkdir()
        unavailable = state / "observations"
        unavailable.write_bytes(b"blocked inbox")
        first = run_child(f4_root, "fallback-timeout")
        assert first["exit"] == 0
        before = engine_calls(f4_root)
        recovery = state / "recovery"
        ready, = recovery.glob("feedback-*.ready")
        rows = _read_jsonl(ready.with_suffix(".jsonl"))
        terminal = one_check(operation_rows(rows), "publication-outcome")
        assert terminal["actual"] == "published_degraded"
        request, _ = reconcile_request(terminal)
        proof = call_owner(
            f4_root, state / "owner.sqlite", state / "unused.jsonl", "reconcile", request,
            directories=(recovery, unavailable),
        )
        assert proof["result"]["job_status"] == "succeeded"
        assert proof["result"]["cost_state"] == "unknown"
        assert unavailable.read_bytes() == b"blocked inbox" and engine_calls(f4_root) == before

    @pytest.mark.windows_only
    @pytest.mark.skipif(os.name != "nt", reason="Windows native path boundary")
    def test_long_state_directory_accepts_and_recovers_an_original_failure(self, f4_root):
        state = f4_root.joinpath(*("日" + "directory" * 4 for _ in range(7)))
        env = _child_env(f4_root, "default")
        env["RESEARCH_FEEDBACK_STATE_ROOT"] = str(state)
        command = [sys.executable, "-B", "-X", "utf8", str(RUNNER), "--child",
                   str(REPO), str(f4_root), "fallback-timeout"]
        child = subprocess.run(command, cwd=f4_root, env=env, capture_output=True, timeout=20)
        assert child.returncode == 0
        directory = state / "observations"
        native = Path("\\\\?\\" + str(directory))
        ready, = native.glob("feedback-*.ready")
        terminal = one_check(operation_rows(_read_jsonl(ready.with_suffix(".jsonl"))), "publication-outcome")
        request, _ = reconcile_request(terminal)
        proof = call_owner(f4_root, f4_root / "owner.sqlite", f4_root / "unused.jsonl",
                           "reconcile", request, directories=(directory,))
        assert proof["result"]["job_status"] == "succeeded"
        assert engine_calls(f4_root) == 2

    def test_delivery_details_are_redacted(self, f4_root):
        run_child(f4_root, "fallback-timeout")
        delivery = read_deliveries(f4_root, "default")[0]
        text = delivery["details_text"]
        assert str(f4_root) not in text, "绝对路径不出仓"
        assert "audio.wav" not in text, "音频名不出仓"
        assert "fixture upstream failed" not in text, "原始异常正文不出仓"
        assert "fixture-timeout" not in text
        assert "TimeoutError" in text, "脱敏因果链保留异常类别"

    def test_delivered_rows_carry_cross_process_identity(self, f4_root):
        run_child(f4_root, "explicit-off")
        delivery = read_deliveries(f4_root, "default")[0]
        rows = delivery["rows"]
        assert {row["owner"] for row in rows} == {"meeting-converter"}
        run_ids = {row["run_id"] for row in rows}
        assert len(run_ids) == 1
        run_id = run_ids.pop()
        assert run_id and run_id != "", "缺省时生成可跨进程查回的 ID"
        assert delivery["rows"][0]["attempt_id"] == "attempt-1"

    def test_redelivery_with_the_recorded_identity_is_idempotent(self, f4_root):
        """已发但回告丢失：按记录过的交付身份补发，不重复登记原发生。"""
        from core.feedback import DeliveringRecorder, reset_state

        run_child(f4_root, "explicit-off")
        delivery = read_deliveries(f4_root, "default")[0]
        rows_before = delivery["rows"]
        assert rows_before
        delivery_id = delivery["path"].stem[len("feedback-"):]

        reset_state()
        recorder = DeliveringRecorder(
            delivery["path"].parent,
            run_id=rows_before[0]["run_id"],
            attempt_id=rows_before[0]["attempt_id"],
            delivery_id=delivery_id,
        )
        observable_fields = (
            "step_id", "check_id", "expected", "actual", "disposition",
            "issue_key", "evidence_ref", "parent_step_id", "origin_owner",
            "terminal_check_id",
        )
        for row in rows_before:
            recorder.record(
                **{name: row[name] for name in observable_fields if name in row}
            )
        assert len(_read_jsonl(delivery["path"])) == len(rows_before), \
            "补发同一份原发生不新增行"
        assert recorder.finalize_delivery()
        assert delivery["path"].with_name(delivery["path"].stem + ".ready").is_file()

    def test_published_delivery_is_complete_and_line_terminated(self, f4_root):
        """发布完成的交付文件只含完整 JSON 行（发布是同目录临时文件+原子替换）。"""
        run_child(f4_root, "fallback-timeout")
        delivery = read_deliveries(f4_root, "default")[0]
        rows = delivery["rows"]
        assert rows, "发布完成的文件行数一致"
        assert all(isinstance(row, dict) for row in rows)
        raw = delivery["path"].read_text(encoding="utf-8")
        assert raw.endswith("\n"), "每行都以换行收尾，重复消费不会粘连"
        assert one_check(rows, "publication-outcome")

    def test_concurrent_reader_never_sees_a_partial_file(self, f4_root):
        """并发消费：子进程逐次发布期间，读方循环冷读只见完整 JSON 行。"""
        import threading

        errors = []
        parsed = []
        stop = threading.Event()
        observations = f4_root / "state" / "observations"

        def reader():
            while not stop.is_set():
                if not observations.exists():
                    time.sleep(0.01)
                    continue
                files = sorted(
                    p for p in observations.glob("feedback-*.jsonl")
                    if not p.name.endswith(".details.jsonl")
                )
                if not files:
                    time.sleep(0.01)
                    continue
                try:
                    text = files[0].read_text(encoding="utf-8")
                except OSError:
                    # Windows 替换瞬间的 sharing violation：读方重试，不算部分文件。
                    time.sleep(0.005)
                    continue
                for line in text.splitlines():
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        errors.append(exc)
                        continue
                    if isinstance(row, dict) and "check_id" in row:
                        parsed.append(row)
                time.sleep(0.005)

        worker = threading.Thread(target=reader)
        worker.start()
        try:
            child = start_child(f4_root, "kill-after-terminal")
            try:
                wait_for(f4_root / "terminal-written")
                child.kill()
            finally:
                child.wait(timeout=15)
        finally:
            stop.set()
            worker.join(timeout=10)

        assert not errors, f"并发读方读到了不完整文件: {errors[:3]}"
        check_ids = {row["check_id"] for row in parsed}
        assert "run-started" in check_ids, "并发期间至少读到启动收据"
        assert "publication-outcome" in check_ids, "终态已写后读方可见"

    def test_two_tasks_are_isolated_by_their_own_delivery_files(self, tmp_path):
        first = tmp_path / "task-a"
        second = tmp_path / "task-b"
        first.mkdir()
        second.mkdir()
        prepare_source(first)
        prepare_source(second)
        run_child(first, "explicit-off")
        run_child(second, "explicit-off")
        first_delivery = read_deliveries(first, "default")
        second_delivery = read_deliveries(second, "default")
        assert len(first_delivery) == len(second_delivery) == 1
        assert first_delivery[0]["path"].name != second_delivery[0]["path"].name
        first_run = first_delivery[0]["rows"][0]["run_id"]
        second_run = second_delivery[0]["rows"][0]["run_id"]
        assert first_run != second_run, "两个并发任务隔离"
