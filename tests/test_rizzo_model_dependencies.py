from pathlib import Path
import re


ROOT = Path(__file__).parents[1]


def test_rizzo_runtime_direct_dependencies_are_exactly_pinned() -> None:
    requirements = (
        ROOT / "services" / "rizzo_model_service" / "requirements.in"
    ).read_text(encoding="utf-8").splitlines()
    dependencies = {
        line.strip()
        for line in requirements
        if line.strip() and not line.startswith("#")
    }

    assert dependencies == {
        "fastapi==0.116.1",
        "uvicorn[standard]==0.35.0",
        "huggingface_hub==1.27.0",
        "tokenizers==0.22.2",
        "safetensors==0.8.0",
        "torch==2.13.0+cpu",
        "transformers==5.14.1",
    }


def test_rizzo_runtime_lock_is_complete_hashed_and_cpu_only() -> None:
    lock = (
        ROOT / "services" / "rizzo_model_service" / "requirements.lock"
    ).read_text(encoding="utf-8")
    package_starts = list(
        re.finditer(
            r"(?m)^[a-z0-9][a-z0-9._-]*(?:\[[^]]+\])?==[^\s\\]+\s*\\$",
            lock,
        )
    )

    assert len(package_starts) > 7
    assert "fastapi==0.116.1" in lock
    assert "uvicorn==0.35.0" in lock
    assert "huggingface-hub==1.27.0" in lock
    assert "tokenizers==0.22.2" in lock
    assert "safetensors==0.8.0" in lock
    assert "torch==2.13.0+cpu" in lock
    assert "transformers==5.14.1" in lock
    assert "nvidia-" not in lock
    assert "triton==" not in lock

    for index, package in enumerate(package_starts):
        next_start = (
            package_starts[index + 1].start()
            if index + 1 < len(package_starts)
            else len(lock)
        )
        assert "--hash=sha256:" in lock[package.end() : next_start]


def test_rizzo_container_enforces_the_hashed_lock() -> None:
    dockerfile = (
        ROOT / "services" / "rizzo_model_service" / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert 'pip install "pip==26.2.1"' in dockerfile
    assert "requirements.lock" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "--index-url https://pypi.org/simple" in dockerfile
    assert "--extra-index-url https://download.pytorch.org/whl/cpu" in dockerfile
    assert "requirements.txt" not in dockerfile
    assert "torch==" not in dockerfile
    assert "transformers==" not in dockerfile
    assert "pip install --upgrade pip" not in dockerfile
