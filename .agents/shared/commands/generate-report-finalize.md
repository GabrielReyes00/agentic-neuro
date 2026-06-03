# Generate Report Finalize

Use this module after `report_knowledge_map.json` is complete.

## Purpose

Write, validate, and persist the final report from structured synthesis artifacts.

Inputs:

- `report_research_plan.json`
- `source_cards.jsonl`
- `coverage_ledger.json`
- `report_knowledge_map.json`
- verified vault crosslinks

## Drafting Rule

Write the report from `report_knowledge_map.json`, consulting source-card rows only for exact citation details, numbers, limitations, or wording-sensitive claims. Do not draft directly from raw RAG output.

The final report must still satisfy the main `generate-report.md` Quality Contract: encyclopedic density, citations at point of claim, provenance tiering, key numbers, differentiators, failure modes, evidence quality labels, effect sizes, Mastery Objectives, and verified wikilinks.

Structured artifacts are guardrails, not a compression mandate. If the map is too thin to support a clinically dense reference, return to synthesis or research instead of writing a sparse report.

## Internal Artifact Boundary

Research artifacts are internal production scaffolding, not report content. Do not mention `source_cards.jsonl`, query rewriting, coverage ledgers, gap repair, raw-source audit, validators, RAG mechanics, or repo workflow details inside the final clinical report. The report may include a brief sanctioned `> [!info] RAG Supplemented` callout when RAG was used, but the body must read as a clinical reference chapter, not a provenance memo.

Bottom YAML is also part of the final report artifact. Do not put `provenance`, `internal_knowledge_used`, source-card counts, query counts, validator status, or workflow summaries in YAML. Keep workflow provenance in session artifacts and in the user-facing completion summary, not in the clinical note.

Use validation work to improve the clinical content silently:

- Turn raw-source audit into stronger cited clinical claims, not a paragraph about the audit.
- Turn coverage-ledger gaps into additional clinical sections, tables, or caveats, not "gap repaired" notes.
- Turn source-card limitations into better citation tiering or explicit evidence-quality labels, not comments about card compression.
- Preserve or expand clinical physiology, ICU metrics, failure modes, operative decision points, and study-guide density when adding validation controls.

## Clinical Report Product Standard

The final report is a clinical reference and study guide. It should read like the best v1-style output: dense, specific, usable on service, and explicit about physiology, decision points, evidence strength, and failure modes. Do not trade away bedside utility for workflow tidiness.

Before validation, self-audit the draft against the topic's natural demands:

- ICU or emergency topics need bedside monitoring parameters, escalation triggers, lesion-level physiology, and predictable failure modes.
- Operative topics need anatomy-risk relationships, approach logic, key maneuvers, bailout thinking, and complication mechanisms.
- Pathophysiology-heavy topics need mechanism-to-consequence chains that connect biology to exam findings, imaging, treatment, prognosis, or complications.
- Controversy-heavy topics need evidence strength, effect sizes when available, population boundaries, and practical interpretation.
- Broad clinical topics need enough differentiators that a reader can separate neighboring diseases, mimics, and management pathways.

If the report reads like an operational checklist or thin summary when the topic warrants a reference chapter, it is incomplete even if the structural validator passes.

## Coverage Ledger Gate

Before writing final prose, inspect `coverage_ledger.json`. If any required block has `status: gap`, stop and return to `generate-report-research.md` for targeted repair. Do not write a final report with known required coverage gaps.

After writing the report, run:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/report_validator.py \
  "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/<Title Case Title>.md" \
  --coverage-ledger "data/Sessions/<Title>/coverage_ledger.json"
```

The validator is a structural and ledger gate, not a substitute for agent self-audit. Passing validation does not prove citation adequacy or expert completeness; failing validation means the report is not complete.

## Finish Steps

1. Write `Reports/<Title Case Title>.md`. Ensure its bottom YAML carries `domain:` (one or more canonical slugs: vascular, skull-base, tumor, spine, trauma, neurocritical-care, functional, pediatric, peripheral-nerve, anatomy, general) and a one-line `summary:`; add `display:` if a shorter index title is wanted.
2. Run `report_validator.py` with `--coverage-ledger`.
3. Regenerate the domain-grouped index: `python3 src/index_builder.py Reports`.
4. Extract 2-5 concept stubs when appropriate per `.agents/shared/commands/concept-extraction.md`.
5. Log the report anchor to memory with `skill="generate-report"`.
6. Surface to the user: TL;DR, file path, source mix, Quality Contract result, coverage-ledger result, validator result, and wikilinks added.

Keep `data/Sessions/<Title>/coverage_ledger.json`, `source_cards.jsonl`, and `report_knowledge_map.json` during generation. Clean up only transient raw retrieval dumps unless the user asks to preserve the session artifacts.
