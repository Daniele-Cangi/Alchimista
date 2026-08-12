"""Regenerate the reproducible Full-Rizzo Linux CPU dependency lock."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


UV_VERSION = "0.12.3"
ROOT = Path(__file__).resolve().parents[1]
INPUT = Path("services/rizzo_model_service/requirements.in")
LOCK = Path("services/rizzo_model_service/requirements.lock")


def main() -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit(f"uv {UV_VERSION} is required to regenerate {LOCK}")

    installed_version = subprocess.run(
        [uv, "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not installed_version.startswith(f"uv {UV_VERSION} "):
        raise SystemExit(
            f"expected uv {UV_VERSION}, found {installed_version or 'unknown version'}"
        )

    subprocess.run(
        [
            uv,
            "pip",
            "compile",
            INPUT.as_posix(),
            "--python-version",
            "3.11",
            "--python-platform",
            "x86_64-manylinux_2_28",
            "--generate-hashes",
            "--torch-backend",
            "cpu",
            "--default-index",
            "https://pypi.org/simple",
            "--no-header",
            "--output-file",
            LOCK.as_posix(),
        ],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
