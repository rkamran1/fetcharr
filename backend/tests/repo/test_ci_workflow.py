from pathlib import Path
from typing import Any

import pytest
import yaml

GATE = "vars.DOCKERHUB_PUSH_ENABLED == 'true'"


@pytest.fixture
def workflow(repo_root: Path) -> dict[Any, Any]:
    return yaml.safe_load((repo_root / ".github" / "workflows" / "docker.yml").read_text())


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 parses the bare key `on` as the boolean True.
    return workflow.get("on", workflow.get(True))


def _run_lines(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_triggers_include_release_tags_a_weekly_schedule_and_dispatch(
    workflow: dict[Any, Any],
) -> None:
    triggers = _triggers(workflow)

    assert set(triggers) == {"pull_request", "push", "schedule", "workflow_dispatch"}
    assert triggers["pull_request"]["branches"] == ["main"]
    # Feature-branch pushes are covered by their PR; only main runs on push.
    assert triggers["push"]["branches"] == ["main"]
    # A release tag publishes the semver tags; the weekly run rebuilds the newest of them.
    assert triggers["push"]["tags"] == ["v*.*.*"]
    assert [entry["cron"] for entry in triggers["schedule"]]


def test_weekly_job_rebuilds_the_latest_release_tag(workflow: dict[Any, Any]) -> None:
    weekly = workflow["jobs"]["weekly"]

    assert "schedule" in weekly["if"]
    assert weekly["needs"] == ["backend", "frontend"]
    resolve = next(step for step in weekly["steps"] if step.get("id") == "release")
    assert "git tag --list 'v*.*.*'" in resolve["run"]
    assert "git checkout --detach" in resolve["run"]


def test_weekly_job_publishes_latest(workflow: dict[Any, Any]) -> None:
    weekly = workflow["jobs"]["weekly"]
    meta = next(step for step in weekly["steps"] if step.get("id") == "meta")
    push = next(step for step in weekly["steps"] if step.get("with", {}).get("push") is True)

    assert "type=raw,value=latest" in meta["with"]["tags"]
    assert GATE in push["if"]
    # Nothing is built when there is no release tag to rebuild.
    assert "steps.release.outputs.tag != ''" in push["if"]


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


def test_dockerhub_steps_gated_by_repo_variable(workflow: dict[Any, Any]) -> None:
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    publishing = [
        step
        for step in steps
        if step.get("uses", "").startswith("docker/login-action")
        or step.get("with", {}).get("push") is True
    ]

    assert len(publishing) >= 2
    assert all(GATE in step.get("if", "") for step in publishing)


def test_image_job_builds_and_checks_on_pull_requests(workflow: dict[Any, Any]) -> None:
    """CI never publishes (D1: the owner publishes from their Mac), but it must still catch a
    broken Dockerfile before a hand-rolled publish, so the job runs unconditionally."""
    image = workflow["jobs"]["image"]

    assert "if" not in image
    assert "if" not in workflow["jobs"]["backend"]
    assert "if" not in workflow["jobs"]["frontend"]
    # The two things a PR has to exercise: the amd64 build and the image checks.
    build = next(step for step in image["steps"] if step.get("name") == "Build (linux/amd64)")
    assert build["with"]["platforms"] == "linux/amd64"
    assert "scripts/test-image.sh" in _run_lines(image)


def test_publishing_steps_only_run_on_push(workflow: dict[Any, Any]) -> None:
    """A pull request builds; only a push to main or a tag could ever publish."""
    for step in workflow["jobs"]["image"]["steps"]:
        if step.get("uses", "").startswith("docker/login-action") or step.get("id") == "meta":
            assert "github.event_name == 'push'" in step["if"], step.get("name")


def test_image_name_comes_from_the_repo_variable(workflow: dict[Any, Any]) -> None:
    """One name for the Docker Hub repo across the workflow and scripts/publish.sh."""
    raw = (Path(__file__).resolve().parents[3] / ".github" / "workflows" / "docker.yml").read_text()
    metadata = [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("docker/metadata-action")
    ]

    assert len(metadata) == 2
    for step in metadata:
        assert step["with"]["images"] == "docker.io/${{ vars.DOCKERHUB_REPO }}"
    assert "DOCKERHUB_IMAGE" not in raw


# First major of each action that runs on Node 24 (Node 20 actions are deprecated on runners).
NODE24_MIN_MAJOR = {
    "actions/checkout": 5,
    "actions/setup-node": 5,
    "astral-sh/setup-uv": 7,
    "docker/setup-buildx-action": 4,
    "docker/build-push-action": 7,
    "docker/login-action": 4,
    "docker/metadata-action": 6,
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
