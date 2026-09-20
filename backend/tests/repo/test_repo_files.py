import subprocess
from pathlib import Path

import yaml

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
    ".local/",
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
    ".local/",
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


def test_path_settings_documented(repo_root: Path) -> None:
    compose = (repo_root / "docker-compose.example.yml").read_text()
    readme_rows = [
        line for line in (repo_root / "README.md").read_text().splitlines() if line.startswith("|")
    ]

    for name, default in (
        ("COMPLETED_DIR", "/web-downloads/completed"),
        ("INCOMPLETE_DIR", "/web-downloads/incomplete"),
    ):
        assert f"{name}={default}" in compose
        assert any(row.startswith(f"| `{name}` | `{default}` |") for row in readme_rows)


def test_pipeline_settings_documented(repo_root: Path) -> None:
    compose = (repo_root / "docker-compose.example.yml").read_text()
    readme_rows = [
        line for line in (repo_root / "README.md").read_text().splitlines() if line.startswith("|")
    ]

    for name, default in (("MAX_CONCURRENT_DOWNLOADS", "2"), ("AUTO_RESUME", "true")):
        assert f"{name}={default}" in compose
        assert any(row.startswith(f"| `{name}` | `{default}` |") for row in readme_rows)


def test_secret_and_radarr_settings_documented(repo_root: Path) -> None:
    compose = (repo_root / "docker-compose.example.yml").read_text()
    readme_rows = [
        line for line in (repo_root / "README.md").read_text().splitlines() if line.startswith("|")
    ]

    # SECRET_KEY, RADARR_URL and RADARR_API_KEY have no default worth shipping, so the
    # compose file names them commented out and the README explains what they do (§13.4).
    for name in ("SECRET_KEY", "SECRET_KEY_FILE", "RADARR_URL", "RADARR_API_KEY"):
        assert f"{name}=" in compose, name
        assert any(row.startswith(f"| `{name}` |") for row in readme_rows), name
    assert "SECRET_KEY_FILE=/config/secret.key" in compose


def _dev_compose(repo_root: Path) -> dict:
    return yaml.safe_load((repo_root / "docker-compose.dev.yml").read_text())


def _mounts(service: dict) -> dict[str, str]:
    return {volume.split(":")[1]: volume.split(":")[0] for volume in service["volumes"]}


def _environment(service: dict) -> dict[str, str]:
    return dict(entry.split("=", 1) for entry in service["environment"])


def test_dev_compose_mounts_the_downloads_directory(repo_root: Path) -> None:
    compose = _dev_compose(repo_root)

    # Without it the dev container has nowhere to put downloads (§7.6), and a host
    # folder rather than a named volume keeps finished files openable.
    assert _mounts(compose["services"]["backend"])["/web-downloads"] == "./.local/web-downloads"
    assert "fetcharr-dev-downloads" not in compose.get("volumes", {})


def test_dev_compose_runs_the_arr_apps_on_one_shared_path(repo_root: Path) -> None:
    """The dev stack's whole point: one folder that means the same thing everywhere (M5c AC8)."""
    services = _dev_compose(repo_root)["services"]

    # A Move import is only a rename when fetcharr and the arr apps agree on the path (§7.1).
    shared = {
        name: _mounts(services[name])["/web-downloads"] for name in ("backend", "radarr", "sonarr")
    }
    assert set(shared.values()) == {"./.local/web-downloads"}, shared

    # The API keys are seeded, so a fresh volume needs no key copied out of the arr UI.
    key = "${DEV_RADARR_API_KEY:-0123456789abcdef0123456789abcdef}"
    assert _environment(services["radarr"])["RADARR__AUTH__APIKEY"] == key
    assert _environment(services["sonarr"])["SONARR__AUTH__APIKEY"].startswith(
        "${DEV_SONARR_API_KEY:-"
    )

    # And fetcharr is pointed at the throwaway Radarr with that same key (§7.5).
    backend = _environment(services["backend"])
    assert backend["RADARR_URL"] == "http://radarr:7878"
    assert backend["RADARR_API_KEY"] == key

    # One uid/gid/umask across all three, or an arr app can't delete what fetcharr wrote (§7.6).
    for name in ("backend", "radarr", "sonarr"):
        environment = _environment(services[name])
        assert (environment["PUID"], environment["PGID"], environment["UMASK"]) == (
            "1000",
            "1000",
            "002",
        ), name


def test_entrypoint_prepares_the_download_folders(repo_root: Path) -> None:
    entrypoint = (repo_root / "docker" / "entrypoint.sh").read_text()

    # A fresh volume belongs to root, so the app user needs the folders made and handed over.
    assert 'COMPLETED_DIR="${COMPLETED_DIR:-/web-downloads/completed}"' in entrypoint
    assert 'INCOMPLETE_DIR="${INCOMPLETE_DIR:-/web-downloads/incomplete}"' in entrypoint
    assert 'mkdir -p "$dir"' in entrypoint
    assert 'chown app:app "$dir"' in entrypoint
    # Never recursive: media Radarr/Sonarr owns must keep its ownership.
    assert "chown -R" not in entrypoint


def test_readme_documents_running_the_backend_on_the_host(repo_root: Path) -> None:
    development = (repo_root / "README.md").read_text().split("## Development", 1)[1]

    assert "COMPLETED_DIR=" in development
    assert "INCOMPLETE_DIR=" in development


def test_claude_md_documents_the_frontend_structure(repo_root: Path) -> None:
    claude_md = (repo_root / "CLAUDE.md").read_text()

    assert "## Frontend structure" in claude_md
    for expected in ("features/<domain>/", "no-restricted-imports", "@/features/<name>"):
        assert expected in claude_md, expected


def test_compose_mounts_web_downloads_volume(repo_root: Path) -> None:
    compose = yaml.safe_load((repo_root / "docker-compose.example.yml").read_text())
    targets = [volume.split(":")[1] for volume in compose["services"]["fetcharr"]["volumes"]]

    # completed/ and incomplete/ share the /web-downloads volume; no /data mount any more.
    assert targets == ["/config", "/web-downloads"]
