"""core/feedback.py - 本仓转录发布的反馈观察投影（``feedback-observation/1``）。

这个模块把一次转录操作的事实投影成跨仓可读的观察行。它只写两样东西：
``RESEARCH_FEEDBACK_OUT`` 指定的 JSONL 旁路，和该文件同名的 ``*.details.jsonl``
步骤日志。旁路本身不写 stdout/stderr、不改返回值、不改任何产物字节，也不触碰
逐字稿正文。旁路写不进去时，只在本仓已有的本地诊断通道（logging）和 recorder
自身的计数上报告；业务结果、退出码与重试行为完全由主任务自己决定。注意：
本仓 CLI 把 logging 接到 stdout（``transcribe.py``），因此这些**诊断行**会出现在
CLI 的 stdout 上，业务日志行本身不变。

词表（稳定结果词；细节留在本仓的 details 记录里）：

``requested-outputs``
    expected 取本次请求模式：原文模式 ``original_current``，翻译模式
    ``original_translated_bilingual_current``，命中已有原件的跳过规则时
    ``reused_existing``。actual 取本轮真正提交的结果：``original_current`` /
    ``original_translated_bilingual_current`` / ``previous_translations_only`` /
    ``stale_and_missing_translations`` / ``missing_translations`` /
    ``partial_current`` / ``reused_existing`` / ``write_failed`` /
    ``transcription_failed`` / ``translation_failed`` / ``unknown``。
    “本轮产出但只提交了部分目标”“只保留上一版译文”“一次成功的原文模式”
    是三件不同的事，因此有三个不同的 actual。

``writer-<role>``
    role 取 ``original`` / ``translated`` / ``bilingual``。actual 取
    ``committed_this_round`` / ``not_requested`` / ``previous_kept`` /
    ``absent`` / ``failed``。

``transcription-started``
    actual 取 ``engine_started`` / ``engine_not_started``，用来证明引擎是否
    真的被调用过。

``publication-outcome``
    终态：``published_current`` / ``published_partial`` /
    ``published_incomplete`` / ``reused_existing`` / ``write_failed`` /
    ``transcription_failed`` / ``translation_failed`` / ``unknown``。
    ``published_partial`` 是“提交了部分目标，另一个 writer 失败”，
    ``published_incomplete`` 是“本轮没产出译文，只剩上一版或根本没有”——两件
    不同的事，因此在终态上也分开。

``cost-receipt``
    本仓没有用量收据，因此费用恒为 ``cost_unknown``，disposition 为
    ``unknown``。

身份：每次真实调用有自己的 step，前缀保留不透明的输入标识。本轮开始和结束
共用该 step。同一次运行里首次转录、随后跳过或再次转录分别占用不同 step。
证据引用为 mc-output/<input_id> 或 mc-output/<input_id>/<role>。重投原 JSONL
保留已经写出的所有身份。

详情只保留结构化阶段、角色及异常类型。完整异常由原生产日志负责。本轮提交
的指纹由原子 writer 提供。旧件诊断在业务计时结束后读取，读取失败时保留已知事实。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from core.output import WrittenOutput

logger = logging.getLogger(__name__)

OBSERVATION_SCHEMA = "feedback-observation/1"
DETAIL_SCHEMA = "meeting-converter-feedback-detail/1"
OWNER = "meeting-converter"
ADAPTER_VERSION = "meeting-converter-feedback/1.0.3"

FEEDBACK_OUT_ENV = "RESEARCH_FEEDBACK_OUT"
FEEDBACK_RUN_ID_ENV = "RESEARCH_FEEDBACK_RUN_ID"
FEEDBACK_ATTEMPT_ID_ENV = "RESEARCH_FEEDBACK_ATTEMPT_ID"

DISPOSITIONS = ("expected", "deviation", "unknown")

# ── check 名 ─────────────────────────────────────────────────────

CHECK_ACTION_STARTED = "action-started"
CHECK_TRANSCRIPTION_STARTED = "transcription-started"
CHECK_WRITER_PREFIX = "writer-"
CHECK_REQUESTED_OUTPUTS = "requested-outputs"
CHECK_PUBLICATION_OUTCOME = "publication-outcome"
CHECK_COST_RECEIPT = "cost-receipt"
TERMINAL_CHECK_ID = CHECK_PUBLICATION_OUTCOME

# ── writer 角色 ──────────────────────────────────────────────────

ROLE_ORIGINAL = "original"
ROLE_TRANSLATED = "translated"
ROLE_BILINGUAL = "bilingual"
ROLES = (ROLE_ORIGINAL, ROLE_TRANSLATED, ROLE_BILINGUAL)

# ── 请求模式 ─────────────────────────────────────────────────────

MODE_ORIGINAL_ONLY = "original_only"
MODE_TRANSLATED = "translated_and_bilingual"

# ── 结果词 ───────────────────────────────────────────────────────

EXPECTED_ORIGINAL_CURRENT = "original_current"
EXPECTED_ALL_CURRENT = "original_translated_bilingual_current"
EXPECTED_REUSED = "reused_existing"

ACTUAL_PREVIOUS_TRANSLATIONS = "previous_translations_only"
ACTUAL_STALE_AND_MISSING = "stale_and_missing_translations"
ACTUAL_MISSING_TRANSLATIONS = "missing_translations"
ACTUAL_PARTIAL = "partial_current"
ACTUAL_WRITE_FAILED = "write_failed"
ACTUAL_TRANSCRIPTION_FAILED = "transcription_failed"
ACTUAL_TRANSLATION_FAILED = "translation_failed"
ACTUAL_UNKNOWN = "unknown"

PUBLISHED_CURRENT = "published_current"
PUBLISHED_PARTIAL = "published_partial"
PUBLISHED_INCOMPLETE = "published_incomplete"

WRITER_COMMITTED = "committed_this_round"
WRITER_NOT_REQUESTED = "not_requested"
WRITER_PREVIOUS_KEPT = "previous_kept"
WRITER_ABSENT = "absent"
WRITER_FAILED = "failed"
WRITER_PRESENCE_UNKNOWN = "presence_unknown"

ENGINE_STARTED = "engine_started"
ENGINE_NOT_STARTED = "engine_not_started"

COST_UNKNOWN = "cost_unknown"

# ── 阶段 ─────────────────────────────────────────────────────────

STAGE_TRANSCRIPTION = "transcription"
STAGE_TRANSLATION = "translation"
STAGE_OUTPUT = "output"

# ── issue_key（本仓认可的规则签名）────────────────────────────────

ISSUE_STALE_OUTPUT = "stale-output-success"

def _is_str(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def now() -> str:
    """本轮运行的 UTC 时间戳（秒精度）。"""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def input_identity(path: Any) -> str:
    """一个输入文件的稳定、不透明身份。

    身份由解析后的路径散列而来：同一文件在重投时沿用原身份，而同一批里
    两个同名但来源不同的音频仍然可区分。路径本身不离开本仓。
    """
    try:
        resolved = str(Path(path).resolve())
    except OSError:
        resolved = str(path)
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]


def evidence_ref_for(input_id: str, role: Optional[str] = None) -> str:
    """本仓能解释的逻辑证据引用。"""
    if role:
        return f"mc-output/{input_id}/{role}"
    return f"mc-output/{input_id}"


def _observation_identity(record: Mapping[str, Any]) -> Tuple[str, ...]:
    """一行观察的去重身份：位置 + 内容。"""
    return (
        str(record.get("owner", "")),
        str(record.get("run_id", "")),
        str(record.get("attempt_id", "")),
        str(record.get("step_id", "")),
        str(record.get("check_id", "")),
        str(record.get("expected", "")),
        str(record.get("actual", "")),
        str(record.get("disposition", "")),
    )


def _details_identity(record: Mapping[str, Any]) -> str:
    """一条 details 记录的内容身份。"""
    raw = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return "fb-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _read_jsonl(path: Path) -> List[dict]:
    """读取一个 JSONL 文件；读不到或不是 JSON 行时不给记录。"""
    try:
        if not path.is_file():
            return []
        raw = path.read_bytes()
    except OSError:
        return []
    records: List[dict] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


class FeedbackRecorder:
    """一次运行的单写者、只追加的 JSONL 落点。

    写失败永远不抛异常：它被记在 ``write_failures`` 与 ``diagnostics`` 上，
    并在本仓已有的本地诊断通道（logging）上报告，调用方保留自己的退出码、
    结果与重试行为。
    """

    def __init__(
        self,
        out_path: Any,
        *,
        run_id: str,
        attempt_id: str,
        version: str = ADAPTER_VERSION,
        owner: str = OWNER,
        details_path: Any = None,
        sink: Any = None,
        details_sink: Any = None,
    ) -> None:
        self.out_path = Path(out_path)
        self.details_path = (
            Path(details_path)
            if details_path is not None
            else self.out_path.with_name(self.out_path.name + ".details.jsonl")
        )
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.version = version
        self.owner = owner
        # 注入的 sink 取代文件本身，用来在不改宿主权限模型的前提下演练
        # 一个写不进去的目的地。
        self._sink = sink
        self._details_sink = details_sink
        self.write_failures = 0
        self.diagnostics: List[str] = []
        self._written: set = set()
        self._details_written: set = set()
        self._scan_existing()

    # ── 读回上一轮已经写下的内容 ──────────────────────────────────

    def _scan_existing(self) -> None:
        for record in _read_jsonl(self.out_path):
            if "check_id" in record:
                self._written.add(_observation_identity(record))
        for record in _read_jsonl(self.details_path):
            identifier = record.get("details_id")
            if isinstance(identifier, str):
                self._details_written.add(identifier)

    # ── 写 ────────────────────────────────────────────────────────

    def record(
        self,
        *,
        step_id: str,
        check_id: str,
        expected: str,
        actual: str,
        disposition: Optional[str] = None,
        issue_key: Optional[str] = None,
        evidence_ref: Optional[str] = None,
        details: Optional[Mapping[str, Any]] = None,
        parent_step_id: Optional[str] = None,
        origin_owner: Optional[str] = None,
        terminal_check_id: Optional[str] = None,
    ) -> bool:
        """追加一行观察。True 表示新的一行确实落盘了。"""
        try:
            return self._record(
                step_id=step_id,
                check_id=check_id,
                expected=expected,
                actual=actual,
                disposition=disposition,
                issue_key=issue_key,
                evidence_ref=evidence_ref,
                details=details,
                parent_step_id=parent_step_id,
                origin_owner=origin_owner,
                terminal_check_id=terminal_check_id,
            )
        except Exception as exc:  # 防御：投影永远不成为业务失败的原因
            self._note_failure(f"feedback_write_failed:{type(exc).__name__}")
            return False

    def _record(
        self,
        *,
        step_id: str,
        check_id: str,
        expected: str,
        actual: str,
        disposition: Optional[str],
        issue_key: Optional[str],
        evidence_ref: Optional[str],
        details: Optional[Mapping[str, Any]],
        parent_step_id: Optional[str],
        origin_owner: Optional[str],
        terminal_check_id: Optional[str],
    ) -> bool:
        if not all(_is_str(value) for value in (step_id, check_id, expected, actual)):
            self._note_failure("feedback_write_failed:invalid_observation")
            return False
        if disposition is None:
            disposition = "expected" if expected == actual else "deviation"
        if disposition not in DISPOSITIONS:
            self._note_failure("feedback_write_failed:invalid_disposition")
            return False

        observation: Dict[str, Any] = {
            "schema_version": OBSERVATION_SCHEMA,
            "owner": self.owner,
        }
        if origin_owner and origin_owner != self.owner:
            observation["origin_owner"] = origin_owner
        observation.update(
            {
                "run_id": self.run_id,
                "attempt_id": self.attempt_id,
                "step_id": step_id,
                "check_id": check_id,
                "expected": expected,
                "actual": actual,
                "disposition": disposition,
            }
        )
        if issue_key:
            observation["issue_key"] = issue_key
        if evidence_ref:
            observation["evidence_ref"] = evidence_ref
        observation["version"] = self.version
        if parent_step_id:
            observation["parent_step_id"] = parent_step_id
        if terminal_check_id:
            observation["terminal_check_id"] = terminal_check_id

        identity = _observation_identity(observation)
        if identity in self._written:
            # 重投同一份结果：沿用原身份，不新增行。
            return False

        if details is not None:
            detail_record = dict(details)
            identifier = _details_identity(detail_record)
            detail_record["details_id"] = identifier
            if identifier in self._details_written:
                observation["details_ref"] = identifier
            elif self._append_jsonl(
                self.details_path, detail_record, sink=self._details_sink
            ):
                self._details_written.add(identifier)
                observation["details_ref"] = identifier
            # details 写不进去时不写 details_ref：不留下指向不存在记录的悬挂引用。

        if not self._append_jsonl(self.out_path, observation, sink=self._sink):
            # 这一行没有到达旁路：它在这里不留身份，之后的尝试仍可送达。
            return False
        self._written.add(identity)
        return True

    def _append_jsonl(
        self, path: Path, record: Mapping[str, Any], *, sink: Any = None
    ) -> bool:
        """追加一行 JSON。False 表示这行没有落到目的地。"""
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        if sink is not None:
            try:
                sink(line)
            except Exception as exc:
                self._note_failure(f"feedback_write_failed:{type(exc).__name__}")
                return False
            return True
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a+b") as handle:
                # Keep a truncated old record on a separate line from the next append.
                handle.seek(0, os.SEEK_END)
                if handle.tell():
                    handle.seek(-1, os.SEEK_END)
                    if handle.read(1) != b"\n":
                        line = "\n" + line
                handle.write(line.encode("utf-8"))
        except OSError as exc:
            self._note_failure(f"feedback_write_failed:{type(exc).__name__}")
            return False
        return True

    def _note_failure(self, kind: str) -> None:
        """记录一条不完整的诊断，并在本仓已有的本地诊断通道上报告。

        诊断留在 recorder 内存里，同时走 logging（stdout/stderr 的内容不受
        影响的是业务输出；本条是诊断，不是业务结果）。主任务的退出码、结果
        与重试行为完全不受影响。
        """
        self.write_failures += 1
        self.diagnostics.append(kind)
        logger.warning(f"反馈旁路写入失败（不影响本次转录结果）: {kind}")

    def note_failure(self, kind: str) -> None:
        """对外的诊断入口（供 flush 兜底使用）。"""
        self._note_failure(kind)


# ── 进程内 recorder ──────────────────────────────────────────────

_RECORDERS: Dict[Tuple[str, str, str], FeedbackRecorder] = {}
_LAST_RECORDER: Optional[FeedbackRecorder] = None
#: 宿主没有给出运行身份时，本进程自成一个运行——同一个进程里的所有操作
#: 必须属于同一个运行，否则一批文件会被报成许多个互不相干的运行。
_PROCESS_RUN_ID = "run-" + uuid.uuid4().hex[:12]


def recorder_from_env(
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[FeedbackRecorder]:
    """本进程的 recorder；没有指定旁路目的地时返回 None。

    目的地由宿主通过 ``RESEARCH_FEEDBACK_OUT`` 指定；运行与尝试身份可以由
    宿主通过 ``RESEARCH_FEEDBACK_RUN_ID`` / ``RESEARCH_FEEDBACK_ATTEMPT_ID``
    提供。目的地不合法时返回 None：旁路永远不能让主任务失败。
    """
    global _LAST_RECORDER

    env = os.environ if environ is None else environ
    raw = env.get(FEEDBACK_OUT_ENV)
    if not isinstance(raw, str) or not raw.strip():
        return None
    out = raw.strip()
    run_id = env.get(FEEDBACK_RUN_ID_ENV)
    if not _is_str(run_id):
        run_id = _PROCESS_RUN_ID
    attempt_id = env.get(FEEDBACK_ATTEMPT_ID_ENV)
    if not _is_str(attempt_id):
        attempt_id = "attempt-1"

    key = (out, run_id, attempt_id)
    recorder = _RECORDERS.get(key)
    if recorder is None:
        try:
            recorder = FeedbackRecorder(out, run_id=run_id, attempt_id=attempt_id)
        except Exception as exc:
            # 目的地不合法（例如没有文件名的盘符）：旁路不可用，但主任务照常。
            logger.warning(f"反馈旁路目的地不可用（不影响本次转录结果）: {type(exc).__name__}")
            return None
        _RECORDERS[key] = recorder
    _LAST_RECORDER = recorder
    return recorder


def current_recorder() -> Optional[FeedbackRecorder]:
    """本进程最近一次的 recorder；没有启用旁路时为 None。"""
    return _LAST_RECORDER


def reset_state() -> None:
    """清空进程内的 recorder 缓存（测试与独立重放使用）。"""
    global _LAST_RECORDER

    _RECORDERS.clear()
    _LAST_RECORDER = None


# ── 一次操作的投影 ───────────────────────────────────────────────


class OperationFeedback:
    """一次转录操作在旁路上的投影。

    没有启用旁路时，所有方法都是空操作：业务代码不需要为它写分支。

    观察行先在内存里缓冲，只有 :meth:`flush` 才真正写盘。调用方必须在
    没有任何计时器打开时调用它，否则旁路自身的写入耗时会混进发布出去的
    耗时字段，改变三个产物文件的字节。
    """

    def __init__(
        self,
        recorder: Optional[FeedbackRecorder],
        *,
        input_id: str,
        requested_mode: str,
        force: bool,
    ) -> None:
        self._recorder = recorder
        self.input_id = input_id
        self.step_id = f"meeting-operation/{input_id}/{uuid.uuid4().hex}" if recorder else ""
        self.requested_mode = requested_mode
        self.force = bool(force)
        self._writers: Dict[str, Dict[str, Any]] = {}
        self._writer_paths: Dict[str, Path] = {}
        self._errors: List[Dict[str, Any]] = []
        self._engine_started = False
        self._stage = STAGE_TRANSCRIPTION
        self._aborted = False
        self._unknown = False
        self._reused: Optional[Dict[str, Any]] = None
        self._finished = False
        self._pending: List[Dict[str, Any]] = []
        self._started_details: Optional[Dict[str, Any]] = None

    # ── 事实 ──────────────────────────────────────────────────────

    def set_stage(self, stage: str) -> None:
        """记录当前处于哪个阶段（用于区分终态的失败原因）。"""
        self._stage = stage

    def note_engine_started(self) -> None:
        """引擎即将被调用。"""
        self._engine_started = True
        self._emit_transcription_started(ENGINE_STARTED)

    def note_engine_not_started(self) -> None:
        """本轮没有调用引擎（命中已有原件的跳过规则）。"""
        self._engine_started = False
        self._emit_transcription_started(ENGINE_NOT_STARTED)

    @property
    def enabled(self) -> bool:
        return self._recorder is not None

    def note_writer_committed(self, role: str, witness: Optional[WrittenOutput]) -> None:
        if self._recorder is None:
            return
        self._note_writer(role, WRITER_COMMITTED)
        if witness is not None:
            self._writers[role].update(
                sha256=witness.sha256, bytes=witness.size, fingerprint_source="committed_writer",
            )

    def note_writer_failed(self, role: str, path: Path, error: BaseException) -> None:
        self._note_writer(role, WRITER_FAILED, path)
        self._note_error(role, error)

    def note_writer_not_requested(self, role: str) -> None:
        self._note_writer(role, WRITER_NOT_REQUESTED)

    def note_writer_not_produced(self, role: str, path: Path) -> None:
        self._note_writer(role, WRITER_PRESENCE_UNKNOWN, path)

    def _note_writer(self, role: str, result: str, path: Optional[Path] = None) -> None:
        if self._recorder is None:
            return
        self._writers[role] = {
            "role": role,
            "result": result,
            "this_round": result == WRITER_COMMITTED,
            "sha256": None,
            "bytes": None,
        }
        if path is not None:
            self._writer_paths[role] = path

    def note_reuse(self, translated: Path, bilingual: Path) -> None:
        """The original file already passed the production reuse check."""
        if self._recorder is not None:
            self._reused = {
                "original": True,
                "translated": _has_regular_file(translated),
                "bilingual": _has_regular_file(bilingual),
            }

    def note_abort(self) -> None:
        """本轮被异常中止：终态是失败，不是部分完成。"""
        self._aborted = True

    def mark_unknown(self) -> None:
        """本轮被中止，没有可信终态：终态保留 unknown。"""
        self._unknown = True

    def note_error(self, error: BaseException) -> None:
        """记录本轮的一个原始异常（本仓自己保留细节）。"""
        self._note_error(None, error)

    def _note_error(self, role: Optional[str], error: BaseException) -> None:
        if self._recorder is None:
            return
        error_type = type(error).__name__
        if any(
            item["stage"] == self._stage and item["error_type"] == error_type
            and (role is None or item["role"] == role)
            for item in self._errors
        ):
            return
        self._errors.append({"stage": self._stage, "role": role, "error_type": error_type})

    # ── 观察 ──────────────────────────────────────────────────────

    def start(self) -> None:
        """记录操作开始——它发生在结果可能出现之前。"""
        if self._recorder is None:
            return
        self._started_details = self._details_payload("started")
        self._pending.append(
            {
                "step_id": self.step_id,
                "check_id": CHECK_ACTION_STARTED,
                "expected": "started",
                "actual": "started",
                "disposition": "expected",
                "evidence_ref": evidence_ref_for(self.input_id),
                "terminal_check_id": TERMINAL_CHECK_ID,
                "details": self._started_details,
            }
        )
        # 开始行立刻落盘：此刻还没有任何计时器打开。
        self.flush()

    def finish(self, metrics: Optional[Mapping[str, Any]] = None) -> None:
        """记录本轮终态（先缓冲，由 :meth:`flush` 落盘）。"""
        if self._finished:
            return
        self._finished = True
        if self._recorder is None:
            return

        self._probe_writer_outputs()
        details = self._details_payload("finished", metrics=metrics)
        self._emit_writer_rows(details)

        requested_expected = self._requested_expected()
        requested_actual = self._requested_actual()
        self._pending.append(
            {
                "step_id": self.step_id,
                "check_id": CHECK_REQUESTED_OUTPUTS,
                "expected": requested_expected,
                "actual": requested_actual,
                "disposition": (
                    "unknown"
                    if requested_actual == ACTUAL_UNKNOWN
                    else (
                        "expected"
                        if requested_expected == requested_actual
                        else "deviation"
                    )
                ),
                "issue_key": self._issue_key(requested_actual),
                "evidence_ref": evidence_ref_for(self.input_id),
                "details": details,
            }
        )

        outcome = self._publication_actual()
        outcome_expected = (
            EXPECTED_REUSED if self._reused is not None else PUBLISHED_CURRENT
        )

        # 费用行先写，终态行最后写：这样一次没写完的旁路一定以“没有终态”
        # 收尾，消费方据此判定终态未知，而不会把半截记录读成可信终态。
        self._pending.append(
            {
                "step_id": self.step_id,
                "check_id": CHECK_COST_RECEIPT,
                "expected": COST_UNKNOWN,
                "actual": COST_UNKNOWN,
                "disposition": "unknown",
                "evidence_ref": evidence_ref_for(self.input_id),
                "details": details,
            }
        )

        self._pending.append(
            {
                "step_id": self.step_id,
                "check_id": CHECK_PUBLICATION_OUTCOME,
                "expected": outcome_expected,
                "actual": outcome,
                "disposition": (
                    "unknown"
                    if outcome == ACTUAL_UNKNOWN
                    else (
                        "expected"
                        if outcome_expected == outcome
                        else "deviation"
                    )
                ),
                "evidence_ref": evidence_ref_for(self.input_id),
                "details": details,
            }
        )

    def flush(self) -> None:
        """把缓冲的观察写到旁路。

        调用方必须在没有任何计时器打开时调用它：旁路自身的写入耗时不属于
        被测量的那段工作。重复调用是安全的——同样的内容只写一次。

        写盘过程中出现的任何异常都不得替换业务结果：这里的异常一律记成
        不完整的诊断，业务的返回值与退出码不受影响。
        """
        if self._recorder is None or not self._pending:
            return
        pending, self._pending = self._pending, []
        for entry in pending:
            try:
                self._recorder.record(**entry)
            except BaseException as exc:  # 旁路的任何异常都不替换业务结果
                self._recorder.note_failure(
                    f"feedback_write_failed:{type(exc).__name__}"
                )

    # ── 内部 ──────────────────────────────────────────────────────

    def _emit_transcription_started(self, actual: str) -> None:
        if self._recorder is None:
            return
        self._pending.append(
            {
                "step_id": self.step_id,
                "check_id": CHECK_TRANSCRIPTION_STARTED,
                "expected": actual,
                "actual": actual,
                "disposition": "expected",
                "evidence_ref": evidence_ref_for(self.input_id),
                "details": self._started_details,
            }
        )

    def _emit_writer_rows(self, details: Mapping[str, Any]) -> None:
        if self._recorder is None:
            return
        for role in ROLES:
            entry = self._writers.get(role)
            if entry is None:
                continue
            expected = self._writer_expected(role)
            actual = entry["result"]
            self._pending.append(
                {
                    "step_id": self.step_id,
                    "check_id": f"{CHECK_WRITER_PREFIX}{role}",
                    "expected": expected,
                    "actual": actual,
                    "disposition": (
                        "unknown" if actual == WRITER_PRESENCE_UNKNOWN
                        else "expected" if expected == actual else "deviation"
                    ),
                    "evidence_ref": evidence_ref_for(self.input_id, role),
                    "details": details,
                }
            )

    def _issue_key(self, requested_actual: str) -> Optional[str]:
        """根因已确认时才带 issue_key。

        ``stale-output-success`` 只覆盖“上一版确实留在了盘上”这一类；
        ``missing_translations``（连上一版都没有）与它可观察到的现象不同，
        责任层相同但没有可指认的旧件，因此不带 issue_key。
        """
        if requested_actual in (ACTUAL_PREVIOUS_TRANSLATIONS, ACTUAL_STALE_AND_MISSING):
            return ISSUE_STALE_OUTPUT
        return None

    def _writer_expected(self, role: str) -> str:
        if role == ROLE_ORIGINAL:
            return WRITER_COMMITTED
        if self.requested_mode == MODE_ORIGINAL_ONLY:
            return WRITER_NOT_REQUESTED
        return WRITER_COMMITTED

    def _requested_expected(self) -> str:
        if self._reused is not None:
            return EXPECTED_REUSED
        if self.requested_mode == MODE_ORIGINAL_ONLY:
            return EXPECTED_ORIGINAL_CURRENT
        return EXPECTED_ALL_CURRENT

    def _requested_actual(self) -> str:
        if self._unknown:
            return ACTUAL_UNKNOWN
        if self._reused is not None:
            return EXPECTED_REUSED
        original = self._writers.get(ROLE_ORIGINAL, {}).get("result")
        if original != WRITER_COMMITTED:
            if self._stage == STAGE_TRANSCRIPTION:
                return ACTUAL_TRANSCRIPTION_FAILED
            if self._stage == STAGE_TRANSLATION:
                return ACTUAL_TRANSLATION_FAILED
            return ACTUAL_WRITE_FAILED
        if self.requested_mode == MODE_ORIGINAL_ONLY:
            return EXPECTED_ORIGINAL_CURRENT
        translated = self._writers.get(ROLE_TRANSLATED, {}).get("result")
        bilingual = self._writers.get(ROLE_BILINGUAL, {}).get("result")
        if translated == WRITER_COMMITTED and bilingual == WRITER_COMMITTED:
            return EXPECTED_ALL_CURRENT
        not_produced = (WRITER_PREVIOUS_KEPT, WRITER_ABSENT)
        if translated in not_produced and bilingual in not_produced:
            if translated == WRITER_PREVIOUS_KEPT and bilingual == WRITER_PREVIOUS_KEPT:
                return ACTUAL_PREVIOUS_TRANSLATIONS
            if WRITER_ABSENT in (translated, bilingual):
                if WRITER_PREVIOUS_KEPT in (translated, bilingual):
                    return ACTUAL_STALE_AND_MISSING
                return ACTUAL_MISSING_TRANSLATIONS
        if WRITER_PRESENCE_UNKNOWN in (translated, bilingual) and WRITER_FAILED not in (translated, bilingual):
            return ACTUAL_UNKNOWN
        return ACTUAL_PARTIAL

    def _publication_actual(self) -> str:
        if self._unknown:
            return ACTUAL_UNKNOWN
        if self._reused is not None:
            return EXPECTED_REUSED
        if self._aborted:
            # 本轮被异常中止：终态是失败，不是部分完成。
            if self._stage == STAGE_TRANSCRIPTION:
                return ACTUAL_TRANSCRIPTION_FAILED
            if self._stage == STAGE_TRANSLATION:
                return ACTUAL_TRANSLATION_FAILED
            # 写盘失败：已经提交了部分目标就是“部分提交”，一个都没提交才是
            # “写入失败”。两件不同的事，因此两个不同的终态词。
            if self._writers.get(ROLE_ORIGINAL, {}).get("result") == WRITER_COMMITTED:
                return PUBLISHED_PARTIAL
            return ACTUAL_WRITE_FAILED
        requested = self._requested_actual()
        if requested in (
            ACTUAL_TRANSCRIPTION_FAILED,
            ACTUAL_TRANSLATION_FAILED,
            ACTUAL_WRITE_FAILED,
        ):
            return requested
        if requested == self._requested_expected():
            return PUBLISHED_CURRENT
        if requested == ACTUAL_PARTIAL:
            # 提交了部分目标，另一个 writer 失败。
            return PUBLISHED_PARTIAL
        # 本轮没有产出译文：只剩上一版，或根本没有。
        return PUBLISHED_INCOMPLETE

    def _probe_writer_outputs(self) -> None:
        # Gather optional evidence only after the business timers have stopped.
        for role, path in self._writer_paths.items():
            present = _has_regular_file(path)
            entry = self._writers[role]
            if entry["result"] == WRITER_PRESENCE_UNKNOWN and present is not None:
                entry["result"] = WRITER_PREVIOUS_KEPT if present else WRITER_ABSENT
            if present:
                entry["sha256"], entry["bytes"] = _file_fingerprint(path)

    def _details_payload(
        self, phase: str, metrics: Optional[Mapping[str, Any]] = None
    ) -> Dict[str, Any]:
        """本仓自己的一条步骤日志：不含路径、逐字稿正文与凭证。"""
        payload: Dict[str, Any] = {
            "schema_version": DETAIL_SCHEMA,
            "phase": phase,
            "input_id": self.input_id,
            "step_id": self.step_id,
            "requested_mode": self.requested_mode,
            "force": self.force,
            "projection_version": ADAPTER_VERSION,
            "recorded_at": now(),
        }
        if phase == "finished":
            payload["engine_started"] = self._engine_started
            payload["writers"] = [
                self._writers[role] for role in ROLES if role in self._writers
            ]
            payload["errors"] = list(self._errors)
            payload["metrics"] = dict(metrics or {})
            payload["outcome"] = self._publication_actual()
            if self._reused is not None:
                payload["reused_outputs"] = dict(self._reused)
        return payload


def _has_regular_file(path: Path) -> Optional[bool]:
    try:
        return stat.S_ISREG(path.stat().st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return None


def _file_fingerprint(path: Path) -> Tuple[Optional[str], Optional[int]]:
    try:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size
    except OSError:
        return None, None


def begin_operation(
    *,
    audio_path: Any,
    translate_requested: bool,
    force: bool,
    environ: Optional[Mapping[str, str]] = None,
) -> OperationFeedback:
    """开始一次转录操作的反馈投影。

    没有启用旁路时返回一个空操作对象：调用方不需要为它写任何分支。
    旁路目的地不合法时同样返回空操作对象——旁路永远不能让主任务失败。
    """
    try:
        recorder = recorder_from_env(environ)
    except Exception as exc:  # 防御：投影永远不成为业务失败的原因
        logger.warning(f"反馈旁路不可用（不影响本次转录结果）: {type(exc).__name__}")
        recorder = None
    mode = MODE_TRANSLATED if translate_requested else MODE_ORIGINAL_ONLY
    input_id = ""
    if recorder is not None:
        try:
            input_id = input_identity(audio_path)
        except Exception:
            input_id = hashlib.sha256(str(audio_path).encode("utf-8", "replace")).hexdigest()[:12]
    return OperationFeedback(
        recorder,
        input_id=input_id,
        requested_mode=mode,
        force=force,
    )
