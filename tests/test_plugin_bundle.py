from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.sync_agent_adapters import expected_plugin_files


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "agentic-neuro"


def test_plugin_manifest_and_generated_bundle_stay_inside_plugin_root():
    manifest = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
    assert manifest["skills"] == "./skills/"
    expected = expected_plugin_files(
        json.loads((ROOT / ".agents/shared/workflow-registry.json").read_text())
    )
    for path, content in expected.items():
        assert path.is_relative_to(PLUGIN)
        assert path.is_file()
        observed = path.read_bytes() if isinstance(content, bytes) else path.read_text()
        assert observed == content
    assert not any(path.is_symlink() for path in PLUGIN.rglob("*"))
    assert (
        PLUGIN
        / "resources/docs/maintenance/Repository Maintenance Principles.md"
    ).is_file()
    assert (
        PLUGIN / "resources/docs/maintenance/Repository Hygiene Audit.md"
    ).is_file()


def test_reference_deck_is_repo_owned_and_hash_identical_in_plugin():
    style_path = ROOT / ".agents/shared/presentation-styles.json"
    style = json.loads(style_path.read_text())["styles"]["baylor_minimal_academic"]
    relative = Path(style["reference_deck"])
    assert not relative.is_absolute()
    canonical = style_path.parent / relative
    bundled = PLUGIN / "resources/.agents/shared" / relative
    assert canonical.is_file() and bundled.is_file()
    assert hashlib.sha256(canonical.read_bytes()).digest() == hashlib.sha256(
        bundled.read_bytes()
    ).digest()
