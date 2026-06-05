# Intraoperative Guide

Produce a complete, source-grounded operative rehearsal manual for a neurosurgical procedure. The output should let a neurosurgery resident mentally perform the operation from indication and setup through closure, immediate postoperative surveillance, complication recognition, and failure recovery.

This command is closer to `/generate-report` than to `/consult`: the artifact is a durable standalone operative reference, not a brief teaching exchange. The agent is the intelligence layer. Scripts retrieve sources, validate structure, and record memory; they do not write or reason for the agent.

Follow `.agents/shared/commands/learning-session-contract.md` for the module map. Use `memory-operations.md`, `memory-retrieval.md`, `review-artifacts.md`, `anki-session-workflow.md`, and `anki-card-quality.md` for shared memory, artifact, concept, and Anki behavior unless this contract is more specific.

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

Classify procedure complexity to scale query floors, cycles, and subagent requirements.
* **Simple**: Floor 3 queries. Max 2 expert cycles. Self-review permitted with justification.
* **Intermediate**: Floor 6 queries (≥1 frontier). Max 3 expert cycles. Map & expert subagents required.
* **Complex**: Floor 10 queries (≥2 frontier). Max 5 expert cycles with escalation. Map & expert subagents required.

---

## Pre-Generation Setup

1. **Step 0: Resolve Procedure**: Derive a Title Case slug. Overwrite existing guides. Create session directory: `data/Sessions/<Title>/verdicts`.
2. **Step 1: Discover Memory (silent)**: Run `study_memory.py startup-recall` (profile `doc`) to check prior weaknesses.
3. **Step 2: Scan Vault (silent)**: Scan the vault to locate real target files for cross-citations.

---

## End-to-End Workflow

Follow the modular workflow checkpoints defined in the child modules:

1. **Checkpoint 0: Ledger**: Maintain `data/Sessions/<Title> Workflow Ledger.md` (for dry runs/debug) or in session scratch space. Verdict JSONs are stored under `data/Sessions/<Title>/verdicts/`.
2. **Checkpoint 1: Decomposition** — Read [.agents/shared/commands/intraoperative-guide-decomposition.md](file:///.agents/shared/commands/intraoperative-guide-decomposition.md). Build the Coverage Matrix and write `decomposition.json`.
3. **Checkpoint 2: Research** — Read [.agents/shared/commands/intraoperative-guide-research.md](file:///.agents/shared/commands/intraoperative-guide-research.md). Run textbook RAG and PubMed queries to write `research.json` and generate `source_cards.jsonl` and `coverage_ledger.json`.
4. **Checkpoint 3: Operative Knowledge Map** — Read [.agents/shared/commands/intraoperative-guide-knowledge-map.md](file:///.agents/shared/commands/intraoperative-guide-knowledge-map.md). Construct the JSON-based operative mental model.
5. **Checkpoint 4: Map-Completeness Review** — Read [.agents/shared/commands/intraoperative-guide-map-review.md](file:///.agents/shared/commands/intraoperative-guide-map-review.md). Separate reviewer subagent stress-tests the map; writes `map-review-cycle-<N>.json`.
6. **Checkpoint 5: First Synthesis** — Read [.agents/shared/commands/intraoperative-guide-synthesis.md](file:///.agents/shared/commands/intraoperative-guide-synthesis.md). Draft the guide from the approved map, utilizing correct provenance tiering.
7. **Checkpoint 6: Expert Completeness Review** — Read [.agents/shared/commands/intraoperative-guide-review.md](file:///.agents/shared/commands/intraoperative-guide-review.md). Dedicated expert reviewer subagent evaluates the draft against the rubric; writes `expert-review-cycle-<N>.json`.
8. **Checkpoint 7: Gap Repair Loop** — Read [.agents/shared/commands/intraoperative-guide-gap-repair.md](file:///.agents/shared/commands/intraoperative-guide-gap-repair.md). Apply the escalation ladder if expert review returns `REVISION REQUIRED`; writes `gap-repair-cycle-<N>.json`.
9. **Checkpoint 8: Finalization** — Read [.agents/shared/commands/intraoperative-guide-finalize.md](file:///.agents/shared/commands/intraoperative-guide-finalize.md). Verify verdict chain, run `operative_guide_validator.py`, rebuild index, extract concepts, log memory, and enqueue procedure-specific Anki cards (`Neurosurgery::Procedures::<Title>`).

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

---

## User-Facing Finish

Reread [.agents/shared/commands/intraoperative-guide-finalize.md](file:///.agents/shared/commands/intraoperative-guide-finalize.md) to report:
* File/dry-run path and procedure complexity.
* Source mix, retrieval counts, and context budget tracking.
* Subagent usage and verdict chain summaries (cycles, verdicts, gap-repairs).
* Validator results, Coverage Matrix blocks satisfied, wikilinks, and Anki card counts/deck.
* Confirmation that dry runs did not write real vault, memory, or Anki files.
