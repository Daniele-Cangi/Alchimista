from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_rizzo_runtime_direct_python_dependencies_are_exactly_pinned() -> None:
    requirements = (
        ROOT / "services" / "rizzo_model_service" / "requirements.txt"
    ).read_text(encoding="utf-8").splitlines()
    dependencies = [line.strip() for line in requirements if line.strip() and not line.startswith("#")]

    assert "huggingface_hub==1.27.0" in dependencies
    assert "tokenizers==0.22.2" in dependencies
    assert "safetensors==0.8.0" in dependencies
    assert all("==" in dependency for dependency in dependencies)


def test_rizzo_runtime_build_tool_and_heavy_dependencies_are_pinned() -> None:
    dockerfile = (
        ROOT / "services" / "rizzo_model_service" / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert 'pip install "pip==26.2.1"' in dockerfile
    assert '"torch==2.13.0"' in dockerfile
    assert '"transformers==5.14.1"' in dockerfile
    assert "pip install --upgrade pip" not in dockerfile
