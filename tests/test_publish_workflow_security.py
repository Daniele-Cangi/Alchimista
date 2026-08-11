from __future__ import annotations

import re
from pathlib import Path


WORKFLOW_PATH = Path(__file__).parents[1] / ".github" / "workflows" / "publish-ghcr.yml"


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_publishing_actions_are_pinned_to_full_commit_shas() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    uses_lines = re.findall(r"^\s+uses:\s+([^\s#]+)\s+#\s+(v\S+)\s*$", workflow, re.MULTILINE)

    assert len(uses_lines) == 7
    for action, version_comment in uses_lines:
        repository, separator, revision = action.partition("@")
        assert separator == "@"
        assert "/" in repository
        assert re.fullmatch(r"[0-9a-f]{40}", revision)
        assert re.fullmatch(r"v\d+\.\d+\.\d+", version_comment)


def test_package_write_permission_is_scoped_to_publish_job() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    global_permissions = _between(workflow, "permissions:\n", "jobs:\n")
    proof_job = _between(workflow, "  self-hosted-proof:\n", "  publish:\n")
    publish_job = workflow.split("  publish:\n", 1)[1]

    assert "contents: read" in global_permissions
    assert "packages:" not in global_permissions
    assert "permissions:\n      contents: read" in proof_job
    assert "packages:" not in proof_job
    assert "permissions:\n      contents: read\n      packages: write" in publish_job
    assert workflow.count("packages: write") == 1
