"""Shared post-write hooks for durable Obsidian artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def refresh_vault_intelligence(vault_root: Path) -> dict[str, Any]:
    """Refresh the persistent vault index only for the configured real vault."""
    try:
        import vault_index
    except ModuleNotFoundError:  # pragma: no cover - package import in tests
        from . import vault_index
    return vault_index.refresh_default_index_after_vault_write(vault_root=vault_root)

