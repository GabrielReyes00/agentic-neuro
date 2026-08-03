#!/usr/bin/env python3
"""Validate the real PowerPoint package produced by /grand-rounds."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

import yaml

try:
    from vault_schema import parse_frontmatter
except ModuleNotFoundError:  # imported as part of the `src` package
    from .vault_schema import parse_frontmatter


ARTICLE_REQUIRED_COVERAGE = (
    "Start Here",
    "Clinical Foundation",
    "Study Architecture",
    "Results That Matter",
    "Figures and Tables Explained",
    "Interpretation",
    "Limitations That Actually Matter",
    "Neurosurgical Relevance",
    "Presentation Core",
)

ARTICLE_REQUIRED_EVIDENCE_DIMENSIONS = (
    "study_ecosystem",
    "eligibility_and_applicability",
    "intervention_and_comparator",
    "outcome_schedule",
    "treatment_adherence",
    "longitudinal_results",
    "benefits_harms_secondary_outcomes",
    "interpretation_and_bias",
)

ARTICLE_CRITICAL_SALIENCE = {
    "thesis-determining",
    "decision-relevant",
    "faculty-defense",
    "administrative",
}
ARTICLE_CRITICAL_DISPOSITIONS = {"main", "notes", "backup", "omit"}
COMPANION_SOURCE_STATES = {
    "verified_source",
    "identified_not_retrieved",
    "not_applicable",
}

SLIDE_REQUIRED_KEYS = {
    "id",
    "title",
    "job",
    "role",
    "layout_family",
    "visual_anchor",
    "visual_coverage",
    "background_tone",
    "visible_content",
    "speaker_notes",
    "citations",
    "assets",
    "source_sections",
    "timed_seconds",
    "backup",
}

PLAN_SCHEMA = "grand_rounds_deck_plan_v2"
VISUAL_QA_SCHEMA = "grand_rounds_visual_qa_v2"
STYLE_CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / ".agents/shared/presentation-styles.json"
)
STYLE_ROUTES = {
    "editorial_academic": "editorial_academic",
    "custom_directed": "custom_directed",
    "template_faithful": "template_faithful",
}
DESIGN_BRIEF_STRING_KEYS = {
    "route",
    "audience",
    "communication_job",
    "art_direction",
    "page_system",
    "palette_rationale",
    "display_font",
    "body_font",
    "title_style",
    "motif",
    "background_strategy",
}
VISUAL_QA_EMPTY_LIST_KEYS = (
    "overflow_slides",
    "overlap_slides",
    "clipped_slides",
    "title_wrap_slides",
    "unresolved_placeholders",
    "illegible_asset_slides",
    "figure_scale_failures",
    "citation_failures",
    "chart_label_failures",
    "alignment_failures",
    "misleading_quantitative_encoding_slides",
    "color_overuse_slides",
    "filled_container_overuse_slides",
    "rounded_container_slides",
    "decorative_line_overuse_slides",
    "dark_background_drift_slides",
    "textbox_fit_failures",
    "bullet_wall_slides",
    "weak_visual_anchor_slides",
    "repetitive_layout_slides",
    "decorative_chrome_slides",
    "ui_panel_slides",
    "palette_drift_slides",
    "typography_inconsistency_slides",
    "spacing_inconsistency_slides",
    "redundant_slides",
    "orphan_context_slides",
    "title_slide_interpretive_copy_slides",
    "slogan_or_tagline_slides",
    "rhetorical_or_adversarial_copy_slides",
    "low_information_annotation_slides",
    "narrative_prose_slides",
    "unsupported_interpretation_slides",
    "word_fragmentation_slides",
    "numeric_token_split_slides",
    "semantic_legend_failures",
    "pasted_chart_legend_slides",
    "watermarked_asset_slides",
    "redundant_interpretive_band_slides",
    "summary_duplication_slides",
    "cross_platform_render_failures",
)


def _presentation_styles() -> dict[str, Any]:
    try:
        data = json.loads(STYLE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid presentation style registry: {exc}") from exc
    styles = data.get("styles")
    if not isinstance(styles, dict):
        raise RuntimeError("presentation style registry has no styles object")
    return styles


def visual_qa_template(*, slide_count: int = 0) -> dict[str, Any]:
    """Return the canonical QA ledger shape without duplicating it in prose."""
    template: dict[str, Any] = {
        "schema": VISUAL_QA_SCHEMA,
        "status": "pending",
        "inspected_slide_count": slide_count,
        "full_size_slide_count": slide_count,
        "contact_sheet_inspected": False,
        "repair_cycle_count": 0,
        "design_brief_match": False,
        "meaningful_visual_main_slide_count": 0,
        "layout_family_counts": {},
        "min_title_font_size_pt": 0,
        "min_body_font_size_pt": 0,
        "citation_font_size_pt": 0,
        "notes": [],
    }
    template.update({key: [] for key in VISUAL_QA_EMPTY_LIST_KEYS})
    return template


@dataclass
class GuardResult:
    deck: str
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "deck": self.deck,
            "metrics": self.metrics,
            "errors": self.errors,
        }


def _load_json(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"{label} does not exist: {path}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"invalid {label}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return {}
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pptx_metrics(deck: Path, errors: list[str]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "pptx_slide_count": 0,
        "pptx_notes_count": 0,
        "pptx_media_count": 0,
        "aspect_ratio": 0.0,
    }
    if not deck.is_file():
        errors.append(f"deck does not exist: {deck}")
        return metrics
    if deck.suffix.lower() != ".pptx":
        errors.append("deck must be a .pptx file")
        return metrics
    try:
        with ZipFile(deck) as archive:
            names = archive.namelist()
            slides = [
                name
                for name in names
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ]
            notes = [
                name
                for name in names
                if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)
            ]
            media = [name for name in names if name.startswith("ppt/media/") and not name.endswith("/")]
            metrics["pptx_slide_count"] = len(slides)
            metrics["pptx_media_count"] = len(media)

            meaningful_notes = 0
            for name in notes:
                try:
                    root = ET.fromstring(archive.read(name))
                except ET.ParseError:
                    continue
                tokens = [
                    (node.text or "").strip()
                    for node in root.iter()
                    if node.tag.endswith("}t") and (node.text or "").strip()
                ]
                text = " ".join(token for token in tokens if not token.isdigit())
                if len(text) >= 20:
                    meaningful_notes += 1
            metrics["pptx_notes_count"] = meaningful_notes

            try:
                root = ET.fromstring(archive.read("ppt/presentation.xml"))
                node = next((item for item in root.iter() if item.tag.endswith("}sldSz")), None)
                if node is not None:
                    width = int(node.attrib.get("cx", "0"))
                    height = int(node.attrib.get("cy", "0"))
                    metrics["aspect_ratio"] = round(width / height, 4) if height else 0.0
            except (KeyError, ET.ParseError, ValueError):
                pass
    except BadZipFile:
        errors.append("deck is not a valid OOXML ZIP package")
    return metrics


def validate_package(
    *,
    deck: Path,
    plan_path: Path,
    assets_path: Path,
    visual_qa_path: Path,
    source_journal_club: Path | None = None,
) -> GuardResult:
    errors: list[str] = []
    plan = _load_json(plan_path, "deck plan", errors)
    asset_manifest = _load_json(assets_path, "asset manifest", errors)
    visual_qa = _load_json(visual_qa_path, "visual QA", errors)
    pptx = _pptx_metrics(deck, errors)

    if plan.get("schema") != PLAN_SCHEMA:
        errors.append(f"deck plan schema must be {PLAN_SCHEMA}")
    mode = str(plan.get("mode") or "").lower()
    if mode not in {"case", "article"}:
        errors.append("deck plan mode must be case or article")
    style_profile = str(plan.get("style_profile") or "").strip()
    if style_profile not in STYLE_ROUTES:
        errors.append(
            "deck plan style_profile must be editorial_academic, custom_directed, or template_faithful"
        )

    design_brief = plan.get("design_brief")
    if not isinstance(design_brief, dict):
        errors.append("deck plan requires a design_brief object")
        design_brief = {}
    for key in sorted(DESIGN_BRIEF_STRING_KEYS):
        if not str(design_brief.get(key) or "").strip():
            errors.append(f"design_brief missing {key}")
    expected_route = STYLE_ROUTES.get(style_profile)
    if expected_route and design_brief.get("route") != expected_route:
        errors.append("design_brief route does not match style_profile")
    if style_profile == "editorial_academic" and design_brief.get("title_style") != "sentence_case":
        errors.append("editorial_academic design_brief title_style must be sentence_case")
    palette = design_brief.get("palette")
    if not isinstance(palette, dict):
        errors.append("design_brief palette must be an object")
    else:
        for key in ("canvas", "ink", "primary", "secondary", "signal"):
            value = str(palette.get(key) or "")
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
                errors.append(f"design_brief palette {key} must be a six-digit hex color")
    declared_layout_families = design_brief.get("layout_families")
    if not isinstance(declared_layout_families, list) or not declared_layout_families:
        errors.append("design_brief layout_families must be a non-empty list")
        declared_layout_families = []
    elif style_profile == "editorial_academic" and len(set(declared_layout_families)) < 3:
        errors.append("editorial_academic design requires at least three layout families")
    forbidden_moves = design_brief.get("forbidden_moves")
    if not isinstance(forbidden_moves, list) or not forbidden_moves:
        errors.append("design_brief forbidden_moves must be a non-empty list")
    surface_style = str(design_brief.get("surface_style") or "").strip()
    if surface_style == "baylor_minimal_academic":
        style = _presentation_styles()[surface_style]
        constraints = design_brief.get("human_style_constraints")
        if not isinstance(constraints, dict):
            errors.append(
                "baylor_minimal_academic requires human_style_constraints"
            )
        else:
            required_constraints = style["constraints"]
            for key, expected in required_constraints.items():
                if constraints.get(key) != expected:
                    errors.append(
                        f"baylor_minimal_academic constraint {key} must be {expected!r}"
                    )
        if design_brief.get("background_strategy") != "white_only":
            errors.append(
                "baylor_minimal_academic background_strategy must be white_only"
            )
        expected_palette = style["palette"]
        if isinstance(palette, dict):
            for key, expected in expected_palette.items():
                if palette.get(key) != expected:
                    errors.append(
                        f"baylor_minimal_academic palette {key} must be {expected}"
                    )
        reference_alignment = design_brief.get("reference_alignment")
        if not isinstance(reference_alignment, dict):
            errors.append(
                "baylor_minimal_academic requires reference_alignment"
            )
        else:
            reference_deck = str(
                reference_alignment.get("reference_deck") or ""
            ).strip()
            if not reference_deck:
                errors.append("reference_alignment missing reference_deck")
            if reference_alignment.get("status") != "inspected":
                errors.append("reference_alignment status must be inspected")
            for key in ("adopted_patterns", "rejected_weaknesses"):
                values = reference_alignment.get(key)
                if not isinstance(values, list) or not values:
                    errors.append(f"reference_alignment {key} must be a non-empty list")
    if mode == "article" and str(plan.get("title_slide_subtitle") or "").strip():
        errors.append("article title slide must not contain an interpretive subtitle")

    slides = plan.get("slides")
    if not isinstance(slides, list) or not slides:
        errors.append("deck plan slides must be a non-empty list")
        slides = []

    slide_ids: set[str] = set()
    slide_backup_by_id: dict[str, bool] = {}
    titles: set[str] = set()
    main_seconds = 0
    main_count = 0
    backup_count = 0
    substantive_main_count = 0
    meaningful_visual_main_count = 0
    main_layout_families: list[str] = []
    slide_asset_refs: set[str] = set()
    for idx, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            errors.append(f"slide {idx} must be an object")
            continue
        missing = SLIDE_REQUIRED_KEYS - set(slide)
        if missing:
            errors.append(f"slide {idx} missing keys: {', '.join(sorted(missing))}")
        slide_id = str(slide.get("id") or "").strip()
        title = str(slide.get("title") or "").strip()
        job = str(slide.get("job") or "").strip()
        role = str(slide.get("role") or "").strip()
        layout_family = str(slide.get("layout_family") or "").strip()
        visual_anchor = str(slide.get("visual_anchor") or "").strip()
        background_tone = str(slide.get("background_tone") or "").strip()
        notes = str(slide.get("speaker_notes") or "").strip()
        if not slide_id or slide_id in slide_ids:
            errors.append(f"slide {idx} has missing or duplicate id")
        slide_ids.add(slide_id)
        slide_backup_by_id[slide_id] = slide.get("backup") is True
        if not title or title.lower() in titles:
            errors.append(f"slide {idx} has missing or duplicate title")
        titles.add(title.lower())
        if not job:
            errors.append(f"slide {idx} has no declared job")
        if not role:
            errors.append(f"slide {idx} has no declared role")
        if not layout_family:
            errors.append(f"slide {idx} has no layout_family")
        elif declared_layout_families and layout_family not in declared_layout_families:
            errors.append(f"slide {idx} uses undeclared layout_family: {layout_family}")
        if background_tone not in {"light", "dark", "image"}:
            errors.append(f"slide {idx} background_tone must be light, dark, or image")
        try:
            visual_coverage = float(slide.get("visual_coverage"))
        except (TypeError, ValueError):
            visual_coverage = -1
            errors.append(f"slide {idx} visual_coverage must be numeric")
        if visual_coverage < 0 or visual_coverage > 100:
            errors.append(f"slide {idx} visual_coverage must be between 0 and 100")
        if len(notes) < 40:
            errors.append(f"slide {idx} speaker notes are too thin")
        citations = slide.get("citations")
        if mode == "article" and (not isinstance(citations, list) or not citations):
            errors.append(f"article slide {idx} has no citation")
        assets = slide.get("assets")
        if isinstance(assets, list):
            slide_asset_refs.update(str(item) for item in assets if str(item).strip())
        try:
            seconds = int(slide.get("timed_seconds") or 0)
        except (TypeError, ValueError):
            seconds = 0
            errors.append(f"slide {idx} timed_seconds must be an integer")
        if slide.get("backup") is True:
            backup_count += 1
        else:
            main_count += 1
            main_seconds += max(seconds, 0)
            if role not in {"title", "section"}:
                substantive_main_count += 1
                main_layout_families.append(layout_family)
                if visual_anchor.lower() in {
                    "",
                    "text",
                    "bullets",
                    "bullet list",
                    "title rule",
                    "decorative chrome",
                }:
                    errors.append(f"slide {idx} lacks a meaningful visual_anchor")
                else:
                    meaningful_visual_main_count += 1
                if visual_coverage < 35:
                    errors.append(f"slide {idx} visual_coverage is below 35%")
                if role in {"evidence", "comparison"} and visual_coverage < 50:
                    errors.append(f"slide {idx} evidence visual_coverage is below 50%")
            if mode == "article":
                rationale = str(slide.get("separation_rationale") or "").strip()
                if len(rationale) < 25:
                    errors.append(f"article slide {idx} lacks a specific separation_rationale")
                words = re.findall(r"\b[\w%+–—-]+\b", title)
                if role != "title" and len(words) > 8:
                    errors.append(f"article slide {idx} title exceeds 8 words")

    layout_counts = Counter(main_layout_families)
    if substantive_main_count:
        max_allowed = max(1, substantive_main_count // 2)
        for family, count in layout_counts.items():
            if count > max_allowed:
                errors.append(
                    f"layout_family {family} is used on {count} of {substantive_main_count} substantive main slides"
                )
    for idx in range(len(main_layout_families) - 2):
        window = main_layout_families[idx : idx + 3]
        if len(set(window)) == 1:
            errors.append(f"layout_family repeats on three consecutive substantive slides: {window[0]}")
            break

    if (
        style_profile == "editorial_academic"
        and design_brief.get("background_strategy") == "dark_title_with_light_content"
    ):
        main_slides = [
            slide for slide in slides if isinstance(slide, dict) and slide.get("backup") is not True
        ]
        if main_slides:
            if main_slides[0].get("background_tone") not in {"dark", "image"}:
                errors.append("editorial academic opening must use a dark or image background")
            for idx, slide in enumerate(main_slides[1:], start=2):
                if slide.get("background_tone") != "light":
                    errors.append(
                        f"editorial academic content slide {idx} must use a light background"
                    )

    duration = plan.get("duration_minutes")
    try:
        duration_seconds = int(duration) * 60
    except (TypeError, ValueError):
        duration_seconds = 0
        errors.append("duration_minutes must be an integer")
    if duration_seconds and main_seconds > duration_seconds:
        errors.append(
            f"main-slide timing exceeds duration: {main_seconds}s > {duration_seconds}s"
        )

    if len(slides) != pptx["pptx_slide_count"]:
        errors.append(
            f"deck plan slide count {len(slides)} does not match PPTX {pptx['pptx_slide_count']}"
        )
    if slides and pptx["pptx_notes_count"] < len(slides) - 1:
        errors.append(
            f"PPTX has meaningful notes on only {pptx['pptx_notes_count']} of {len(slides)} slides"
        )
    ratio = float(pptx.get("aspect_ratio") or 0.0)
    if ratio and abs(ratio - (16 / 9)) > 0.02:
        errors.append(f"deck is not 16:9; aspect ratio is {ratio}")

    coverage = plan.get("coverage")
    if mode == "article":
        if slides and isinstance(slides[0], dict) and str(slides[0].get("title") or "") != str(plan.get("title") or ""):
            errors.append("article title slide must reproduce the article title exactly")
        if not isinstance(coverage, dict):
            errors.append("article deck plan requires coverage mapping")
            coverage = {}
        for section in ARTICLE_REQUIRED_COVERAGE:
            refs = coverage.get(section) if isinstance(coverage, dict) else None
            if not isinstance(refs, list) or not refs:
                errors.append(f"article coverage missing: {section}")
            elif any(str(ref) not in slide_ids for ref in refs):
                errors.append(f"article coverage references unknown slide for: {section}")

        coverage_audit = plan.get("coverage_audit")
        if not isinstance(coverage_audit, dict):
            errors.append("article deck plan requires an interpretation-critical coverage_audit")
            coverage_audit = {}

        required_dimensions = coverage_audit.get("required_dimensions")
        if not isinstance(required_dimensions, dict):
            errors.append("coverage_audit required_dimensions must be an object")
            required_dimensions = {}
        for dimension in ARTICLE_REQUIRED_EVIDENCE_DIMENSIONS:
            refs = required_dimensions.get(dimension)
            if not isinstance(refs, list) or not refs:
                errors.append(f"coverage_audit missing evidence dimension: {dimension}")
            elif any(str(ref) not in slide_ids for ref in refs):
                errors.append(f"coverage_audit references unknown slide for: {dimension}")

        coverage_risks = coverage_audit.get("coverage_risks")
        if not isinstance(coverage_risks, list):
            errors.append("coverage_audit coverage_risks must be a list")
        elif coverage_risks:
            errors.append("coverage_audit has unresolved coverage_risks")

        critical_items = coverage_audit.get("critical_items")
        if not isinstance(critical_items, list) or not critical_items:
            errors.append("coverage_audit critical_items must be a non-empty list")
            critical_items = []
        critical_ids: set[str] = set()
        for idx, item in enumerate(critical_items, start=1):
            if not isinstance(item, dict):
                errors.append(f"coverage critical item {idx} must be an object")
                continue
            item_id = str(item.get("id") or "").strip()
            summary = str(item.get("summary") or "").strip()
            salience = str(item.get("salience") or "").strip()
            disposition = str(item.get("disposition") or "").strip()
            source = str(item.get("source") or "").strip()
            rationale = str(item.get("rationale") or "").strip()
            refs = item.get("slide_ids")
            if not item_id or item_id in critical_ids:
                errors.append(f"coverage critical item {idx} has missing or duplicate id")
            critical_ids.add(item_id)
            if not summary:
                errors.append(f"coverage critical item {item_id or idx} missing summary")
            if salience not in ARTICLE_CRITICAL_SALIENCE:
                errors.append(f"coverage critical item {item_id or idx} has invalid salience")
            if disposition not in ARTICLE_CRITICAL_DISPOSITIONS:
                errors.append(f"coverage critical item {item_id or idx} has invalid disposition")
            if not source:
                errors.append(f"coverage critical item {item_id or idx} missing source")
            if len(rationale) < 20:
                errors.append(f"coverage critical item {item_id or idx} has thin rationale")
            if salience in {"thesis-determining", "decision-relevant"} and disposition == "omit":
                errors.append(f"coverage critical item {item_id or idx} cannot omit {salience} evidence")
            if disposition != "omit":
                if not isinstance(refs, list) or not refs:
                    errors.append(f"coverage critical item {item_id or idx} must map to a slide")
                    refs = []
                elif any(str(ref) not in slide_ids for ref in refs):
                    errors.append(f"coverage critical item {item_id or idx} references unknown slide")
                if disposition == "main" and any(slide_backup_by_id.get(str(ref), False) for ref in refs):
                    errors.append(f"coverage critical item {item_id or idx} marked main but maps to backup")
                if disposition == "backup" and any(not slide_backup_by_id.get(str(ref), False) for ref in refs):
                    errors.append(f"coverage critical item {item_id or idx} marked backup but maps to main")

        longitudinal = coverage_audit.get("longitudinal_result_coverage")
        if not isinstance(longitudinal, dict):
            errors.append("coverage_audit requires longitudinal_result_coverage")
        else:
            prespecified = longitudinal.get("prespecified_timepoints")
            shown = longitudinal.get("shown_timepoints")
            if not isinstance(prespecified, list) or not prespecified:
                errors.append("longitudinal_result_coverage requires prespecified_timepoints")
            if not isinstance(shown, list) or not shown:
                errors.append("longitudinal_result_coverage requires shown_timepoints")
                shown = []
            if longitudinal.get("trajectory_required") is True and len(shown) < 2:
                errors.append("trajectory-required article must show at least two outcome timepoints")
            if len(str(longitudinal.get("rationale") or "").strip()) < 20:
                errors.append("longitudinal_result_coverage requires a specific rationale")

        companion_evidence = coverage_audit.get("companion_evidence")
        if not isinstance(companion_evidence, list):
            errors.append("coverage_audit companion_evidence must be a list")
            companion_evidence = []
        for idx, item in enumerate(companion_evidence, start=1):
            if not isinstance(item, dict):
                errors.append(f"companion evidence {idx} must be an object")
                continue
            label = str(item.get("label") or "").strip()
            source_status = str(item.get("source_status") or "").strip()
            disposition = str(item.get("disposition") or "").strip()
            refs = item.get("slide_ids")
            if not label:
                errors.append(f"companion evidence {idx} missing label")
            if source_status not in COMPANION_SOURCE_STATES:
                errors.append(f"companion evidence {label or idx} has invalid source_status")
            if disposition not in ARTICLE_CRITICAL_DISPOSITIONS:
                errors.append(f"companion evidence {label or idx} has invalid disposition")
            if item.get("material_to_interpretation") is True and disposition == "omit":
                errors.append(f"material companion evidence {label or idx} cannot be omitted")
            if item.get("material_to_interpretation") is True:
                if not isinstance(refs, list) or not refs:
                    errors.append(f"material companion evidence {label or idx} must map to a slide")
                elif any(str(ref) not in slide_ids for ref in refs):
                    errors.append(f"companion evidence {label or idx} references unknown slide")
            if source_status == "verified_source" and not str(item.get("citation") or "").strip():
                errors.append(f"verified companion evidence {label or idx} requires a citation")
        if backup_count < 1:
            errors.append("article deck requires at least one backup slide")
        main_slides = [slide for slide in slides if isinstance(slide, dict) and slide.get("backup") is not True]
        if main_slides:
            if len(main_slides) < 2:
                errors.append("article deck requires a Background or Introduction slide after the title")
            else:
                background = main_slides[1]
                background_title = re.sub(
                    r"\s+", " ", str(background.get("title") or "").strip().lower()
                )
                if background_title not in {"background", "introduction"}:
                    errors.append(
                        "second main article slide must be titled Background or Introduction"
                    )
                if str(background.get("role") or "").strip() != "background":
                    errors.append("article Background or Introduction slide must use role background")
                background_sections = background.get("source_sections")
                if (
                    not isinstance(background_sections, list)
                    or "Clinical Foundation" not in background_sections
                ):
                    errors.append(
                        "article Background or Introduction slide must map to Clinical Foundation"
                    )
                background_visible = background.get("visible_content")
                if not isinstance(background_visible, list) or not 3 <= len(background_visible) <= 5:
                    errors.append(
                        "article Background or Introduction slide must contain three to five orientation anchors"
                    )
            last = main_slides[-1]
            title = re.sub(r"\s+", " ", str(last.get("title") or "").strip().lower())
            if title not in {"summary", "main takeaway", "main takeaways"}:
                errors.append("last main article slide must be titled Summary or Main Takeaways")
            visible = last.get("visible_content")
            if not isinstance(visible, list) or not 3 <= len(visible) <= 5:
                errors.append("article summary slide must contain three to five recap points")
        checks = plan.get("result_checks")
        if not isinstance(checks, list) or not checks:
            errors.append("article deck requires quantitative result_checks")
        else:
            for idx, check in enumerate(checks, start=1):
                if not isinstance(check, dict) or check.get("pass") is not True:
                    errors.append(f"result check {idx} did not pass")
                for key in ("claim", "expected", "actual", "source"):
                    if not isinstance(check, dict) or not str(check.get(key) or "").strip():
                        errors.append(f"result check {idx} missing {key}")

    assets = asset_manifest.get("assets")
    if not isinstance(assets, list):
        errors.append("asset manifest must contain an assets list")
        assets = []
    asset_ids: set[str] = set()
    for idx, asset in enumerate(assets, start=1):
        if not isinstance(asset, dict):
            errors.append(f"asset {idx} must be an object")
            continue
        asset_id = str(asset.get("asset_id") or "").strip()
        if not asset_id or asset_id in asset_ids:
            errors.append(f"asset {idx} has missing or duplicate asset_id")
        asset_ids.add(asset_id)
        for key in ("kind", "source_label", "transformation", "citation"):
            if not str(asset.get(key) or "").strip():
                errors.append(f"asset {asset_id or idx} missing {key}")
        output_path = str(asset.get("output_path") or "").strip()
        if output_path and not Path(output_path).is_file():
            errors.append(f"asset output does not exist: {output_path}")
        destinations = asset.get("destination_slides")
        if not isinstance(destinations, list) or not destinations:
            errors.append(f"asset {asset_id or idx} has no destination slides")
        elif any(str(ref) not in slide_ids for ref in destinations):
            errors.append(f"asset {asset_id or idx} references unknown slide")
    missing_assets = slide_asset_refs - asset_ids
    if missing_assets:
        errors.append("slides reference unknown assets: " + ", ".join(sorted(missing_assets)))

    if visual_qa.get("schema") != VISUAL_QA_SCHEMA:
        errors.append(f"visual QA schema must be {VISUAL_QA_SCHEMA}")
    if visual_qa.get("status") != "pass":
        errors.append("visual QA status must be pass")
    if visual_qa.get("inspected_slide_count") != len(slides):
        errors.append("visual QA inspected_slide_count does not match deck")
    if visual_qa.get("full_size_slide_count") != len(slides):
        errors.append("visual QA full_size_slide_count does not match deck")
    if visual_qa.get("contact_sheet_inspected") is not True:
        errors.append("visual QA must confirm contact-sheet inspection")
    if visual_qa.get("design_brief_match") is not True:
        errors.append("visual QA must confirm the rendered deck matches the design brief")
    repair_cycles = visual_qa.get("repair_cycle_count")
    if not isinstance(repair_cycles, int) or repair_cycles < 1:
        errors.append("visual QA requires at least one repair cycle")
    if visual_qa.get("meaningful_visual_main_slide_count") != substantive_main_count:
        errors.append("visual QA meaningful_visual_main_slide_count does not match the plan")
    qa_layout_counts = visual_qa.get("layout_family_counts")
    if not isinstance(qa_layout_counts, dict):
        errors.append("visual QA layout_family_counts must be an object")
    elif qa_layout_counts != dict(layout_counts):
        errors.append("visual QA layout_family_counts does not match the deck plan")
    for key in VISUAL_QA_EMPTY_LIST_KEYS:
        value = visual_qa.get(key)
        if not isinstance(value, list):
            errors.append(f"visual QA {key} must be a list")
        elif value:
            errors.append(f"visual QA has unresolved {key}: {value}")

    title_size = visual_qa.get("min_title_font_size_pt")
    if style_profile == "template_faithful":
        title_floor = 1
    elif surface_style == "baylor_minimal_academic":
        title_floor = _presentation_styles()[surface_style]["font_floors_pt"]["title"]
    else:
        title_floor = 35
    if not isinstance(title_size, (int, float)) or title_size < title_floor:
        errors.append(f"visual QA min_title_font_size_pt must be at least {title_floor}")
    body_size = visual_qa.get("min_body_font_size_pt")
    if style_profile == "template_faithful":
        body_floor = 1
    elif surface_style == "baylor_minimal_academic":
        body_floor = _presentation_styles()[surface_style]["font_floors_pt"]["body"]
    else:
        body_floor = 18
    if not isinstance(body_size, (int, float)) or body_size < body_floor:
        errors.append(f"visual QA min_body_font_size_pt must be at least {body_floor}")
    citation_size = visual_qa.get("citation_font_size_pt")
    if style_profile == "template_faithful":
        citation_floor = 1
    elif surface_style == "baylor_minimal_academic":
        citation_floor = _presentation_styles()[surface_style]["font_floors_pt"]["citation"]
    else:
        citation_floor = 9
    if not isinstance(citation_size, (int, float)) or citation_size < citation_floor:
        errors.append(f"visual QA citation_font_size_pt must be at least {citation_floor}")

    source_pdf = Path(str(plan.get("source_pdf") or "")) if plan.get("source_pdf") else None
    expected_hash = str(plan.get("source_pdf_sha256") or "").strip()
    if mode == "article":
        if source_pdf is None or not source_pdf.is_file():
            errors.append("article deck requires an existing source_pdf")
        elif not expected_hash:
            errors.append("article deck requires source_pdf_sha256")
        elif _sha256(source_pdf) != expected_hash:
            errors.append("source PDF hash does not match deck plan")

        journal_path = source_journal_club or (
            Path(str(plan.get("source_journal_club")))
            if plan.get("source_journal_club")
            else None
        )
        if journal_path is None or not journal_path.is_file():
            errors.append("article deck requires an existing source Journal Club dossier")
        else:
            meta = parse_frontmatter(journal_path.read_text(encoding="utf-8"))
            if meta.get("skill") != "journal-club":
                errors.append("source dossier is not a journal-club artifact")
            if meta.get("source_package_status") != "complete":
                errors.append("source dossier package is not complete")
            if str(plan.get("source_journal_club") or "") != str(journal_path):
                errors.append("deck plan source_journal_club does not match validated dossier")

    result = GuardResult(str(deck), errors=errors)
    result.metrics = {
        **pptx,
        "planned_slide_count": len(slides),
        "main_slide_count": main_count,
        "substantive_main_slide_count": substantive_main_count,
        "meaningful_visual_main_slide_count": meaningful_visual_main_count,
        "layout_family_counts": dict(layout_counts),
        "backup_slide_count": backup_count,
        "main_timed_seconds": main_seconds,
        "asset_count": len(assets),
        "result_check_count": len(plan.get("result_checks") or []),
        "coverage_critical_item_count": len(
            (plan.get("coverage_audit") or {}).get("critical_items") or []
        ),
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate /grand-rounds deck packages")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--deck", required=True)
    validate.add_argument("--plan", required=True)
    validate.add_argument("--assets", required=True)
    validate.add_argument("--visual-qa", required=True)
    validate.add_argument("--source-journal-club")
    validate.add_argument("--json", action="store_true")
    template = sub.add_parser("visual-qa-template")
    template.add_argument("--slide-count", type=int, default=0)
    args = parser.parse_args(argv)

    if args.command == "visual-qa-template":
        print(json.dumps(visual_qa_template(slide_count=args.slide_count), indent=2))
        return 0

    result = validate_package(
        deck=Path(args.deck),
        plan_path=Path(args.plan),
        assets_path=Path(args.assets),
        visual_qa_path=Path(args.visual_qa),
        source_journal_club=(
            Path(args.source_journal_club) if args.source_journal_club else None
        ),
    )
    print(json.dumps(result.to_dict(), separators=(",", ":")))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
