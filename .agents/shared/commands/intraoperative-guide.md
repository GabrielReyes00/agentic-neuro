# Intraoperative Guide

Produce a complete, source-grounded operative rehearsal manual for a neurosurgical procedure. The output should let a neurosurgery resident mentally perform the operation from indication and setup through closure, immediate postoperative surveillance, complication recognition, and failure recovery.

This command is closer to `/generate-report` than to `/consult`: the artifact is a durable standalone operative reference, not a brief teaching exchange. The agent is the intelligence layer. Scripts retrieve sources, validate structure, and record memory; they do not write or reason for the agent.

Follow `.agents/shared/commands/learning-session-contract.md` for shared memory, artifact, concept, and Anki behavior unless this contract is more specific.

The deterministic validator is necessary but never sufficient. A guide may pass validation and still fail this workflow if expert completeness review does not approve it as a standalone operative reference.

## Depth Target: 85% Resident Mastery

Every guide must contain enough material that a neurosurgery resident studying *only* this document achieves roughly **85% of the deep understanding** needed to perform and defend the procedure. The remaining 15% comes from hands-on cadaver/OR exposure and procedure-specific atlas figures.

This target is operationalized by the **Coverage Matrix** built during decomposition. Every Coverage Matrix block must be addressable in the final draft. Compact treatment is acceptable when a block is genuinely simple for the procedure; silent omission is a workflow failure.

---

## Modular Workflow Authority

This file is the public command contract and orchestrator. Detailed checkpoint instructions live in focused modules. Read the relevant module freshly when reaching each checkpoint so the workflow does not drift in long contexts:

- `.agents/shared/commands/intraoperative-guide-decomposition.md` — procedure-specific topic decomposition, **Coverage Matrix**, retrieval plan, pre/intra/post-OR phase skeleton, attending-defense questions.
- `.agents/shared/commands/intraoperative-guide-crosslinks.md` — real Obsidian vault target, verified wikilink discovery, related-note placement.
- `.agents/shared/commands/intraoperative-guide-research.md` — serial RAG, per-domain retrieval matrix, source-pack extraction.
- `.agents/shared/commands/intraoperative-guide-knowledge-map.md` — operative mental model, first-principle map blocks, step-rationale chains, anatomy-risk with neurophysiologic consequence, anesthesia, neuromonitoring, hemostasis, endpoint criteria, outcomes, patient modifiers, OR team choreography.
- `.agents/shared/commands/intraoperative-guide-map-review.md` — **dedicated map-completeness reviewer subagent**, separate from the writer; required gate before synthesis.
- `.agents/shared/commands/intraoperative-guide-synthesis.md` — draft and revision writing standards aligned to the Coverage Matrix.
- `.agents/shared/commands/intraoperative-guide-review.md` — **dedicated expert completeness reviewer subagent**, separate from the writer; required gate before finalization.
- `.agents/shared/commands/intraoperative-guide-gap-repair.md` — targeted repair with cycle budget and escalation ladder.
- `.agents/shared/commands/intraoperative-guide-finalize.md` — verdict-chain enforcement, vault/dry-run write, validation, index, concepts, memory, and Anki.
- `.agents/shared/commands/intraoperative-guide-attending-bank.md` — curated procedure-family pimping question bank used by the expert reviewer as an independent cross-check floor.

Do not inline or duplicate those module instructions into wrappers. Codex, Claude, and Gemini should all enter through this file and then load modules at the checkpoints.

## Mandatory Subagent Separation

Two checkpoints **require** a subagent different from the writer for intermediate and complex procedures:

- **Map-completeness review** (`intraoperative-guide-map-review.md`).
- **Expert completeness review** (`intraoperative-guide-review.md`).

If no subagent is available, the workflow halts and the limitation is surfaced to the user. Silent fall-back to self-review is a workflow failure for intermediate/complex procedures. Simple bedside procedures may use self-review against the same rubric, but the verdict JSON must record the justification.

## Verdict Chain (machine-readable audit trail)

Each checkpoint produces a verdict JSON under:

```text
data/Sessions/<Title>/verdicts/
```

Required files by the end of the workflow:

- `decomposition.json`
- `research.json`
- `map-review-cycle-<N>.json` (most recent must be `MAP_APPROVED`)
- `expert-review-cycle-<N>.json` (most recent must be `APPROVED`)
- `gap-repair-cycle-<N>.json` for every cycle where expert review returned `REVISION REQUIRED`

The finalize module reads this chain and refuses to write to the real vault unless the chain is complete and approving. Agent honesty is not the audit mechanism — the verdict files are. Retain the verdict directory after real runs by default; Gabriel may delete it explicitly when no longer needed.

## Context Budget and Compression

This workflow must not treat "deep research" as permission to keep every raw retrieval passage in the model context. Raw retrieval dumps may be retained on disk for audit, but downstream checkpoints should receive compressed artifacts unless a specific unresolved gap requires the raw text.

Default context budgets for a single-procedure run:

- **Research brief:** target 1,200-2,000 words. Include only conduct-changing extracts and compact source cards. Do not paste full RAG output into later prompts.
- **Structured source layer:** `source_cards.jsonl` and `coverage_ledger.json` are canonical. A markdown research brief is optional and should be a generated debug view, not the ordinary handoff.
- **Operative knowledge map:** prefer `knowledge_map.json` with stable block IDs and source-card pointers. Target 1,200-2,200 words equivalent for intermediate procedures and 2,200-3,800 for complex procedures. Expand only blocks that change conduct, rescue, interpretation, or attending defense.
- **Reviewer handoffs:** give reviewers the current draft or structured map plus `coverage_ledger.json`, relevant source-card rows, and the latest compact verdict summary. Do not give every raw RAG file, every source card, or every prior verdict JSON unless the reviewer asks for a narrow item.
- **Verdict handoff:** later stages consume a verdict summary (verdict, blocking gaps, repair paths, fresh questions, rationale) rather than full bank-question arrays. The full JSON remains on disk for audit.
- **Attending-bank references:** verdict JSON stores stable bank question IDs, not full question text. The bank file is canonical.
- **Gap repair:** run additional RAG/PubMed only for named blocking gaps or mandatory escalation rules. Do not run broad "make it better" retrieval after the initial research floor is met.

If a procedure would exceed these budgets, prefer a compact but complete guide plus an `Unresolved or Weak Areas` entry that triggers targeted repair. Completeness is still required, but raw context volume is not a quality metric.

---

## Role and Success Criterion

You are a senior neurosurgical fellow teaching operative mental rehearsal. Prioritize what changes conduct in the OR: action sequence, exposure logic, landmarks, anatomy-risk relationships, instrument choices, decision points, critical maneuvers, common novice errors, bail-outs, closure consequences, and postoperative signatures of intraoperative failure.

Success means the resident can:

- Explain the disease, its biomechanics or pathophysiology, and how natural history forces surgery.
- Interpret the relevant imaging and adjunct studies to decide on surgery.
- Defend approach selection against alternatives with outcomes evidence.
- Set up the room, patient, imaging, monitoring, equipment, and exposure plan.
- Coordinate the anesthetic, physiologic, and neuromonitoring strategy.
- Walk through the operation step by step with landmarks, danger zones, and **why each step occurs**.
- Name the critical technical moments and the consequence of getting each wrong.
- Execute a hemostasis strategy through every phase.
- Recover from common intraoperative problems using specific bail-outs.
- Confirm endpoint/completion criteria intraoperatively before closure.
- Recognize early postoperative complications and connect them to the operative step that caused them.
- Adapt the plan to patient-specific modifiers (host factors, anatomic variants, prior surgery).
- Defend the guide against attending-level questions about approach selection, anatomy, complications, alternatives, outcomes, and failure recovery.

---

## Complexity Routing

After resolving the procedure, classify complexity. Complexity scales retrieval floors and cycle budgets but never lowers the 85% depth target.

- **Simple bedside or minor procedure:** EVD, lumbar drain, burr-hole subdural evacuation, basic wound washout. Research floor 3 queries. Maximum 2 expert review cycles. Map-review and expert-review may be self-review with recorded justification.
- **Intermediate procedure:** ACDF, VP shunt, laminectomy, cranioplasty, routine tumor exposure. Research floor 6 queries with ≥1 frontier query. Maximum 3 expert review cycles. Map-review and expert-review subagents required.
- **Complex cranial, skull base, vascular, deformity, or endoscopic procedure:** aneurysm clipping, AVM resection, far lateral/transcondylar, petrosectomy, bypass, endonasal skull base, deformity correction. Research floor 10 queries with ≥2 frontier queries. Maximum 5 expert review cycles with escalation-ladder rules. Map-review and expert-review subagents required.

---

## Pre-Generation Setup

### Step 0: Resolve the procedure

Derive a Title Case procedure title from the user's request. If the procedure is genuinely ambiguous, ask one clarifying question. Otherwise infer the likely procedure and proceed.

If `Operative Guides/<Title>.md` already exists, treat the request as regeneration: overwrite the file in place, refresh `Operative Guides/INDEX.md`, and replace stale concept stubs only when needed. Do not create `_v2`, `(updated)`, or date-stamped variants.

Create the verdict directory at the start of the run:

```bash
cd /Users/gabrielreyes/agentic-neuro && \
mkdir -p "data/Sessions/<Title>/verdicts"
```

### Step 1: Related-memory discovery (silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py summary --topic "<procedure/topic>" --limit 8 --scaffold-limit 2 --include-curated
```

Use memory only to discover related anchors and prior weaknesses worth supporting in the guide. Do not compress or omit content because the learner may already know it.

Skip memory writes and reads for explicit dry runs unless the user asks for memory-enabled generation.

### Step 2: Vault scan for cross-citation targets (silent)

Read `.agents/shared/commands/intraoperative-guide-crosslinks.md`.

```bash
cd /Users/gabrielreyes/agentic-neuro && \
find "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides" \
     "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports" \
     "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Consults" \
     "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material" \
     "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts" \
     -maxdepth 1 -type f -name "*.md" 2>/dev/null
```

Identify real wikilink targets relevant to this operation. Use only verified filenames. Feed the most relevant candidates into decomposition, knowledge mapping, synthesis, and the final `## Related in This Vault` section.

---

## End-to-End Workflow

### Checkpoint 0: Workflow ledger

Create or maintain a scratch workflow ledger outside the final guide. For dry runs or explicit debugging, place it in `data/Sessions/<Title> Workflow Ledger.md`. For real runs, keep it in session scratch space and delete it before completion unless the user asks to preserve it. The ledger is not an Obsidian guide and must not be copied into the final artifact.

The verdict JSONs under `data/Sessions/<Title>/verdicts/` are the durable audit trail; the human-readable ledger summarizes them. Record:

- Procedure title and complexity.
- Decomposition summary, Coverage Matrix blocks planned, attending-defense questions.
- Verified wikilink candidates and selected related notes.
- Retrieval query list and per-domain coverage.
- Research limitations.
- Map-review subagent identity, cycle verdicts, and fresh attending questions used.
- Expert-review subagent identity, cycle verdicts, and fresh attending questions used.
- Blocking gaps, repair paths, escalation rules triggered.
- Final approval rationale.
- Deterministic validator result.
- Write targets and confirmation of dry-run versus real writes.
- Path to verdict directory.

### Checkpoint 1: Procedure Decomposition

Read `.agents/shared/commands/intraoperative-guide-decomposition.md`.

Build a procedure-specific decomposition before retrieval. This decomposition produces the **Coverage Matrix** that anchors the 85% depth target, the pre/intra/post-OR phase skeleton, and the per-domain retrieval plan. It also generates the writer's attending-defense questions (the reviewers will add their own fresh questions later).

Write `decomposition.json` to the verdict directory.

### Checkpoint 2: Research

Read `.agents/shared/commands/intraoperative-guide-research.md`.

Run serial domain-specific RAG retrieval according to the decomposition's per-domain retrieval matrix and produce structured source cards plus a coverage ledger. Hit the complexity-tier query floor or record an internal-knowledge justification for any unfilled block.

Subagents may be used for research extraction when available, especially to prevent context bloat. If a subagent is used:

- Give it only the procedure, complexity, decomposition, and research module.
- Let it run or specify serial retrieval only.
- Require `source_cards.jsonl`, `coverage_ledger.json`, the exact query list, and the verdict JSON. A markdown research brief is optional.
- Do not ask multiple subagents to run heavy RAG simultaneously.

If RAG retrieval fails during a real artifact request, retry conservatively. If it still fails, surface a concise warning and ask whether to proceed without RAG. Dry-run workflow tests may proceed without RAG only if clearly marked as dry runs.

Write `research.json` to the verdict directory.

### Checkpoint 3: Operative Knowledge Map

Read `.agents/shared/commands/intraoperative-guide-knowledge-map.md`.

Build the operative knowledge map from the decomposition, `source_cards.jsonl`, `coverage_ledger.json`, and internal expert knowledge. The map must cover every Coverage Matrix block. Self-triage the map before handoff.

### Checkpoint 4: Map-Completeness Review (dedicated subagent)

Read `.agents/shared/commands/intraoperative-guide-map-review.md`.

A **separate map-completeness reviewer subagent** stress-tests the map. Give the reviewer the decomposition, `coverage_ledger.json`, the structured map, relevant source-card rows, and a short verdict-chain summary; do not give raw RAG dumps by default. The reviewer surfaces ≥3 candidate gaps on cycle 1 and generates ≥3 fresh attending questions of its own. The map cannot proceed to drafting unless the reviewer writes `MAP_APPROVED`. Iterate on the map (cheap) rather than the prose (expensive).

For simple procedures, self-review against this rubric is acceptable with recorded justification in the verdict.

Write `map-review-cycle-<N>.json` to the verdict directory for each cycle.

### Checkpoint 5: First Synthesis

Read `.agents/shared/commands/intraoperative-guide-synthesis.md`.

Draft the guide from the approved operative knowledge map, not directly from raw RAG. Do not write to the real vault yet. The draft must cover every Coverage Matrix block, carry step-rationale chains in every phase, and include the consolidated Pre-Scrub Mental Rehearsal section.

### Checkpoint 6: Expert Completeness Review (dedicated subagent)

Read `.agents/shared/commands/intraoperative-guide-review.md`.

A **separate expert completeness reviewer subagent**, different from the writer and ideally different from the map reviewer, runs the post-draft semantic gate. Give the reviewer the draft, decomposition, approved map, compact research brief/source cards, and the latest verdict summary. The reviewer should write a full verdict JSON for audit, but return only the delta summary to the orchestrator unless a blocker requires more detail. The reviewer surfaces ≥3 candidate gaps on cycle 1 and generates ≥3 fresh attending questions of its own. Approval requires every rubric block satisfied, every Coverage Matrix block addressable, every fresh attending question answered, and the 85% depth target reached.

Write `expert-review-cycle-<N>.json` to the verdict directory.

### Checkpoint 7: Gap Repair Loop

If expert review returns `REVISION REQUIRED`, read `.agents/shared/commands/intraoperative-guide-gap-repair.md`.

Repair each blocking gap according to the reviewer-assigned path. Apply the **escalation ladder** when a gap repeats across cycles: cycle 2→3 forces a PubMed query; cycle 3→4 (complex only) requires map revision plus map-review rerun; cycle 4→5 escalates to the user. Cycle budgets are 2 (simple), 3 (intermediate), and 5 (complex). If budget is exhausted, escalate to user — do not write a known-incomplete real guide with a disclaimer.

Write `gap-repair-cycle-<N>.json` to the verdict directory.

For batch dry-run stress tests involving multiple procedures in one turn, explicitly label the run as a stress test in the ledger. Batch dry runs are useful for exposing workflow failure modes but should not be treated as the maximum quality expected from a real one-procedure generation.

### Checkpoint 8: Finalization

Read `.agents/shared/commands/intraoperative-guide-finalize.md`.

Before final write, reread `.agents/shared/commands/intraoperative-guide-crosslinks.md` and verify every `[[wikilink]]` in the guide still matches a scanned vault filename.

Finalize must:

1. Verify the verdict chain is complete and approving. Halt if any required verdict JSON is missing or non-approving.
2. Write the approved guide to the real vault, or to `data/Sessions/<Title> Dry Run.md` for dry runs.
3. Run `src/operative_guide_validator.py`.
4. Fix deterministic validation failures and rerun.
5. For real runs, update the index, extract concepts, log memory, and queue Anki cards when appropriate.
6. For dry runs, do not write vault files, memory, concepts, or Anki cards.

Operative-guide Anki cards are a deck-routing exception to the usual domain taxonomy. Every card generated from this guide must use:

```text
Neurosurgery::Procedures::<Title>
```

where `<Title>` is the operative guide filename without `.md`.

---

## Non-Negotiable Quality Principles

- No arbitrary numerical quotas for operative steps, danger zones, instruments, anatomy expansions, or citations.
- Completeness is judged by Coverage Matrix block satisfaction and conduct-changing knowledge, not length.
- The 85% resident-mastery depth target governs every block; silent omission is a workflow failure.
- The guide is written from an approved operative knowledge map, not directly from search results.
- Map-completeness review and expert completeness review must be performed by subagents different from the writer for intermediate/complex procedures.
- Each operative step must carry an explicit step-rationale chain (mechanical/anatomic goal → why this technique → consequence if skipped → downstream step).
- Anatomy must expand into operative consequences with neurophysiologic role: vascular supply, nerve function, fascial plane, venous drainage, bony limit, corridor boundary, postoperative deficit, or bail-out option.
- Pitfalls must be mechanism-linked. "Avoid retraction" is inadequate unless the guide states what is being retracted, why it is vulnerable, what injury looks like, and what to do instead.
- Bail-outs must be executable. "Get help" may be correct but is incomplete unless paired with what to do while help arrives.
- Postoperative management must connect complications to the operative step that caused them.
- Source retrieval supplements expert synthesis. Do not parrot retrieved passages or structure the guide around retrieval order.
- Do not pad short procedures with irrelevant detail. Compact treatment is fine when the block is genuinely simple.

---

## Artifact Rules

- No H1 title; the filename is the title in Obsidian.
- No YAML at the top. YAML metadata belongs at the bottom.
- If RAG was used, place the sanctioned callout immediately above the first H2:

```markdown
> [!info] RAG Supplemented
> Textbook retrieval was used to ground operative sequence, anatomy, equipment, pitfalls, and bail-outs.
```

- Cite sources inline where they add specificity, especially textbook chapter/page references and any journal evidence that changes indications or outcomes.
- Provenance tiering is mandatory (see `intraoperative-guide-synthesis.md`): every clinical claim is **RAG-grounded** (cited), **model knowledge — verified** (confirming source located, cited), or **model knowledge — verify** (labelled inline, high-stakes specifics flagged with `⚠`). Never attach a textbook/PMID citation to model-knowledge content. The expert reviewer enforces this with a provenance-integrity check.
- Use wikilinks only to files verified in the vault scan.
- Use restrained Obsidian-native formatting for readability: callouts, compact tables, and short phase labels are encouraged when they make a long guide easier to rehearse. Do not add decorative formatting that distracts from operative content.
- Prefer callouts for high-signal material:
  - `> [!info] RAG Supplemented` only for source status, exactly as specified above.
  - `> [!tip] Operative Mental Model` for the opening mental model when helpful.
  - `> [!warning] Critical Safety Point` for airway, vascular, neural, or wrong-level hazards.
  - `> [!danger] Bail-Out` for executable rescue plans.
  - `> [!note] Attending Question` for oral-defense prompts when a separate section would interrupt flow.
- Use tables only for compact comparison or causality maps, such as approach selection, complication signatures, or phase-by-phase failure modes. Do not turn the whole guide into tables.
- Mermaid flowcharts are encouraged for decision branches and causality flows when they aid rehearsal; they are not a substitute for prose and are not yet mandated.
- Include a `## Pre-Scrub Mental Rehearsal` section near the end of the guide for intermediate and complex procedures.
- Write like an operative reference, not a generic explanation.
- Avoid false precision. If a step varies by attending preference or institution, say what varies and what principle remains fixed.
- Do not include "Generation Mode," "STATUS: COMPLETE," citation registries, review memos, gap repair memos, verdict JSON contents, or scaffolding commentary in the final guide.
- Do not add Anki deck-routing metadata as a body section in the guide.

---

## User-Facing Finish

Surface a concise summary:

- File path or dry-run path.
- Source mix and per-domain retrieval counts.
- Source-card path and whether raw retrieval dumps were only retained for audit.
- Whether context budgets were followed or intentionally exceeded, with the reason.
- Procedure complexity.
- Whether decomposition, map-completeness review, and expert completeness review subagents were used (and which checkpoints fell back to self-review with justification).
- Number of map-review cycles and final verdict.
- Number of expert-review cycles and final verdict.
- Whether targeted RAG or PubMed gap repair was needed, and which escalation rules fired.
- Validator result.
- Coverage Matrix blocks satisfied / total.
- Important wikilinks added.
- Anki card count and deck, if real cards were created.
- Path to the verdict-chain directory.
- Confirmation that dry runs did not write real vault, memory, or Anki artifacts when applicable.
