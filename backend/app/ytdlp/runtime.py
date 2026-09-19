"""Port of `detect_js_runtime` from download_video.sh."""

import os
import shutil
from pathlib import Path
from typing import Literal

JsRuntime = Literal["deno", "node"]


def detect_js_runtime() -> JsRuntime | None:
    """Find a JS runtime for YouTube's n-sig challenge: deno first, then node."""
    if shutil.which("deno") is None:
        # deno may be installed but missing from a non-interactive PATH.
        deno_bin = Path.home() / ".deno" / "bin"
        if os.access(deno_bin / "deno", os.X_OK):
            os.environ["PATH"] = f"{deno_bin}{os.pathsep}{os.environ.get('PATH', '')}"

    if shutil.which("deno") is not None:
        return "deno"
    if shutil.which("node") is not None:
        return "node"
    return None
