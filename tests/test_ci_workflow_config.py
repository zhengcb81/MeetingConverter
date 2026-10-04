"""CI workflow 合同测试：静态校验 .github/workflows/ci.yml 满足快速可靠门约束。"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"

PYTHON_VERSION = "3.13"

ALLOWED_ACTIONS = ("actions/checkout", "actions/setup-python")


def _load() -> dict:
    data = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "workflow YAML must parse to a mapping"
    return data


def _on(data: dict) -> dict:
    triggers = data.get("on", data.get(True))
    assert isinstance(triggers, dict), "workflow must declare on: triggers"
    return triggers


def _job() -> dict:
    jobs = _load().get("jobs")
    assert isinstance(jobs, dict) and jobs, "workflow must define jobs"
    assert len(jobs) == 1, f"expected exactly one job, got {list(jobs)}"
    job = next(iter(jobs.values()))
    assert job.get("runs-on"), "job must declare runs-on"
    return job


def _steps(job: dict) -> list:
    steps = job.get("steps")
    assert isinstance(steps, list) and steps, "job must declare steps"
    return steps


def _step_uses(steps: list, prefix: str) -> list:
    return [s for s in steps if str(s.get("uses", "")).startswith(prefix)]


def _step_runs(steps: list, needle: str) -> list:
    return [s for s in steps if needle in str(s.get("run", ""))]


def _covers(config, branch: str) -> bool:
    branches = config.get("branches")
    if branches is None:
        return True
    return branch in branches or "**" in branches


def test_workflow_yaml_parses() -> None:
    data = _load()
    assert data.get("name")
    assert _on(data)


def test_push_runs_on_every_branch() -> None:
    on = _on(_load())
    assert "push" in on, "missing trigger: push"
    config = on.get("push") or {}
    assert _covers(config, "master"), "push must cover the mainline"
    assert _covers(config, "feature/example"), "push must cover feature branches"


def test_pull_request_targets_mainline() -> None:
    on = _on(_load())
    assert "pull_request" in on, "missing trigger: pull_request"
    config = on.get("pull_request") or {}
    assert _covers(config, "master") and _covers(config, "main")


def test_single_job_without_matrix() -> None:
    job = _job()
    strategy = job.get("strategy") or {}
    assert "matrix" not in strategy, "single Python version only; no matrix"


def test_single_pinned_python_version() -> None:
    steps = _steps(_job())
    setup = _step_uses(steps, "actions/setup-python")
    assert len(setup) == 1, "exactly one setup-python step"
    assert setup[0].get("with", {}).get("python-version") == PYTHON_VERSION


def test_pytest_runs_explicit_selector_without_full_repo_coverage() -> None:
    steps = _steps(_job())
    matches = _step_runs(steps, "pytest")
    assert len(matches) == 1, "exactly one pytest step"
    step = matches[0]
    run = str(step.get("run", ""))
    assert "tests/" in run, "pytest must target an explicit test selector"
    assert "--cov=." not in run, "full-repo coverage must not gate every push"
    assert "if" not in step, "the test step must never be skipped"
    assert not step.get("continue-on-error"), "test failures must fail the job"


def test_no_failure_masking() -> None:
    job = _job()
    assert not job.get("continue-on-error"), "job must not mask failures"
    for step in _steps(job):
        assert not step.get("continue-on-error"), "step must not mask failures"
        expression = str(step.get("if", ""))
        assert "always(" not in expression, f"always() masks failures: {expression}"


def test_if_expressions_use_single_quoted_literals_only() -> None:
    job = _job()
    expressions = [str(job.get("if", ""))]
    expressions += [str(step.get("if", "")) for step in _steps(job)]
    for expression in expressions:
        assert '"' not in expression, f"double-quoted literal breaks Actions: {expression}"


def test_only_allowlisted_setup_actions() -> None:
    for step in _steps(_job()):
        uses = step.get("uses")
        if uses is None:
            continue
        assert str(uses).startswith(ALLOWED_ACTIONS), f"unexpected action: {uses}"


def test_job_timeout_is_bounded() -> None:
    timeout = _job().get("timeout-minutes")
    assert isinstance(timeout, int) and 0 < timeout <= 5, f"bad timeout: {timeout}"
