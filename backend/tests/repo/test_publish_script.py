"""scripts/publish.sh is the only thing that publishes the image (§13.3), so its tag derivation
and its refusals are asserted here. Every run uses --dry-run inside a throwaway git repo: no
Docker, no network, and the head sha is one this test made."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = "example/fetcharr"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@dataclass(frozen=True)
class Publisher:
    """A clean one-commit git repo holding a copy of the script, and a way to run it."""

    path: Path

    def run(self, *args: str, repo: str | None = REPO) -> subprocess.CompletedProcess[str]:
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(self.path)}
        if repo is not None:
            env["DOCKERHUB_REPO"] = repo
        return subprocess.run(
            ["scripts/publish.sh", *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def git(self, *args: str) -> str:
        return _git(self.path, *args)

    def image_refs(self, stdout: str) -> list[str]:
        return [line for line in stdout.splitlines() if line.startswith("docker.io/")]


@pytest.fixture
def publish(repo_root: Path, tmp_path: Path) -> Publisher:
    script = tmp_path / "scripts" / "publish.sh"
    script.parent.mkdir()
    script.write_bytes((repo_root / "scripts" / "publish.sh").read_bytes())
    script.chmod(0o755)

    _git(tmp_path, "init", "-b", "main")
    # Set locally so the test works on a machine with no global git identity.
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "add", "scripts/publish.sh")
    _git(tmp_path, "commit", "-m", "initial")

    return Publisher(tmp_path)


def test_edge_resolves_edge_and_sha_tags(publish: Publisher) -> None:
    result = publish.run("edge", "--dry-run")

    assert result.returncode == 0, result.stderr
    short = publish.git("rev-parse", "--short", "HEAD")
    assert publish.image_refs(result.stdout) == [
        f"docker.io/{REPO}:edge",
        f"docker.io/{REPO}:sha-{short}",
    ]
    # The footer shows APP_VERSION, so an edge image must say `edge`, not a version number.
    assert "APP_VERSION=edge" in result.stdout.splitlines()


def test_release_resolves_the_semver_ladder_and_latest(publish: Publisher) -> None:
    publish.git("tag", "v0.1.0")

    result = publish.run("v0.1.0", "--dry-run")

    assert result.returncode == 0, result.stderr
    # Exactly the §13.3 release tags, and no sha- tag: a release is named by its version.
    assert publish.image_refs(result.stdout) == [
        f"docker.io/{REPO}:0.1.0",
        f"docker.io/{REPO}:0.1",
        f"docker.io/{REPO}:0",
        f"docker.io/{REPO}:latest",
    ]
    assert "APP_VERSION=0.1.0" in result.stdout.splitlines()


def test_builds_amd64_and_pushes_with_build_args(publish: Publisher) -> None:
    result = publish.run("edge", "--dry-run")

    assert result.returncode == 0, result.stderr
    argv = result.stdout.splitlines()
    assert argv[:3] == ["docker", "buildx", "build"]
    # Without --platform, Apple Silicon builds an arm64 image the Intel server cannot run (§13.3).
    assert argv[3:5] == ["--platform", "linux/amd64"]
    assert "--push" in argv
    assert f"VCS_REF={publish.git('rev-parse', 'HEAD')}" in argv


def test_refuses_a_dirty_working_tree(publish: Publisher) -> None:
    (publish.path / "untracked.txt").write_text("work in progress\n")

    result = publish.run("edge", "--dry-run")

    assert result.returncode != 0
    assert "dirty" in result.stderr
    # Nothing was resolved, so there is no command a copy-paste could run by accident.
    assert publish.image_refs(result.stdout) == []


def test_refuses_without_a_repo_or_with_a_bad_ref(publish: Publisher) -> None:
    missing_repo = publish.run("edge", "--dry-run", repo=None)
    assert missing_repo.returncode != 0
    assert "DOCKERHUB_REPO" in missing_repo.stderr

    bad_ref = publish.run("release-1", "--dry-run")
    assert bad_ref.returncode != 0
    assert "edge" in bad_ref.stderr and "vX.Y.Z" in bad_ref.stderr

    assert publish.run("--dry-run").returncode != 0


def test_release_requires_the_matching_git_tag(publish: Publisher) -> None:
    """Publishing :0.1.0 from an untagged commit would make a rollback lie about what runs."""
    untagged = publish.run("v0.1.0", "--dry-run")

    assert untagged.returncode != 0
    assert "not tagged v0.1.0" in untagged.stderr

    publish.git("tag", "v0.1.0")
    assert publish.run("v0.1.0", "--dry-run").returncode == 0
