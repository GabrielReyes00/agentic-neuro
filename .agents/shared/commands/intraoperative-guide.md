# Intraoperative Guide

Create a durable, source-grounded operative rehearsal guide that lets a
neurosurgery resident plan, mentally execute, defend, and recover from a
procedure from indication through postoperative surveillance. This is a
reference-generation workflow, not a brief bedside consult.

## Standalone Preoperative Readiness Standard

Do not claim an unverifiable percentage of “mastery.” A guide is ready only when
a resident using it can:

- explain pathology, natural history, indication, timing, and alternatives;
- interpret the imaging and patient modifiers that change the plan;
- prepare the room, positioning, equipment, anesthesia, and monitoring;
- narrate each operative phase with landmarks, rationale, danger anatomy, and
  endpoint criteria;
- anticipate bleeding, signal change, lost planes, failed exposure, hardware or
  device problems, and executable bail-outs;
- connect postoperative findings to the operative step that may have caused
  them; and
- defend approach selection, evidence limits, complications, and conversion or
  abort thresholds under attending questioning.

The Coverage Matrix built during decomposition is the procedure-specific
readiness checklist. Every applicable block must be satisfied or explicitly
marked not applicable with a reason. Length and query count are not substitutes
for conduct-changing coverage.

## Modular Authority

Load only the module needed at each checkpoint:

- `intraoperative-guide-decomposition.md`: Coverage Matrix and research plan
- `intraoperative-guide-crosslinks.md`: verified vault relationships
- `.agents/shared/commands/rag-routing.md`: smallest sufficient textbook
  retrieval tier
- `intraoperative-guide-research.md`: source cards and coverage ledger
- `intraoperative-guide-knowledge-map.md`: structured operative mental model
- `intraoperative-guide-map-review.md`: independent map review
- `intraoperative-guide-synthesis.md`: readable guide drafting
- `intraoperative-guide-review.md`: independent semantic/provenance review
- `intraoperative-guide-gap-repair.md`: bounded repair and escalation
- `intraoperative-guide-finalize.md`: verdict, validation, and installation
- `intraoperative-guide-attending-bank.md`: optional applicability-filtered
  attending-question bank

Shared learner memory, artifact, vault, concept, and Anki behavior remains owned
by `memory-operations.md`, `vault-intelligence.md`, `review-artifacts.md`,
`concept-extraction.md`, and the Anki contracts. Do not restate those schemas in
runtime wrappers.

## Independent Review

Intermediate and complex guides require two reviews independent from the writer:

1. map completeness before prose synthesis;
2. expert completeness and provenance before installation.

Prefer a separate reviewer subagent when the runtime supports one. Otherwise use
a fresh-context independent reviewer pass that receives only the named handoff
artifacts and records `reviewer_role: independent_fresh_context`. Never silently
substitute an ordinary same-context self-edit. Simple procedures may use a
single rubric-driven self-review when the verdict records the justification.

Independent review is intended to find real conduct-changing defects. Reviewers
must not manufacture a minimum number of gaps or questions.

## Complexity And Research Scale

Classify the procedure as simple, intermediate, or complex to set context and
repair budgets, not arbitrary evidence quotas:

- **Simple:** up to two review cycles; focused evidence for sequence,
  anatomy-risk, and complications.
- **Intermediate:** up to three review cycles; add setup/anesthesia/monitoring,
  outcomes, and patient-modifier evidence where decision-relevant.
- **Complex:** up to five review cycles; broaden anatomy, alternatives, rescue,
  outcomes, and current evidence across every unresolved Coverage Matrix block.

Plan one retrieval question per unresolved decision or coverage target. Use one
Mini-RAG batch for independent compact lookups and one full-RAG batch for two or
more independent synthesis questions. Current literature is mandatory when
outcomes, devices, guidelines, timing, or comparative strategy can change
conduct—not merely because a procedure was labeled intermediate or complex.

Canonical research handoff:

- `source_cards.jsonl`
- `coverage_ledger.json`
- `research.json`

A Markdown research brief is optional and limited to source mix, limitations,
and unresolved questions. Pass structured cards and stable IDs forward, not raw
retrieval dumps.

## Setup

1. Resolve a Title Case procedure title and create
   `data/Sessions/<Title>/verdicts/`.
2. If an existing guide is present, read it completely. Regeneration updates it
   in place while preserving nonduplicative user-authored material.
3. Run topic-scoped learner recall only when it will help identify known
   weaknesses; the future guide path is not a document-startup target.
4. Query prior vault context when useful:

   ```bash
   python3 src/vault_retriever.py recall "<procedure and anatomy>" --task operative-rehearsal --limit 8
   ```

   Vault context supports crosslinks and personalized emphasis. It does not
   replace operative reasoning or formal evidence.

## Checkpoints

1. **Decompose:** build the Coverage Matrix and `decomposition.json`.
2. **Research:** produce source cards, coverage ledger, and `research.json`.
3. **Map:** build `knowledge_map.json` with step-rationale and anatomy-risk
   relationships.
4. **Review map:** write the latest `map-review-cycle-<N>.json`; synthesis waits
   for `MAP_APPROVED`.
5. **Synthesize:** write the guide from the approved map and source layer.
6. **Review guide:** write `expert-review-cycle-<N>.json`; installation waits for
   `APPROVED` unless the user explicitly authorizes an incomplete artifact.
7. **Repair:** revise only named gaps, updating the map first when the missing
   structure is upstream of prose.
8. **Finalize:** verify the verdict chain, validate, install, index, and report.

Retain compact verdict JSON under `data/Sessions/<Title>/verdicts/` as the audit
trail. Reviewer handoffs contain only verdict, gaps, repair paths, applicable
question IDs, coverage, and rationale.

## Quality Invariants

- Every operative phase carries: goal → maneuver → why this technique → danger
  structure or failure mode → consequence if wrong → endpoint or next phase.
- Anatomy includes spatial location, function/supply, vulnerability, injury
  signature, avoidance, and rescue when relevant.
- Bail-outs are executable actions, not “be careful” or “call for help.”
- Hemostasis identifies predictable sources, control points, agents, and crisis
  sequence.
- Anesthesia and monitoring state modality/target, communication point, and
  response to deviation—or explain why they are not used.
- Postoperative surveillance links findings and imaging to operative causality.
- Evidence claims preserve population, intervention, effect, limitation, and
  freshness boundaries.
- No arbitrary counts of steps, instruments, citations, gaps, or questions.
- No decorative padding. Compact coverage is correct when a block is genuinely
  simple.

## Artifact And Provenance

The final guide has native top frontmatter, no H1, verified wikilinks, a
`## Pre-Scrub Mental Rehearsal` section when appropriate, `## Mastery
Objectives`, and `## Related In This Vault`.

Use the sanctioned RAG callout only when textbook retrieval was used. Every
source-grounded or verified claim cites its actual support. Unsourced model
knowledge is labeled `model knowledge — verify`; high-stakes specifics carry
`⚠ verify`. Never launder model knowledge through a nearby citation.

## Incomplete-Artifact Policy

The normal workflow does not install a guide with blocking gaps. If repair
budgets are exhausted, surface the unresolved gaps and evidence attempted. The
user may explicitly authorize installation for practical use; such a guide must
have `status: incomplete`, a visible `## Unresolved Or Weak Areas` section, and
must not be reported as complete or expert-approved. Otherwise defer or abort.

## Memory, Concepts, And Anki

Guide generation is not assessed mastery. Do not create learner claim state or
passive Anki cards from the artifact. Run concept extraction only for genuinely
novel reusable concepts; zero is valid.

If Gabriel later accepts operative rehearsal, log evaluated answers and create
cards only from eligible assessed exchanges. Those cards use
`Neurosurgery::Procedures::<Operative Guide Title>`.

## Completion Report

Report the guide or dry-run path, complexity, source mix, retrieval limitations,
Coverage Matrix result, reviewer roles/verdicts, repaired or unresolved gaps,
validator result, and any real vault/memory/Anki writes. Dry runs never write to
the real vault, learner memory, concepts, or Anki.
