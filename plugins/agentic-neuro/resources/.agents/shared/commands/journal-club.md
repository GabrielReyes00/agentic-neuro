# Journal Club

Build a source-faithful, PGY-1-accessible dossier from a peer-reviewed
neurosurgery article. The endpoint is the ability to explain the clinical
problem, decisive data, context, interpretation-changing limitations, and a
calibrated practice consequence. This workflow creates no slides; a requested
deck routes to Grand Rounds.

## Authority And Posture

Load by phase:

- `journal-club-analysis.md` — complete source inspection, article/result maps,
  clinical teaching, methodological triage, and context;
- `journal-club-artifact.md` — dossier, provenance, guard, and optional mastery;
- `.agents/shared/commands/vault-intelligence.md` — supplemental personal context;
- `concept-extraction.md` — optional novel concepts after validation;
- learning/memory/Anki modules only after Gabriel opts into assessed mastery.

Paper content outranks appraisal terminology. Assume strong medicine but no
paper-specific knowledge. Preserve technical depth in dependency order and
translate unfamiliar concepts at first use. Surface only methodological defects
that change interpretation, applicability, or faculty defense. Distinguish
reported facts, calculations, and external context at the claim. Never invent a
source detail. Artifact generation is not mastery and creates no passive Anki.

## 1. Intake And Source Package

Accept a PDF plus optional supplement, assignment, or focus. Proceed without a
question when paths are readable; ask only if a missing choice materially
changes the product. A DOI/URL without complete lawful full text supports a
preliminary analysis, never a PDF-verified dossier.

Derive a recognizable Title Case short article title. Destinations:

```text
Journal Club/<Short Article Title>.md
Journal Club/Sources/<Short Article Title>.pdf
```

If the note exists, read it completely and regenerate in place while preserving
user-authored additions. Never create a dated or version-suffixed duplicate.
Workflow state lives under `$RUN_DIR/`.

Follow `journal-club-analysis.md` to inspect every PDF page textually and
visually and build:

- `source_manifest.json`: identity, hash, pages, supplement/protocol/registry
  availability, extraction warnings, and package status;
- `article_map.json`: question, architecture, population, interventions,
  comparators, endpoints, methods, flow, funding, and author conclusion;
- `result_ledger.json`: denominator-aware effect, uncertainty, source location,
  reported/calculated status, and interpretation;
- `context_sources.jsonl`: normalized external context sources;
- `quality_audit.json`: final gate evidence.

These recovery artifacts stay out of the learner-facing transcript.

## 2. Context And Analysis

Recall related vault context only when it improves foundation, literature
lineage, comparison, or faculty defense:

```bash
python3 src/vault_retriever.py recall "<topic intervention comparator controversy>" --task journal-club --limit 8
```

The article remains primary. For stable background, follow
`.agents/shared/commands/rag-routing.md`: named systems use Mini-RAG; one
synthesis uses scalar full RAG; independent syntheses use one batch. Use current
primary literature, guidelines, registries, and publisher sources for
source-sensitive context. Separate publication-era knowledge from current
knowledge.

Follow `journal-club-analysis.md` in this dependency order:

```text
clinical problem → anatomy/pathophysiology → existing management → unresolved
question → study architecture → decisive results → validity → consequence
```

For a genuinely unfamiliar technical concept, give its precise term,
plain-language meaning, and why it changes this paper's interpretation. Do not
turn ordinary vocabulary into a repetitive template.

## 3. Draft, Install, And Validate

Follow `journal-club-artifact.md`; draft to
`$RUN_DIR/draft.md`. Install and validate through:

```bash
python3 src/journal_club_guard.py install --draft "$RUN_DIR/draft.md" --title "<Short Article Title>" --source-pdf "<article.pdf>" --overwrite --json
python3 src/journal_club_guard.py validate "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Journal Club/<Short Article Title>.md" --json
```

Without a local full text, omit `--source-pdf` and set package status to
`preliminary` or `incomplete`. Repair guard failures yourself and reinstall.
Confirm index regeneration and vault-library refresh. Run concept extraction
only for 0–5 genuinely novel reusable concepts; merge reviewed existing concepts
rather than overwriting them silently. Remove only workflow-owned transient
files.

## 4. Optional Mastery

After validation, offer Guided Mastery, Faculty Defense, Combined Preparation,
or Offline Review. Do not start learning bookkeeping until Gabriel opts in.
Assessed modes use `--skill journal-club`, the installed dossier as `--doc`, and
the shared study/memory/Anki modules. Only evaluated answers can change learner
state or create cards.

## Completion And Failure Boundaries

Completion requires full available source inspection, source-located
denominator-aware decisive results, clinical foundation, in-place technical
translation, consequence-framed limitations, separated publication-era/current
context, a population-bounded practice verdict, article-specific faculty
defense, and a passing real-vault guard.

OCR or visually inspect image-only pages; stop if affected-page fidelity remains
unsafe. Mark missing supplements/protocols and current-context failures. A
preliminary brief must remain visibly preliminary. Preserve an unavailable Anki
queue after opted-in mastery and report the blocker only after session closure.
