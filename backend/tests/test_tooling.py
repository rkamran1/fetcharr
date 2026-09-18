import subprocess
import sys
import tomllib
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_ruff_async_rules_enabled() -> None:
    config = tomllib.loads((BACKEND_DIR / "pyproject.toml").read_text())

    assert "ASYNC" in config["tool"]["ruff"]["lint"]["select"]


def test_ruff_flags_blocking_call_in_async(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("import time\n\n\nasync def handler():\n    time.sleep(1)\n")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(BACKEND_DIR / "pyproject.toml"),
            "--no-cache",
            "--output-format",
            "concise",
            str(sample),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "ASYNC251" in result.stdout
