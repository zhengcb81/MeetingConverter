"""MeetingConverter CI must discover and execute the owner suites on both platforms."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
POLICY = ROOT / "tests/contract/test_policy.json"


def _workflow():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_mainline_and_pr_workflows_share_the_same_job():
    definition = _workflow()
    triggers = definition.get("on", definition.get(True))
    assert isinstance(triggers, dict)
    assert set(triggers["push"]["branches"]) == {"master", "main"}
    assert set(triggers["pull_request"]["branches"]) == {"master", "main"}
    assert "workflow_dispatch" in triggers


def test_native_platforms_use_the_policy_and_exact_checkout():
    job = _workflow()["jobs"]["test"]
    policy = json.loads(POLICY.read_bytes())["platforms"]
    rows = job["strategy"]["matrix"]["include"]
    assert {(row["runner"], row["platform"], row["marks"]) for row in rows} == {
        ("ubuntu-latest", "linux", policy["linux"]["markexpr"]),
        ("windows-latest", "windows", policy["windows"]["markexpr"]),
    }
    checkout, = (step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ env.S6_REVISION }}"
    assert job["env"]["S6_REVISION"] == "${{ github.event.pull_request.head.sha || github.sha }}"
    assert 0 < job["timeout-minutes"] <= 15


def test_actual_discovery_and_execution_are_both_mandatory():
    job = _workflow()["jobs"]["test"]
    steps = job["steps"]
    assert not job.get("continue-on-error")
    pytest_steps = [step for step in steps if "python -m pytest " in step.get("run", "")]
    assert len(pytest_steps) == 2
    collect, run = pytest_steps
    assert "--collect-only" in collect["run"] and "--collect-only" not in run["run"]
    for step in pytest_steps:
        assert not step.get("if") and not step.get("continue-on-error")
        command = step["run"]
        assert command.endswith("tests/")
        assert '--s6-revision "$S6_REVISION"' in command
        assert '-m "$S6_MARKS"' in command
        assert "--cov=" not in command
    coverage, = (step for step in steps if "anti_trick_gate_spec coverage" in step.get("run", ""))
    assert not coverage.get("if") and not coverage.get("continue-on-error")
    assert "s6-collected.json s6-executed.json" in coverage["run"]
    assert steps.index(coverage) > steps.index(run)
