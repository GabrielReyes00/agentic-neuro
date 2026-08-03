#!/usr/bin/env python3
"""One-way migration of residency-vault notes to the canonical metadata schema.

The migration is deliberately conservative: it changes metadata placement and
durable file lineage, but it does not rewrite clinical prose or merge notes.
Run without ``--apply`` for a JSON preview.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from vault_schema import compose_note, extract_legacy_metadata, parse_frontmatter
except ModuleNotFoundError:
    from .vault_schema import compose_note, extract_legacy_metadata, parse_frontmatter


DEFAULT_VAULT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
SKIP_ROOTS = {".agents", ".git", ".obsidian", ".trash", "ACGME Canvases"}
ARTIFACT_TYPES = {
    "Shift Debriefs": "shift_debrief",
    "Concepts": "concept",
    "Consults": "consult",
    "Journal Club": "journal_club",
    "Operative Guides": "operative_guide",
    "Presentations": "presentation",
    "Reference": "reference",
    "Reports": "report",
    "Residency": "residency_context",
    "Study Material": "study_material",
}
EPHEMERAL_KEYS = {"manifest_path", "package_manifest"}
VA_LINK = "[[Residency/Institutions/VA]]"
VA_ROTATION_LINK = "[[Residency/Rotations/VA Neurosurgery PGY-1]]"
JOURNAL_CLUB_LINK = "[[Residency/Conferences/Journal Club]]"
SERVICE_BY_DOMAIN = {
    "spine": "[[Residency/Services/Spine]]",
    "neurocritical-care": "[[Residency/Services/Neurocritical Care]]",
    "tumor": "[[Residency/Services/Neuro-Oncology]]",
    "functional": "[[Residency/Services/Functional And Epilepsy]]",
    "peripheral-nerve": "[[Residency/Services/Peripheral Nerve]]",
}
PRESENTATION_DECKS = {
    "Operative Findings In Cubital Tunnel Reoperation":
        "Presentations/Decks/Articles/Operative Findings In Cubital Tunnel Reoperation.pptx",
    "Positive Sagittal Balance In Adult Spinal Deformity":
        "Presentations/Decks/Articles/Positive Sagittal Balance In Adult Spinal Deformity.pptx",
    "SPORT Lumbar Disk Herniation Trial":
        "Presentations/Decks/Articles/SPORT Lumbar Disk Herniation Trial.pptx",
    "Surgery Versus Corticosteroid Injection For Carpal Tunnel Syndrome":
        "Presentations/Decks/Articles/Surgery Versus Corticosteroid Injection For Carpal Tunnel Syndrome.pptx",
    "Ten-Year Outcomes Of TLIF":
        "Presentations/Decks/Articles/Ten-Year Outcomes Of TLIF.pptx",
    "Hybrid Resection And Responsive Neurostimulation For Drug-Resistant Epilepsy":
        "Presentations/Decks/Drafts/Hybrid Resection And Responsive Neurostimulation For Drug-Resistant Epilepsy Baseline.pptx",
}
STUDY_SOURCES = {
    "ABNS Neuroanatomy Exam Review": [
        "Study Material/Sources/Lab 1 - Gross Anatomy Brain Structures - Edited.pptx",
        "Study Material/Sources/Lab 1 - Gross Anatomy Brain Structures - Final.pptx",
        "Study Material/Sources/Lab 2 - Neuroimaging Review.pptx",
        "Study Material/Sources/Lab 3 - Long Tracts.pptx",
    ],
    "Reading Spine MRI": [
        "Study Material/Sources/Lab 2 - Neuroimaging Review.pptx",
    ],
}
EMPTY_PLACEHOLDERS = {
    "Temporal Lobe Epilepsy - Surgical Evaluation and Lobectomy",
    "Ventriculostomy (EVD) Placement - Kocher Point Technique and Complications",
    "Spine Neurological Examination - Localizing Radiculopathy and Myelopathy",
}


def _date_from_stat(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d")


def _domain_value(meta: dict[str, Any]) -> str:
    value = meta.get("domain", "general")
    if isinstance(value, list):
        value = value[0] if value else "general"
    return str(value).strip().lower().replace(" ", "-") or "general"


def _summary_for_missing(path: Path) -> str:
    if path.stem in EMPTY_PLACEHOLDERS:
        return "Empty concept placeholder retained for deliberate repair or archival review."
    if path.stem == "Reading Spine MRI":
        return "Unstructured manual notes on systematic spine MRI review; requires refactor."
    return f"Residency knowledge artifact for {path.stem}."


def _matching_journal_title(vault: Path, meta: dict[str, Any], title: str) -> str | None:
    source = str(meta.get("source_pdf") or "")
    candidates = [Path(source).stem, title]
    for candidate in candidates:
        if not candidate:
            continue
        direct = vault / "Journal Club" / f"{candidate}.md"
        if direct.is_file():
            return candidate
        folded = candidate.casefold()
        for note in (vault / "Journal Club").glob("*.md"):
            if note.stem.casefold() == folded:
                return note.stem
    return None


def _canonical_meta(vault: Path, path: Path, existing: dict[str, Any]) -> dict[str, Any]:
    rel = path.relative_to(vault)
    root = rel.parts[0]
    title = path.stem
    meta = {key: value for key, value in existing.items() if key not in EPHEMERAL_KEYS}
    artifact_type = str(meta.get("artifact_type") or ARTIFACT_TYPES.get(root, "note"))
    domain = _domain_value(meta)

    status = str(meta.get("status") or "current")
    if title in EMPTY_PLACEHOLDERS or title == "Reading Spine MRI":
        status = "needs-repair"

    core: dict[str, Any] = {
        "aliases": meta.pop("aliases", []),
        "artifact_type": artifact_type,
        "status": status,
        "domain": meta.pop("domain", domain),
        "summary": meta.pop("summary", _summary_for_missing(path)),
    }
    for canonical_key in (
        "artifact_type",
        "status",
        "institution",
        "service",
        "rotation",
        "conference",
        "source_file",
        "source_note",
        "presentation",
        "deck_file",
    ):
        meta.pop(canonical_key, None)

    if root in {"Journal Club", "Presentations"}:
        core.update(
            {
                "institution": VA_LINK,
                "rotation": VA_ROTATION_LINK,
                "conference": JOURNAL_CLUB_LINK,
            }
        )
        service = SERVICE_BY_DOMAIN.get(domain)
        if service:
            core["service"] = service

    if root == "Shift Debriefs" and title in {
        "Acute Spine Consult And Postoperative Spine Care",
        "Venous Sinus Thrombosis",
    }:
        core["institution"] = VA_LINK
        core["rotation"] = VA_ROTATION_LINK
        core["service"] = SERVICE_BY_DOMAIN[
            "spine" if "Spine" in title else "neurocritical-care"
        ]

    if root == "Journal Club":
        source_rel = f"Journal Club/Sources/{title}.pdf"
        if (vault / source_rel).is_file():
            meta["source_pdf"] = source_rel
            core["source_file"] = f"[[{source_rel}]]"
        presentation_title = next(
            (
                note.stem
                for note in (vault / "Presentations" / "Articles").glob("*.md")
                if note.stem.casefold() == title.casefold()
            ),
            None,
        )
        if presentation_title:
            core["presentation"] = (
                f"[[Presentations/Articles/{presentation_title}]]"
            )

    if root == "Presentations" and rel.parts[1:2] == ("Articles",):
        deck_rel = PRESENTATION_DECKS.get(title)
        if deck_rel and (vault / deck_rel).is_file():
            core["deck_file"] = f"[[{deck_rel}]]"
            meta["deck_path"] = deck_rel
            status = "draft" if "/Drafts/" in deck_rel else "current"
        else:
            meta.pop("deck_path", None)
            status = "deck-missing"
        core["status"] = status
        journal_title = _matching_journal_title(vault, meta, title)
        if journal_title:
            source_rel = f"Journal Club/Sources/{journal_title}.pdf"
            dossier_rel = f"Journal Club/{journal_title}"
            meta["source_journal_club"] = f"{dossier_rel}.md"
            if (vault / source_rel).is_file():
                meta["source_pdf"] = source_rel
                core["source_file"] = f"[[{source_rel}]]"
            core["source_note"] = f"[[{dossier_rel}]]"

    if root == "Study Material" and title in STUDY_SOURCES:
        meta.pop("source_files", None)
        core["source_files"] = [f"[[{item}]]" for item in STUDY_SOURCES[title]]

    created = (
        meta.pop("created", None)
        or meta.get("generated")
        or meta.get("date")
        or meta.get("presentation_date")
        or _date_from_stat(path)
    )
    updated = meta.pop("updated", None) or _date_from_stat(path)
    core["created"] = created
    core["updated"] = updated
    core.update(meta)
    return core


def migrate(vault: Path, apply: bool = False) -> dict[str, Any]:
    changed: list[str] = []
    skipped: list[str] = []
    errors: list[dict[str, str]] = []
    for path in sorted(vault.rglob("*.md")):
        rel = path.relative_to(vault)
        if rel.parts[0] in SKIP_ROOTS or path.name == "INDEX.md":
            continue
        if rel.parts[0] not in ARTIFACT_TYPES:
            skipped.append(str(rel))
            continue
        try:
            original = path.read_text(encoding="utf-8")
            native = parse_frontmatter(original)
            body, legacy = extract_legacy_metadata(original)
            existing = native or legacy or {}
            meta = _canonical_meta(vault, path, existing)
            rendered = compose_note(body, meta)
            if rendered != original:
                changed.append(str(rel))
                if apply:
                    path.write_text(rendered, encoding="utf-8")
        except Exception as exc:  # keep migration auditable per file
            errors.append({"path": str(rel), "error": str(exc)})
    return {
        "vault": str(vault),
        "mode": "apply" if apply else "preview",
        "changed_count": len(changed),
        "changed": changed,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = migrate(args.vault.expanduser().resolve(), apply=args.apply)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(
            f"{result['mode']}: {result['changed_count']} changed, "
            f"{len(result['errors'])} errors"
        )
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
