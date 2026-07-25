# Journal Club

Build a source-faithful, intern-accessible mastery dossier from a peer-reviewed
neurosurgery article. The endpoint is not a generic summary or a reporting-
checklist audit. The endpoint is a resident who can explain the paper, state its
decisive data, place it in neurosurgical context, critique the limitations that
actually matter, and defend a calibrated conclusion before residents and faculty.

This workflow does not create slides. `/grand-rounds` remains the presentation-
deck workflow; integration between the two workflows is a later concern.

## Modular Authority

Read the focused modules when their phase begins:

- `.agents/shared/commands/journal-club-analysis.md` — PDF/source-package
  inspection, article mapping, teaching posture, result reconstruction,
  design-aware methodological triage, and external context.
- `.agents/shared/commands/journal-club-artifact.md` — final dossier structure,
  provenance syntax, quality gate, installation, and optional mastery modes.
- `.agents/shared/commands/vault-intelligence.md` — personalized vault context.
- `.agents/shared/commands/concept-extraction.md` — optional post-write concept
  cards.
- For an opted-in mastery session only: `memory-operations.md`,
  `memory-retrieval.md`, `adaptive-teaching-doctrine.md`,
  `anki-session-workflow.md`, and `anki-card-quality.md`.

Do not preload the learning-session modules during passive article analysis.

## Invocation

```text
/journal-club --pdf "<article.pdf>" [--supplement "<supplement.pdf>"] \
  [--assignment "<faculty prompt or reason assigned>"] \
  [--focus "<specific controversy or question>"]
```

Natural-language triggers include:

- "Help me understand this paper for journal club."
- "Break down this article before I present it."
- "Prepare me to defend this neurosurgery paper."
- "Create a journal-club dossier from this PDF."

If a DOI or URL is supplied without the PDF, perform only a preliminary analysis
unless a complete lawful full text can be retrieved. Never label abstract-only or
HTML-snippet analysis as PDF-verified.

## Core Posture

1. **Paper first.** Neurosurgical content, results, interpretation, and clinical
   relevance outrank formal appraisal vocabulary.
2. **Assume no paper-specific prior knowledge.** Gabriel is medically literate
   and entering neurosurgery internship, but may be new to the pathology,
   procedure, literature lineage, outcome instruments, and statistical methods.
3. **Preserve technical completeness.** Do not omit or dilute difficult content.
   Introduce it in dependency order and translate it at first use.
4. **Appraise quietly.** Use study design internally to select validity checks.
   Surface only flaws that change interpretation, applicability, or likely faculty
   discussion. Never produce a compliance score or checklist recital.
5. **Separate provenance.** Distinguish article-reported facts, agent calculations,
   and external context at the point of claim.
6. **Artifact is not mastery.** Writing the dossier creates no learner-state
   evidence and no Anki cards. Only evaluated answers in an explicitly accepted
   mastery mode may update learner memory.
7. **No invented source detail.** Missing supplements, inaccessible protocols,
   absent denominators, and uncertain claims remain explicit limitations.

## Phase 0: Intake And Scope

If the PDF path is present and readable, proceed without a questionnaire. Parse
the user's assignment, attending angle, focus, and supplied supplements silently.
Ask one concise question only when a missing choice would materially change the
analysis.

Derive a concise Title Case article title for the artifact. Use the article's
recognizable short title, not a date, workflow prefix, or author name. The final
destinations are:

```text
Journal Club/<Short Article Title>.md
Journal Club/Sources/<Short Article Title>.pdf
```

If the note already exists, ask before replacing it. Treat a same-title run as an
in-place regeneration, never as `_v2` or a date-stamped copy.

Create workflow scaffolding under:

```text
data/Sessions/journal_club_<slug>/
```

Keep raw extraction and workflow state there, not in final YAML.

## Phase 1: Source Package

Read `journal-club-analysis.md` and build:

1. `source_manifest.json` — article identity, file hash, PDF page count,
   supplement/protocol/registry availability, OCR or extraction warnings, and
   source-package status.
2. `article_map.json` — clinical question, study architecture, population,
   intervention/exposure, comparator, endpoints, methods, participant flow,
   funding, and authors' conclusion.
3. `result_ledger.json` — denominator-aware results with effect magnitude,
   uncertainty, location, reported-versus-calculated status, and interpretation.
4. `context_sources.jsonl` — normalized external sources used for the clinical
   foundation, publication-era landscape, and current context.
5. `quality_audit.json` — pass/fail evidence for the final quality gate.

These are internal recovery and reasoning artifacts. Do not paste them into the
learner-facing transcript.

## Phase 2: Personalized And Formal Context

Scan the vault for related notes and verified wikilink targets. Use field-aware
recall when it can improve foundational teaching, literature lineage, evidence
comparison, or anticipated faculty questions:

```bash
python3 src/vault_retriever.py recall \
  "<article topic, intervention, comparator, and controversy>" \
  --task journal-club --limit 8
```

The selected article remains primary. Vault context is supplemental and cannot
replace the paper or formal verification.

Use textbook RAG selectively for stable foundation, anatomy, mechanisms, and
classic management:

```bash
python3 src/lance_retriever.py compare \
  "<pathology anatomy treatment landscape query>" --stdout --no-frontier
```

Use current primary literature, formal guidelines, trial registries, and publisher
materials for source-sensitive context. Separate what was known when the study was
performed or published from what is known now. Do not use subsequent evidence to
pretend the authors should have known the future.

## Phase 3: Analysis And Teaching Synthesis

Follow `journal-club-analysis.md` completely. Build understanding in this order:

```text
Clinical problem
-> relevant anatomy/pathophysiology
-> existing management
-> unresolved question
-> study architecture
-> decisive results
-> interpretation and validity
-> neurosurgical consequence
```

For unfamiliar technical material, teach in place:

```markdown
**Technical concept:** <precise term>
**Plain-language meaning:** <accurate translation>
**Why it matters here:** <effect on this paper's interpretation>
```

Use the triplet where it materially reduces cognitive load; do not mechanically
repeat it for ordinary vocabulary.

## Phase 4: Draft, Validate, And Install

Read `journal-club-artifact.md`. Draft to:

```text
data/Sessions/journal_club_<slug>/draft.md
```

Install and validate the real vault artifact through the deterministic guard:

```bash
python3 src/journal_club_guard.py install \
  --draft "data/Sessions/journal_club_<slug>/draft.md" \
  --title "<Short Article Title>" \
  --source-pdf "<article.pdf>" \
  --json

python3 src/journal_club_guard.py validate \
  "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Journal Club/<Short Article Title>.md" \
  --json
```

When the source package has no local PDF, omit `--source-pdf` and ensure the note
states `source_package_status: preliminary` or `incomplete`. Never set
`source_package_status: complete` without a locally inspected full text.

If validation fails, repair the draft and rerun installation. Do not ask Gabriel
to debug formatting, missing provenance, or structural gaps.

After installation:

1. Confirm `Journal Club/INDEX.md` was regenerated.
2. Confirm the vault intelligence refresh succeeded or surface a concise warning.
3. Extract 2-5 reusable concept cards only when genuinely useful, following
   `concept-extraction.md`.
4. Remove only workflow-owned transient files when no longer needed. Preserve the
   installed note and copied source PDF.

## Phase 5: Optional Mastery

After the dossier passes validation, offer exactly these choices:

- **Guided Mastery** — build the paper from clinical problem through practice
  consequence.
- **Faculty Defense** — adversarial questions on data, limitations, and clinical
  interpretation.
- **Combined Preparation** — Guided Mastery followed by Faculty Defense.
- **Offline Review** — stop after artifact creation.

Do not begin learning-session bookkeeping unless Gabriel opts in. When he does,
follow `journal-club-artifact.md` and the shared learning modules with
`--skill "journal-club"` and `--doc "Journal Club/<Short Article Title>.md"`.

## Completion Standard

The workflow is complete only when:

- The complete available source package was inspected visually and textually.
- Every decisive result is denominator-aware and source-located.
- Intern-level clinical foundation and in-place technical translation are present.
- Only interpretation-changing limitations are emphasized.
- Publication-era and current context are separated.
- The practice verdict names its population and evidentiary boundary.
- The faculty-defense material is specific to the article.
- The real vault note passes `journal_club_guard.py validate`.
- Artifact creation has not been mislabeled as demonstrated mastery.

## Failure Handling

- **Unreadable or image-only PDF:** run OCR or visual extraction; if fidelity
  remains inadequate, stop and identify the affected pages.
- **Missing supplement/protocol:** continue only if the main paper supports a
  responsible analysis; mark exactly what cannot be verified.
- **No full text:** produce a clearly labeled preliminary brief, not a complete
  dossier.
- **External research failure:** keep the article analysis, mark current-context
  gaps, and never fabricate sources.
- **Guard failure:** repair and revalidate before claiming completion.
- **Anki unavailable during opted-in mastery:** preserve the queue and report the
  blocker after session finalization.
