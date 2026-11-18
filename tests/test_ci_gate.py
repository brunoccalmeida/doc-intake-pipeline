"""The CI gate: the single required check of the CI workflow.

The ruleset requires one job with a fixed name, ``ci-passed``, that depends on
every other job. A skipped required check counts as passed, so the gate must
run even when a dependency fails (``if: always()``) and approve only when every
dependency explicitly succeeded (allowlist): failure, cancelled and skipped all
fail it. These tests read the workflow file, so a new job left out of the
gate's ``needs`` fails the test suite before it can weaken the gate.
"""

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from scripts.check_needs import main, unsuccessful_jobs

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
SECURITY = WORKFLOWS / "security.yml"
GATE = "ci-passed"

type Job = dict[str, Any]


def _load(path: Path) -> dict[Any, Any]:
    return cast("dict[Any, Any]", yaml.safe_load(path.read_text(encoding="utf-8")))


def _jobs(path: Path) -> dict[str, Job]:
    return cast("dict[str, Job]", _load(path)["jobs"])


def _triggers(path: Path) -> set[str]:
    """Event names of a workflow (PyYAML reads the ``on:`` key as True)."""
    return set(cast("dict[str, Any]", _load(path)[True]))


JOBS = _jobs(CI)


class TestGateJob:
    """The workflow exposes one stable required check that sees every job."""

    def test_gate_job_exists(self) -> None:
        assert GATE in JOBS, f"{CI.name} has no '{GATE}' job"

    def test_gate_has_no_matrix_or_custom_name(self) -> None:
        """Either would change the check name the ruleset requires."""
        assert "strategy" not in JOBS[GATE]
        assert "name" not in JOBS[GATE]

    def test_gate_runs_even_when_a_dependency_fails(self) -> None:
        """Without always() a failed dependency skips the gate, which passes."""
        assert JOBS[GATE].get("if") == "${{ always() }}"

    def test_gate_needs_every_other_job(self) -> None:
        assert set(JOBS[GATE].get("needs", [])) == set(JOBS) - {GATE}

    def test_gate_checks_the_result_of_every_dependency(self) -> None:
        steps = cast("list[dict[str, Any]]", JOBS[GATE].get("steps", []))
        checker = [s for s in steps if s.get("run") == "python3 scripts/check_needs.py"]
        assert checker, "gate does not run scripts/check_needs.py"
        assert checker[0].get("env", {}).get("NEEDS") == "${{ toJSON(needs) }}"


class TestWorkflowHygiene:
    """Rules zizmor does not enforce."""

    @pytest.mark.parametrize("path", [CI, SECURITY], ids=lambda p: p.name)
    def test_every_job_has_a_timeout(self, path: Path) -> None:
        """A hung job otherwise burns the 6 h default and blocks the queue.

        A job that calls a reusable workflow cannot set one; the called
        workflow's jobs carry their own.
        """
        missing = [
            job_id
            for job_id, job in _jobs(path).items()
            if "uses" not in job and "timeout-minutes" not in job
        ]
        assert missing == []


class TestDependencyAuditInGate:
    """The audit is a dependency of the gate, not a separate required check.

    /mission:ship-pr waits only for the ``gate`` check; inside ``needs`` a
    failed audit fails ``ci-passed`` at once. The audit lives in one reusable
    workflow, so the daily run and the gate run the same steps.
    """

    def test_gate_calls_the_security_workflow(self) -> None:
        callers = {
            job_id
            for job_id, job in JOBS.items()
            # $/: GitHub's self-repository syntax (same commit as the caller),
            # not "./", which resolves against the runtime filesystem
            if job.get("uses") == "$/.github/workflows/security.yml"
        }
        assert callers, f"no job of {CI.name} calls security.yml"
        assert callers <= set(JOBS[GATE]["needs"])

    def test_security_workflow_is_reusable_and_daily(self) -> None:
        assert {"workflow_call", "schedule"} <= _triggers(SECURITY)

    @pytest.mark.parametrize("event", ["pull_request", "push"])
    def test_audit_runs_once_per_change(self, event: str) -> None:
        """The gate already runs it on pull requests and pushes."""
        assert event not in _triggers(SECURITY)


def _needs(**results: str) -> dict[str, dict[str, Any]]:
    """Build the shape of ``toJSON(needs)``: {job: {result, outputs}}."""
    return {job: {"result": result, "outputs": {}} for job, result in results.items()}


class TestUnsuccessfulJobs:
    """Only an explicit "success" counts; anything else blocks the merge."""

    def test_all_successful(self) -> None:
        assert unsuccessful_jobs(_needs(check="success", test="success")) == []

    @pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", ""])
    def test_any_other_result_is_unsuccessful(self, result: str) -> None:
        needs = _needs(check="success", test=result)
        assert unsuccessful_jobs(needs) == [f"test: {result}"]

    def test_missing_result_is_unsuccessful(self) -> None:
        assert unsuccessful_jobs({"test": {}}) == ["test: None"]


class TestMain:
    def test_passes_when_every_job_succeeded(self, capsys: pytest.CaptureFixture[str]) -> None:
        env = {"NEEDS": '{"check": {"result": "success"}, "test": {"result": "success"}}'}
        assert main(env) == 0
        assert "all 2 required jobs succeeded" in capsys.readouterr().out

    def test_fails_and_names_the_job(self, capsys: pytest.CaptureFixture[str]) -> None:
        env = {"NEEDS": '{"check": {"result": "success"}, "test": {"result": "failure"}}'}
        assert main(env) == 1
        assert "test: failure" in capsys.readouterr().err

    @pytest.mark.parametrize("env", [{}, {"NEEDS": ""}, {"NEEDS": "{}"}])
    def test_fails_when_there_is_nothing_to_check(self, env: dict[str, str]) -> None:
        """An empty gate checked nothing; passing it would be a silent pass."""
        assert main(env) == 1
