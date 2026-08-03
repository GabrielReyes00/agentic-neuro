# Intraoperative Guide Finalization

Install only after either (a) expert review returns `APPROVED`, or (b) repair is
exhausted and Gabriel explicitly authorizes a visibly incomplete artifact. The
validator is structural and audit-oriented; it never replaces semantic review.

## Verdict Chain

Under `data/Sessions/<Title>/verdicts/`, require:

- `decomposition.json` with `coverage_matrix_complete: true`;
- `research.json` with `coverage_gate_met: true` (legacy
  `minimum_floor_met` remains readable) or named justified shortfalls; if
  `current_evidence_required: true`, a complete guide also requires
  `current_evidence_source_present: true`;
- `coverage_ledger.json` in the parent session directory, with each applicable
  block covered, justified internal-only, or transparently unresolved;
- latest `map-review-cycle-<N>.json` with `MAP_APPROVED`;
- latest `expert-review-cycle-<N>.json` and one matching
  `gap-repair-cycle-<N>.json` for every revision cycle.

Normal installation requires the latest expert verdict `APPROVED` and no
blocking ledger gap.

Incomplete installation requires latest verdict `REVISION REQUIRED`,
frontmatter `status: incomplete`, a visible `## Unresolved Or Weak Areas`, and:

`data/Sessions/<Title>/verdicts/incomplete-authorization.json`

```json
{
  "authorized": true,
  "authorized_by": "user",
  "authorization_context": "Why a limited artifact is useful now",
  "unresolved_gap_ids": ["CM-07"]
}
```

Every latest expert blocking gap must be represented by Coverage Matrix block ID
(or rubric block when no matrix ID exists). Never create this authorization from
silence, inferred urgency, or the agent's preference. An incomplete guide is not
complete or expert-approved.

## Preflight And Target

Parse only the YAML block opening on line 1. Require native frontmatter with
canonical domain, complexity, one-line summary/provenance, and
`internal_knowledge_used`; no
H1; verified wikilinks; Mastery Objectives; Related In This Vault; and
Pre-Scrub Mental Rehearsal for intermediate/complex procedures.

Write real guides only to:

`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/<Title>.md`

Dry runs use `data/Sessions/<Title> Dry Run.md` and make no vault, concept,
learner-memory, or Anki write.

## Validation And Installation

Normal:

```bash
python3 src/operative_guide_validator.py "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/<Title>.md"
```

Explicitly authorized incomplete:

```bash
python3 src/operative_guide_validator.py --allow-incomplete "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/<Title>.md"
```

Repair only the named structural issue and rerun; do not change expert-reviewed
substance to game a guard. Extract every wikilink and confirm an exact vault note
target; otherwise use plain text. Related In This Vault includes only verified,
explained relationships.

After a real pass:

1. Regenerate `Operative Guides/INDEX.md` through `src/index_builder.py`.
2. Run 0–5 novel concept promotions under `concept-extraction.md`; zero is valid
   and reviewed merges require explicit overwrite flags.
3. Refresh the vault library and require zero integrity failures.
4. Do not log artifact generation as learner mastery or create passive Anki.
   Later evaluated rehearsal may use `Neurosurgery::Procedures::<Title>`.

## Audit And Cleanup

Retain the verdict directory by default as the reproducibility record. Remove
only workflow-owned scratch files listed in the session manifest, only after a
successful real install; never glob or delete the whole Sessions tree. Preserve
dry-run/debug artifacts when needed for inspection.

For calibration runs, write `token_ledger.json` with estimated tokens for raw
retrieval, source cards, coverage ledger, map, verdicts, active downstream
context, and final guide. This is telemetry, not a quality gate.

## Completion Report

Report the real/dry-run path; complexity and Coverage Matrix result; source mix
and limitations; reviewer roles/cycles/final verdict; repaired and unresolved
gaps; validator and vault-integrity results; wikilinks/concepts added; whether
any memory/Anki writes occurred; retained verdict path; and token telemetry when
collected. Label incomplete artifacts prominently.
