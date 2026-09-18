import subprocess
from pathlib import Path

# The /dev-workflow-loop verification table; CLAUDE.md must list every one of these.
VERIFICATION_COMMANDS = [
    "uv run --directory backend ruff check .",
    "uv run --directory backend ruff format --check .",
    "uv run --directory backend ty check app",
    "uv run --directory backend pytest -q",
    "uv run --directory backend alembic check",
    "uv run --directory backend alembic upgrade head",
    "npm --prefix frontend run lint",
    "npm --prefix frontend run typecheck",
    "npm --prefix frontend test -- --run",
    "npm --prefix frontend run build",
    "docker buildx build --platform linux/amd64 -t fetcharr:dev --load .",
    "docker run -d --rm --name fetcharr-smoke -p 18000:8000 fetcharr:dev",
    "curl -fsS http://localhost:18000/healthz",
    "docker stop fetcharr-smoke",
]

GITIGNORE_PATTERNS = [
    "legacy/",
    ".claude/",
    ".env*",
    "*.db",
    "config/",
    "*.mp4",
    "*.mkv",
    "*.webm",
    "*.part",
    "node_modules/",
    ".venv/",
    "frontend/dist/",
    ".pytest_cache/",
    ".ruff_cache/",
    "cookies.txt",
]

DOCKERIGNORE_PATTERNS = [
    "legacy/",
    ".claude/",
    ".git/",
    "cookies.txt",
    "yt-dlp-env/",
    "**/node_modules/",
    "**/.venv/",
    "*.mp4",
    "*.mkv",
]


def _lines(path: Path) -> set[str]:
    return {line.strip() for line in path.read_text().splitlines()}


def test_claude_md_lists_verification_commands(repo_root: Path) -> None:
    claude_md = (repo_root / "CLAUDE.md").read_text()

    missing = [command for command in VERIFICATION_COMMANDS if command not in claude_md]
    assert missing == []


def test_gitignore_covers_scope(repo_root: Path) -> None:
    lines = _lines(repo_root / ".gitignore")

    assert [pattern for pattern in GITIGNORE_PATTERNS if pattern not in lines] == []


def test_dockerignore_excludes_local_files(repo_root: Path) -> None:
    lines = _lines(repo_root / ".dockerignore")

    assert [pattern for pattern in DOCKERIGNORE_PATTERNS if pattern not in lines] == []


def test_nothing_from_legacy_tracked(repo_root: Path) -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--cached"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    assert [path for path in tracked if path.startswith(("legacy/", ".claude/"))] == []
    assert [path for path in tracked if Path(path).name == "cookies.txt"] == []
    probes = ["legacy/cookies.txt", ".claude/plans/x.md"]
    ignored = subprocess.run(
        ["git", "check-ignore", "--no-index", *probes],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ignored.stdout.splitlines() == probes
