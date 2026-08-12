from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PINNED_ACTION = re.compile(
    r"^\s*uses:\s+([^@\s]+)@([0-9a-f]{40})\s+#\s+(v\d+(?:\.\d+){0,2})\s*$"
)


def test_every_external_workflow_action_is_sha_pinned() -> None:
    external_actions: list[tuple[Path, int, str]] = []

    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for line_number, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "uses:" not in line or re.match(r"^\s*uses:\s+\./", line):
                continue
            external_actions.append((workflow, line_number, line))

    assert external_actions
    invalid = [
        f"{path.name}:{line_number}: {line.strip()}"
        for path, line_number, line in external_actions
        if PINNED_ACTION.fullmatch(line) is None
    ]
    assert invalid == []
