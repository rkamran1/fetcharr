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


def test_triggers_are_pull_requests_and_pushes_to_main(workflow: dict[Any, Any]) -> None:
    triggers = _triggers(workflow)

    assert set(triggers) == {"pull_request", "push"}
    assert triggers["pull_request"]["branches"] == ["main"]
    # Feature-branch pushes are covered by their PR; only main runs on push.
    assert triggers["push"]["branches"] == ["main"]


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
