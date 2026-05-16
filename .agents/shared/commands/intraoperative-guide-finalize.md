# Intraoperative Guide Finalization Module

Use this module only after expert completeness review returns `APPROVED`.

## Purpose

Install the approved guide, run deterministic validation, and complete shared learning-system bookkeeping without altering the expert-approved substance except to fix validation failures.

## Verdict Chain Gate (machine-readable enforcement)

Before any write, confirm the verdict chain is complete and consistent. The finalize module **must not** advance unless every required verdict JSON exists, is well-formed, and carries an approving verdict where applicable.

Required files under `data/Sessions/<Title>/verdicts/`:

1. `decomposition.json` — `coverage_matrix_complete: true`.
2. `research.json` — `minimum_floor_met: true` (or every shortfall has a recorded internal-knowledge justification). For intermediate and complex procedures, `frontier_outcomes_query_present: true` is also required; if false, the workflow must return to the research checkpoint and run at least one outcomes query without `--no-frontier` before finalization can proceed. This is a gate, not a flag.
3. `coverage_ledger.json` — present at `data/Sessions/<Title>/coverage_ledger.json`, every required block has `status: covered` or a recorded `internal_only` justification, and no block has `review_status: gap` in the latest ledger.
4. `map-review-cycle-<N>.json` — most recent cycle has `verdict: "MAP_APPROVED"`.
5. `expert-review-cycle-<N>.json` — most recent cycle has `verdict: "APPROVED"`.
6. `gap-repair-cycle-<N>.json` — present for every cycle where expert review returned `REVISION REQUIRED`. The final gap-repair cycle must not have `user_escalation_required: true` unless the user has explicitly authorized shipping with labeled gaps.

Run a verdict-chain check before writing:

```bash
cd /Users/gabrielreyes/agentic-neuro && \
ls "data/Sessions/<Title>/verdicts/" 2>/dev/null
```

If any required verdict file is missing, the workflow is incomplete. Do **not** write the real vault, memory, concepts, or Anki artifacts. Surface the missing verdict to the user and return to the appropriate checkpoint.

## Preconditions

- The verdict chain above is complete.
- Every wikilink in the guide was verified against the real vault scan.
- The guide has no H1 and no top YAML.
- Bottom YAML metadata is present.
- `## Mastery Objectives` and `## Related in This Vault` are present before bottom YAML.
- `## Pre-Scrub Mental Rehearsal` is present near the end of the guide for intermediate and complex procedures.

## Write Target

Write the guide to:

```text
/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/<Title>.md
```

If this is a dry run, do not write to the real vault. Use `data/Sessions/<Title> Dry Run.md` and clearly report that no real vault, memory, or Anki writes occurred.

Before writing, confirm the destination is exactly under `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/`. Do not write real guides into repo-local shadow paths.

## Deterministic Validation

Run:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/operative_guide_validator.py "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/<Title>.md"
```

For dry runs, validate the dry-run path instead.

If validation fails, revise only the issue needed to satisfy the guard, then rerun validation. Do not use the validator as a substitute for expert review.

The validator also rejects unverified wikilinks when the Obsidian vault is available. If it reports broken wikilinks, remove the link syntax or replace the target with an exact verified note title.

## Index, Concepts, Memory, and Anki

For real runs:

1. Update `Operative Guides/INDEX.md`.
2. Extract 2-5 atomic concepts worth future review.
3. Log the guide to memory using the shared learning-session contract.
4. Queue Anki cards only when durable spaced-repetition facts are present.

Operative-guide Anki cards are a deck-routing exception. Every card generated from this guide must use:

```text
Neurosurgery::Procedures::<Title>
```

Do not scatter operative-guide cards into ordinary domain decks.

For dry runs:

- Do not update vault indexes.
- Do not extract/write concept stubs.
- Do not log memory.
- Do not create or flush Anki cards.

## Wikilink Verification

Before final validation, verify all wikilinks:

- Extract every `[[...]]` target from the guide.
- Confirm the target title exactly matches a `.md` filename from the vault scan, without the `.md` suffix.
- Remove or rewrite any unverified wikilink as plain text.
- Ensure `## Related in This Vault` lists only verified targets and explains why each is relevant.

## Scratch Cleanup

For real runs, delete or discard temporary workflow ledgers, decomposition notes, research briefs, operative knowledge maps, expert review memos, and gap-repair memos before skill execution concludes unless Gabriel explicitly asks to preserve them. These files are workflow scaffolding, not vault artifacts.

**Retain the `data/Sessions/<Title>/verdicts/` directory by default**, even on real runs, until Gabriel confirms cleanup. The verdict chain is the reproducibility audit trail. If Gabriel asks to delete it, do so explicitly; otherwise leave it in place for inspection.

For dry runs or explicit debugging, preserve the dry-run guide and workflow ledger in `data/Sessions/` so output quality and agent behavior can be inspected.

## Token Ledger

For dry runs and workflow-calibration runs, write a compact token ledger:

```text
data/Sessions/<Title>/token_ledger.json
```

At minimum record estimated tokens (`chars/4`) for raw RAG audit files, source cards, coverage ledger, knowledge map, reviewer verdicts, final guide, downstream active context excluding raw RAG, and all artifacts including raw audit. This ledger is not a quality gate, but it makes optimization regressions visible.

## User-Facing Summary

Report:

- Final file path or dry-run path.
- Source mix and per-domain retrieval count.
- Source-card path and whether raw retrieval dumps were only retained for audit.
- Coverage-ledger path and whether structured IDs/pointers were used instead of prose handoffs.
- Whether context budgets were followed or intentionally exceeded, with the reason.
- Procedure complexity.
- Verdict chain summary: decomposition complete, research floor met (or justified shortfalls), map-review cycles and final verdict, expert-review cycles and final verdict, gap-repair cycles.
- Whether targeted RAG or PubMed gap repair was needed, and which escalation rules (if any) fired.
- Validator result.
- Wikilinks added or reason none were added.
- Whether vault/memory/Anki writes were performed.
- Coverage Matrix blocks satisfied / total.
- Any intentionally omitted or compact-only blocks and the recorded justification.
- Path to the verdict chain directory.
- Token-ledger summary for dry runs or calibration runs.
