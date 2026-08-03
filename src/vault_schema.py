"""Canonical Obsidian frontmatter helpers for the residency vault.

Obsidian recognizes YAML properties only when the metadata block is the first
block in a Markdown file.  Every vault writer, validator, indexer, and migration
tool should use this module so human-facing Obsidian properties and agent-facing
metadata cannot drift apart.

Legacy bottom-YAML extraction is intentionally isolated here for one-way
migration.  Production writers emit native top frontmatter only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml


METADATA_HINT_KEYS = frozenset(
    {
        "aliases",
        "artifact_type",
        "article_title",
        "created",
        "date",
        "deck_path",
        "domain",
        "extracted_from",
        "generated",
        "internal_knowledge_used",
        "mode",
        "provenance",
        "skill",
        "source_package_status",
        "source_pdf",
        "summary",
        "tags",
        "topic",
    }
)


class _FrontmatterDumper(yaml.SafeDumper):
    """Emit plain property values without YAML anchors or folded link paths."""

    def ignore_aliases(self, data: object) -> bool:
        return True


def frontmatter_bounds(text: str) -> tuple[int, int] | None:
    """Return byte offsets spanning native YAML frontmatter, including fences."""
    if text.startswith("\ufeff"):
        start = 1
    else:
        start = 0
    if not text[start:].startswith("---\n"):
        return None
    close = text.find("\n---", start + 4)
    while close >= 0:
        after = close + 4
        if after == len(text) or text[after] == "\n":
            return start, after + (1 if after < len(text) else 0)
        close = text.find("\n---", close + 1)
    return None


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse native top frontmatter, returning an empty mapping when absent."""
    bounds = frontmatter_bounds(text)
    if bounds is None:
        return {}
    start, end = bounds
    block = text[start:end].splitlines()[1:-1]
    try:
        parsed = yaml.safe_load("\n".join(block))
    except yaml.YAMLError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def split_frontmatter(text: str) -> tuple[str, dict[str, Any] | None]:
    """Return body text and parsed top frontmatter.

    The body is normalized to have no leading blank lines and one trailing
    newline. ``None`` distinguishes missing or malformed frontmatter from an
    intentionally empty mapping.
    """
    bounds = frontmatter_bounds(text)
    if bounds is None:
        return text, None
    meta = parse_frontmatter(text)
    if not meta:
        raw = text[bounds[0] : bounds[1]].splitlines()[1:-1]
        try:
            parsed = yaml.safe_load("\n".join(raw))
        except yaml.YAMLError:
            return text, None
        if not isinstance(parsed, Mapping):
            return text, None
    body = text[bounds[1] :].lstrip("\n").rstrip() + "\n"
    return body, meta


def render_frontmatter(meta: Mapping[str, Any]) -> str:
    """Render deterministic, Obsidian-native YAML frontmatter."""
    payload = yaml.dump(
        dict(meta),
        Dumper=_FrontmatterDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100000,
    ).strip()
    return f"---\n{payload}\n---\n"


def compose_note(body: str, meta: Mapping[str, Any]) -> str:
    """Compose a complete note with native frontmatter and no H1 requirement."""
    clean_body = body.strip()
    return render_frontmatter(meta) + ("\n" + clean_body + "\n" if clean_body else "")


def extract_legacy_metadata(text: str) -> tuple[str, dict[str, Any] | None]:
    """Extract a legacy fenced YAML mapping from anywhere after the body.

    This supports the historical bottom-YAML format and the malformed edge case
    where an attachment embed was appended after the metadata block.  Only a
    mapping containing known metadata keys is considered a metadata block, so
    ordinary thematic breaks are preserved.
    """
    body, native = split_frontmatter(text)
    if native is not None:
        return body, native

    lines = text.splitlines(keepends=True)
    fence_indexes = [idx for idx, line in enumerate(lines) if line.strip() == "---"]
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for left, right in zip(fence_indexes, fence_indexes[1:]):
        inner = "".join(lines[left + 1 : right])
        try:
            parsed = yaml.safe_load(inner)
        except yaml.YAMLError:
            continue
        if not isinstance(parsed, Mapping):
            continue
        parsed_dict = dict(parsed)
        if not (set(parsed_dict) & METADATA_HINT_KEYS):
            continue
        candidates.append((left, right, parsed_dict))

    if not candidates:
        return text, None

    left, right, meta = candidates[-1]
    retained = "".join(lines[:left] + lines[right + 1 :])
    retained = retained.strip() + ("\n" if retained.strip() else "")
    return retained, meta


def has_legacy_metadata(text: str) -> bool:
    """Return True when a non-native legacy YAML metadata block is present."""
    if frontmatter_bounds(text) is not None:
        return False
    _body, meta = extract_legacy_metadata(text)
    return meta is not None
