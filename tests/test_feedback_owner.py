import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest
from subprocess_support import fixture_environment, run_child

from core import transcribe_one
from engines.base import Segment, TranscriptionResult
from exceptions import TranslationError

OWNER = "meeting-converter"
CLI = Path(__file__).resolve().parents[1] / "feedback_owner.py"


def digest(value):
    body = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("ascii")).hexdigest()


def request(kind, scope, payload):
    key = digest([kind, OWNER, *scope])
    return {"schema_version": "feedback-action/1", "kind": kind, "owner": OWNER,
            "method": "lookup" if kind == "reconcile" else "submit", "action_id": key,
            "payload": payload, "request_digest": digest([OWNER, kind, key, payload])}


@pytest.fixture
def run_case(tmp_path, monkeypatch):
    sidecar = tmp_path / "original.jsonl"
    monkeypatch.setenv("RESEARCH_FEEDBACK_OUT", str(sidecar))
    monkeypatch.setenv("RESEARCH_FEEDBACK_RUN_ID", "f4-run")
    monkeypatch.setenv("RESEARCH_FEEDBACK_ATTEMPT_ID", "original-attempt")
    audio = tmp_path / "call.mp3"
    audio.write_bytes(b"synthetic audio")
    stale = tmp_path / "call_翻译.txt"
    stale.write_text("existing translated bytes", encoding="utf-8")
    engine = Mock()
    engine.transcribe.return_value = TranscriptionResult(
        language="en", language_probability=1, duration=2, segments=[Segment(0, 2, "Fixture text")],
    )
    translator = Mock(model="fixture")
    translator.translate_paragraphs.side_effect = TranslationError("synthetic provider error")
    transcribe_one(engine, audio, tmp_path, translator_obj=translator)
    rows = {row["check_id"]: dict(row, origin_owner=OWNER)
            for row in map(json.loads, sidecar.read_text(encoding="utf-8").splitlines())}
    original = rows["requested-outputs"]
    occurrence = digest([original[name] for name in
                         ("owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id")])
    db = tmp_path / "owner.sqlite"

    def call(kind, arg=None):
        argv = [sys.executable, "-B", "-X", "utf8", str(CLI), "--db", str(db), "--sidecar", str(sidecar), kind]
        body = None
        if isinstance(arg, dict):
            body = json.dumps(arg).encode("ascii")
        elif arg:
            argv.append(arg)
        env = {**fixture_environment(), "RESEARCH_FEEDBACK_STATE_ROOT": str(tmp_path / "diagnostics")}
        outcome = run_child(argv, input=body, env=env, capture_output=True, timeout=15, check=True)
        return json.loads(outcome.stdout)

    yield call, rows, occurrence, sidecar, db
    assert stale.read_text(encoding="utf-8") == "existing translated bytes"
    engine.transcribe.assert_called_once()
    translator.translate_paragraphs.assert_called_once()


@pytest.mark.e2e_offline
@pytest.mark.parametrize("layout", ("primary", "fallback", "unavailable"))
def test_bad_owner_request_has_local_trace_and_preserves_wire_result(tmp_path, layout):
    primary, fallback = tmp_path / "local-state", tmp_path / "feedback-inbox"
    if layout != "primary":
        primary.write_bytes(b"original primary blocker")
    if layout == "unavailable":
        fallback.write_bytes(b"original fallback blocker")
    env = fixture_environment()
    env.update(
        RESEARCH_FEEDBACK_STATE_ROOT=str(primary),
        RESEARCH_FEEDBACK_DIR=str(fallback),
        RESEARCH_FEEDBACK_RUN_ID="owner-native-run",
        RESEARCH_FEEDBACK_ATTEMPT_ID="owner-native-attempt",
    )
    db = tmp_path / "owner.sqlite"
    credential = b"synthetic-owner-bearer-value-for-local-test"
    request_body = b'{"payload":"Authorization: Bearer ' + credential
    result = run_child(
        [sys.executable, "-B", str(CLI), "--db", str(db), "reconcile"],
        cwd=tmp_path, input=request_body, env=env, capture_output=True, timeout=15,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"state": "unknown", "error_type": "JSONDecodeError"}
    assert credential not in result.stdout + result.stderr
    assert not db.exists()
    if layout == "unavailable":
        notice, = result.stderr.decode("utf-8").splitlines()
        assert "diagnostic_log_unavailable" in notice
        assert primary.read_bytes() == b"original primary blocker"
        assert fallback.read_bytes() == b"original fallback blocker"
        return
    assert result.stderr == b""
    root = primary if layout == "primary" else fallback
    recorded = (root / "logs" / "feedback-owner.jsonl").read_bytes()
    assert credential not in recorded
    rows = list(map(json.loads, recorded.splitlines()))
    fault, = [row for row in rows if row["phase"] == "error"]
    assert (fault["run_id"], fault["attempt_id"]) == ("owner-native-run", "owner-native-attempt")
    assert fault["error_type"] == "JSONDecodeError" and "feedback_owner.py" in fault["location"]


def test_native_repair_reuses_the_original_evidence_and_saves_one_report(run_case):
    call, rows, occurrence, _, _ = run_case
    observation = rows["requested-outputs"]
    triage = request("triage", [occurrence], {"occurrence_id": occurrence, "observation": observation})
    decision = call("triage", triage)["result"]
    assert decision["decision"] == "repair"
    issue, generation = decision["issue_ref"], decision["generation"]
    repair = request("repair", [issue, generation], {"issue_ref": issue, "generation": generation})
    assert call("get-publication", repair["action_id"]) == {}
    with ThreadPoolExecutor(2) as workers:
        first, second = list(workers.map(lambda _: call("repair", repair), range(2)))
    assert first == second
    fixed = first["result"]
    publication = call("get-publication", repair["action_id"])["publication"]
    assert fixed["fixed_version"].endswith("/" + digest(publication))
    assert set(publication["current"]) == {"original"}
    assert publication["retained"] == ["translated"]
    assert publication["missing"] == ["bilingual"]
    assert publication["publication_outcome"] == "published_incomplete"
    assert publication["occurrence_id"] == occurrence

    scope = [occurrence, OWNER, issue, fixed["fixed_version"]]
    replay = request("replay", scope, {"occurrence_id": occurrence, "original_occurrence_id": occurrence,
                                      "observation": observation, "issue_owner": OWNER, "issue_ref": issue,
                                      "fixed_version": fixed["fixed_version"], "acquisition": "reuse_only"})
    wrong_replay = request("replay", scope, dict(replay["payload"], original_occurrence_id="wrong"))
    assert call("replay", wrong_replay) == {"state": "unknown"}
    assert call("get-action", replay["action_id"]) == {}
    proof = call("replay", replay)["result"]
    assert proof["verdict"] == "verified"
    assert proof["verified_version"] == fixed["fixed_version"]
    body = {"occurrence_id": occurrence, "original_occurrence_id": occurrence, "origin_owner": OWNER,
            "fixed_version": fixed["fixed_version"], "issue_ref": issue, "verdict": "verified",
            "evidence_ref": proof["evidence_ref"]}
    report = request("report", [*scope, "verified"], body)
    wrong = request("report", [*scope, "verified"], dict(body, evidence_ref="different-replay"))
    assert call("report", wrong)["state"] == "unknown"
    assert call("report", report) == {"result": {"recorded": True}}
    assert call("report", report) == {"result": {"recorded": True}}
    assert call("get-action", report["action_id"]) == {"receipt": {"request": report, "result": {"recorded": True}}}


def test_unknown_reconciliation_reads_the_original_status_without_creating_state(run_case):
    call, rows, _, sidecar, db = run_case
    observation = rows["action-started"]
    key = digest([observation[name] for name in
                  ("owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id")])
    lookup = request("reconcile", [key], {"occurrence_id": key, "observation": observation})
    outcome = call("reconcile", lookup)
    assert outcome["result"]["job_status"] == "succeeded"
    assert outcome["result"]["cost_state"] == "unknown"
    incomplete = json.dumps({k: v for k, v in observation.items() if k != "origin_owner"})
    sidecar.write_text(incomplete + "\n", encoding="utf-8")
    outcome = call("reconcile", lookup)
    assert outcome["result"]["job_status"] == "unconfirmed"
    assert outcome["result"]["cost_state"] == "unknown"
    assert not db.exists()


def test_tampered_detail_and_same_audio_wrong_invocation_cannot_schedule_repair(run_case):
    call, rows, occurrence, sidecar, _ = run_case
    original = rows["requested-outputs"]
    wrong = dict(original, step_id=original["step_id"] + "-wrong")
    other = digest([wrong[name] for name in
                    ("owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id")])
    result = call("triage", request("triage", [other], {"occurrence_id": other, "observation": wrong}))
    assert result == {"result": {"decision": "needs_evidence"}}
    detail = sidecar.with_name(sidecar.name + ".details.jsonl")
    value = detail.read_text(encoding="utf-8").replace("published_incomplete", "published_current")
    detail.write_text(value, encoding="utf-8")
    result = call("triage", request("triage", [occurrence], {"occurrence_id": occurrence, "observation": original}))
    assert result == {"result": {"decision": "needs_evidence"}}


@pytest.mark.parametrize("field, value", [
    ("schema_version", "another/1"), ("evidence_ref", "mc-output/0123456789ab"), ("version", "old"),
    ("actual", {"invalid": "object"}),
])
def test_incompatible_terminal_cannot_confirm_the_original_job(run_case, field, value):
    call, rows, _, sidecar, db = run_case
    observation = rows["action-started"]
    key = digest([observation[name] for name in
                  ("owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id")])
    lookup = request("reconcile", [key], {"occurrence_id": key, "observation": observation})
    rows["publication-outcome"][field] = value
    sidecar.write_text("".join(json.dumps(row) + "\n" for row in rows.values()), encoding="utf-8")
    result = call("reconcile", lookup)["result"]
    assert result["job_status"] == "unconfirmed"
    assert result["cost_state"] == "unknown"
    assert not db.exists()


def test_degraded_publication_reconciles_as_a_delivered_job(tmp_path):
    """成功回退（published_degraded）是已交付的作业；降级信号由 deviation 承载。"""
    sidecar = tmp_path / "degraded.jsonl"
    row = {
        "schema_version": "feedback-observation/1", "owner": OWNER, "origin_owner": OWNER,
        "run_id": "f4-run", "attempt_id": "attempt-1", "step_id": "meeting-operation/x/1",
        "check_id": "publication-outcome", "expected": "published_current",
        "actual": "published_degraded", "disposition": "deviation",
        "evidence_ref": "mc-output/x", "version": "meeting-converter-feedback/1.1.0",
    }
    sidecar.write_text(json.dumps(row) + "\n", encoding="utf-8")
    occurrence = digest([row[name] for name in
                         ("owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id")])
    lookup = request("reconcile", [occurrence], {"occurrence_id": occurrence, "observation": row})
    outcome = run_child(
        [sys.executable, "-B", "-X", "utf8", str(CLI), "--db", str(tmp_path / "owner.sqlite"),
         "--sidecar", str(sidecar), "reconcile"],
        input=json.dumps(lookup).encode("ascii"), capture_output=True, timeout=15, check=True,
    )
    result = json.loads(outcome.stdout)
    assert result["state"] == "done"
    assert result["result"]["job_status"] == "succeeded"
    assert result["result"]["cost_state"] == "unknown"
    assert not (tmp_path / "owner.sqlite").exists(), "reconcile 全程只读"
