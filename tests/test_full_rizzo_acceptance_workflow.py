from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_full_rizzo_acceptance_is_optional_and_pinned() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "full-rizzo-acceptance.yml").read_text())
    job = workflow["jobs"]["full-rizzo"]
    source = (ROOT / "scripts" / "full_rizzo_acceptance.py").read_text(encoding="utf-8")

    assert "workflow_dispatch" in workflow[True]
    assert "full-rizzo-acceptance" in job["if"]
    assert job["timeout-minutes"] == 60
    assert "a1c3c83827eca22e9675e30c1111c4641caf5901" in source
    assert 'item.get("detector") == "modello"' in source
    assert '"restart", "rizzo-model-service", "privacy-service"' in source
