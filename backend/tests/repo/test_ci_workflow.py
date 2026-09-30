from pathlib import Path
from typing import Any

import pytest
import yaml


@pytest.fixture
def workflow(repo_root: Path) -> dict[Any, Any]:
    return yaml.safe_load((repo_root / ".github" / "workflows" / "docker.yml").read_text())


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 parses the bare key `on` as the boolean True.
    return workflow.get("on", workflow.get(True))


def _run_lines(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_triggers_are_pull_request_main_and_dispatch(workflow: dict[Any, Any]) -> None:
    """CI never publishes, so a release tag and a weekly cron would only burn minutes."""
    triggers = _triggers(workflow)

    assert set(triggers) == {"pull_request", "push", "workflow_dispatch"}
    assert triggers["pull_request"]["branches"] == ["main"]
    # Feature-branch pushes are covered by their PR; only main runs on push.
    assert triggers["push"]["branches"] == ["main"]
    # A tag push would re-check a commit its PR already checked, and publish nothing.
    assert "tags" not in triggers["push"]


def test_defines_backend_frontend_image_jobs(workflow: dict[Any, Any]) -> None:
    jobs = workflow["jobs"]

    backend = _run_lines(jobs["backend"])
    for command in ("ruff check", "ruff format --check", "ty check app", "pytest", "alembic check"):
        assert command in backend
    frontend = _run_lines(jobs["frontend"])
    for script in ("run lint", "run typecheck", "test -- --run", "run build"):
        assert script in frontend
    image = jobs["image"]
    build = next(s for s in image["steps"] if s.get("name") == "Build (linux/amd64)")
    assert build["with"]["platforms"] == "linux/amd64"
    assert "scripts/test-image.sh" in _run_lines(image)


def test_ci_never_publishes(workflow: dict[Any, Any]) -> None:
    """scripts/publish.sh is the only publisher, so nothing here logs in, reads image metadata,
    pushes, or so much as mentions a Docker Hub credential."""
    raw = (Path(__file__).resolve().parents[3] / ".github" / "workflows" / "docker.yml").read_text()
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]

    for step in steps:
        uses = step.get("uses", "")
        assert not uses.startswith(("docker/login-action", "docker/metadata-action")), uses
        assert step.get("with", {}).get("push") is not True, step.get("name")
    # No gated-off remnants either: a disabled push step is still a credential reference.
    assert "DOCKERHUB" not in raw
    assert "secrets." not in raw


def test_image_job_builds_and_checks_on_pull_requests(workflow: dict[Any, Any]) -> None:
    """CI cannot publish a broken image, but it must still catch a broken Dockerfile before a
    hand-rolled publish does, so the job runs unconditionally."""
    image = workflow["jobs"]["image"]

    assert "if" not in image
    assert "if" not in workflow["jobs"]["backend"]
    assert "if" not in workflow["jobs"]["frontend"]
    # The two things a PR has to exercise: the amd64 build and the image checks.
    build = next(step for step in image["steps"] if step.get("name") == "Build (linux/amd64)")
    assert build["with"]["platforms"] == "linux/amd64"
    assert "scripts/test-image.sh" in _run_lines(image)


def test_only_the_three_test_and_build_jobs_remain(workflow: dict[Any, Any]) -> None:
    """The weekly rebuild job went with the publishing it existed to do."""
    assert set(workflow["jobs"]) == {"backend", "frontend", "image"}


# First major of each action that runs on Node 24 (Node 20 actions are deprecated on runners).
NODE24_MIN_MAJOR = {
    "actions/checkout": 5,
    "actions/setup-node": 5,
    "astral-sh/setup-uv": 7,
    "docker/setup-buildx-action": 4,
    "docker/build-push-action": 7,
}


def test_actions_run_on_node24_and_runner_is_pinned(workflow: dict[Any, Any]) -> None:
    jobs = workflow["jobs"].values()
    uses = [step["uses"] for job in jobs for step in job["steps"] if "uses" in step]

    outdated = []
    for ref in uses:
        action, version = ref.split("@")
        major = int(version.removeprefix("v").split(".")[0])
        if major < NODE24_MIN_MAJOR[action]:
            outdated.append(ref)
    assert outdated == []
    assert {job["runs-on"] for job in jobs} == {"ubuntu-24.04"}


def test_backend_job_installs_ffmpeg(workflow: dict[Any, Any]) -> None:
    steps = workflow["jobs"]["backend"]["steps"]
    runs = [step.get("run", "") for step in steps]
    install = next(i for i, run in enumerate(runs) if "apt-get install" in run and "ffmpeg" in run)
    tests = next(i for i, run in enumerate(runs) if "pytest" in run)

    assert install < tests
