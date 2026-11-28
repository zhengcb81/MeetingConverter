"""Exercise the journal through owner commands and the real library entry point."""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from subprocess_support import fixture_environment, run_child
from test_feedback_owner import request, digest

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "feedback_owner.py"


def _owner(tmp_path, run_id):
    env = {**fixture_environment(),
           "RESEARCH_FEEDBACK_STATE_ROOT": str(tmp_path),
           "RESEARCH_FEEDBACK_RUN_ID": run_id,
           "RESEARCH_FEEDBACK_ATTEMPT_ID": "original-attempt"}
    return run_child(
        [sys.executable, "-B", str(OWNER), "--db", str(tmp_path / "owner.sqlite"), "reconcile"],
        input=b"{", env=env, cwd=tmp_path, capture_output=True, timeout=20,
    )


@pytest.mark.e2e_offline
def test_concurrent_owner_invocations_keep_rows_during_rotation(tmp_path):
    current = tmp_path / "logs" / "feedback-owner.jsonl"
    current.parent.mkdir()
    first_backup = current.with_suffix(".jsonl.1")
    old = b'{"phase":"old"}\n' * 76_000
    previous = b'{"phase":"previous"}\n'
    current.write_bytes(old)
    first_backup.write_bytes(previous)
    with first_backup.open("rb"):
        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(lambda run: _owner(tmp_path, run), ("run-a", "run-b")))
        if os.name == "nt":
            assert first_backup.read_bytes() == previous
    outcomes.append(_owner(tmp_path, "run-c"))
    assert all(result.returncode == 2 and len(result.stdout.splitlines()) == 1 for result in outcomes)
    assert all(not result.stderr for result in outcomes)
    assert first_backup.read_bytes() == old
    assert current.with_suffix(".jsonl.2").read_bytes() == previous
    rows = [json.loads(line) for line in current.read_bytes().splitlines()]
    assert len(rows) == 9
    for run in ("run-a", "run-b", "run-c"):
        assert [row["phase"] for row in rows if row["run_id"] == run] == ["started", "error", "exited"]


@pytest.mark.e2e_offline
def test_existing_original_is_cold_readable_when_called_as_a_library(tmp_path):
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"local audio placeholder kept for the reuse path")
    original = tmp_path / "call_原文.txt"
    original.write_text("Previously published.", encoding="utf-8")
    env = {**fixture_environment(),
           "PYTHONPATH": str(ROOT),
           "RESEARCH_FEEDBACK_STATE_ROOT": str(tmp_path / "state"),
           "RESEARCH_FEEDBACK_RUN_ID": "library-run",
           "RESEARCH_FEEDBACK_ATTEMPT_ID": "library-original"}
    source = (
        "from core import transcribe_one; from pathlib import Path; "
        "assert transcribe_one(None, Path('call.wav'), Path.cwd()) is None"
    )
    result = run_child(
        [sys.executable, "-B", "-c", source], env=env,
        cwd=tmp_path, capture_output=True, timeout=20,
    )
    assert result.returncode == 0 and not result.stdout
    assert original.read_text(encoding="utf-8") == "Previously published."
    journal = tmp_path / "state" / "logs" / "library.jsonl"
    file_rows = [row for row in map(json.loads, journal.read_bytes().splitlines()) if row["stage"] == "file"]
    assert [row["phase"] for row in file_rows] == ["started", "reused"]
    assert all(row["run_id"] == "library-run" and row["attempt_id"] == "library-original" for row in file_rows)
    assert file_rows[0]["step_id"] == file_rows[-1]["step_id"]

@pytest.mark.e2e_offline
@pytest.mark.parametrize(("script", "args", "exit_code", "journal", "phase"), [
    ("company_manager.py", ["show", "synthetic-company-not-in-catalog"], 0, "company-manager", "refused"),
    ("compare_engines.py", [], 1, "compare-engines", "error"),
])
def test_existing_auxiliary_entry_preserves_wire_and_records_refusal(
    tmp_path, script, args, exit_code, journal, phase,
):
    env = {**fixture_environment(), "RESEARCH_FEEDBACK_STATE_ROOT": str(tmp_path)}
    process = run_child(
        [sys.executable, "-B", str(ROOT / script), *args], cwd=tmp_path,
        env=env, capture_output=True, timeout=20,
    )
    assert process.returncode == exit_code
    assert process.stdout and not process.stderr
    rows = list(map(json.loads, (tmp_path / "logs" / (journal + ".jsonl")).read_bytes().splitlines()))
    assert [row["phase"] for row in rows] == ["started", phase, "exited"]
    assert "synthetic-company-not-in-catalog" not in json.dumps(rows)


@pytest.mark.e2e_offline
def test_safe_run_coordinates_bind_native_log_and_existing_observation_without_extra_calls(tmp_path):
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"fixture audio")
    original = tmp_path / "call_原文.txt"
    original.write_text("Original published bytes.", encoding="utf-8")
    old = original.read_bytes()
    observations = tmp_path / "observations.jsonl"
    password = "synthetic-url-secret-block"
    token = "synthetic-folded-bearer-secret"
    env = {
        **fixture_environment(), "PYTHONPATH": str(ROOT),
        "RESEARCH_FEEDBACK_STATE_ROOT": str(tmp_path / "state"),
        "RESEARCH_FEEDBACK_OUT": str(observations),
        "RESEARCH_FEEDBACK_RUN_ID": f"HTTP 403-https://user:{password}@local.invalid/path",
        "RESEARCH_FEEDBACK_ATTEMPT_ID": f"Authorization:\r\n Bearer\r\n {token}",
    }
    run = run_child(
        [sys.executable, "-B", "-c",
         "from core import transcribe_one; from pathlib import Path;"
         "transcribe_one(None, Path('call.wav'), Path.cwd())"],
        cwd=tmp_path, env=env, capture_output=True, timeout=20,
    )
    assert run.returncode == 0 and not run.stdout
    source = observations.read_bytes()
    snapshot = (tmp_path / "state" / "logs" / "library.jsonl").read_bytes()
    for secret in (password, token):
        assert secret.encode() not in source + snapshot + run.stdout + run.stderr
    file, = [row for row in map(json.loads, snapshot.splitlines()) if row["phase"] == "reused"]
    observation, = [row for row in map(json.loads, source.splitlines()) if row["check_id"] == "action-started"]
    for key in ("run_id", "attempt_id", "step_id"):
        assert file[key] == observation[key]
    assert file["run_id"].startswith("redacted-") and file["attempt_id"].startswith("redacted-")
    envelope = {**observation, "origin_owner": "meeting-converter"}
    lookup = run_child(
        [sys.executable, "-B", str(OWNER), "--db", str(tmp_path / "owner.sqlite"),
         "--sidecar", str(observations), "reconcile"],
        cwd=tmp_path, env=env, capture_output=True, timeout=20,
        input=json.dumps(_lookup_request(envelope)).encode("utf-8"),
    )
    assert lookup.returncode == 0 and not lookup.stderr
    result = json.loads(lookup.stdout)
    assert result["state"] == "done"
    assert result["result"]["job_status"] == "succeeded" and result["result"]["cost_state"] == "unknown"
    assert result["result"]["step_id"] == file["step_id"]
    assert observations.read_bytes() == source and original.read_bytes() == old

def _lookup_request(observation):
    keys = ("owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id")
    occurrence = digest([observation[field] for field in keys])
    return request("reconcile", [occurrence], {"occurrence_id": occurrence, "observation": observation})
