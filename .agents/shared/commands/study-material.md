# Study Material Generator and Drill

Use for explicit file-based study requests from PDF, PPTX, or vault markdown. Do not use this for general questions or intern simulation.

Follow `.agents/shared/commands/learning-session-contract.md`.

## Phase 1: Generate Material

1. Infer a clean Title Case topic from the filename.
2. Run `study_memory.py summary --topic "<topic>" --limit 8 --scaffold-limit 2` to load learner context.
3. If the source is already marked `Generation Mode: [+RAG]`, skip the RAG opt-in prompt. Otherwise ask whether to enrich with local RAG.
4. Enumerate all chunks before extraction:
   - PPTX: slides, titles, body, notes, image descriptions.
   - PDF: pages, headers, body, captions, tables.
   - Vault markdown: `##` headings as chunks.
5. Classify each chunk as substantive, intro/outro, duplicate title, or non-teaching administrative content. Exclude only clearly non-substantive chunks and state the exclusion count.
6. Process each substantive chunk in order. Assign `TU-XX` teaching units. Do not batch, merge, or skip substantive chunks.
7. Extract atomic facts before writing questions:
   - Assign `AF-###` IDs.
   - Keep each fact atomic: one relationship, pathway step, discriminator, mechanism, clinical sign, exception, or management consequence.
   - Extract 2-6 atomic facts per substantive chunk, more for dense pathway/clinical slides.
   - Preserve source references for every fact.
8. Build questions from the atomic fact ledger, not directly from slide titles. A slide may produce many questions. One slide -> one topic -> one question is a failure.
9. Verify `Chunks processed: N / N`, atomic fact count, fact coverage, and question density before writing the final file.

### Generation Quality Gate

This command is not complete when the model has merely drafted prose. It is complete only when a deterministic guard verifies the real vault file.

Hard rules:

- Use the stronger available model for generation. Do not use Flash-class models for `/study-material` generation unless Gabriel explicitly accepts a lower-quality draft.
- The final file must live at `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/<Topic Title>.md`.
- Never treat `Documents/Obsidian/...` inside the repo as the vault. That is a workspace shadow path and is a failure.
- If a write tool cannot write outside the workspace, draft to `data/Sessions/study_material_<slug>.md`, then install it with `src/study_material_guard.py`.
- Do not start the interactive drill until `src/study_material_guard.py validate` passes.
- If the guard fails, revise the note and rerun the guard. Tell Gabriel only the concise failure category, not raw command output.

Minimum generated-note contract:

- `Total Questions` metadata and `Chunks Processed: N / N` metadata.
- `## Source Chunk Inventory`, `## Atomic Fact Ledger`, `## Concept Summary`, and `## Questions`.
- At least 25 questions unless Gabriel explicitly requests a shorter deck.
- At least 2 atomic facts per processed substantive chunk.
- At least 2 questions per processed substantive chunk.
- At least 70% of atomic facts referenced by at least one question.
- Every chunk/teaching unit has multiple mapped atomic facts unless the source chunk is genuinely trivial.
- Every question header includes `[complexity]`, source reference, `TU-XX`, and one or more `AF-###` references.
- Every question has an answer in `<details>`.
- Complexity mix includes at least three categories and must include mechanism, discrimination, integration, or clinical questions.

Install/validate flow:

```bash
python3 src/study_material_guard.py install --draft "data/Sessions/study_material_<slug>.md" --title "<Topic Title>" --min-questions 25 --min-questions-per-chunk 2 --min-facts-per-chunk 2 --min-fact-coverage 0.70
python3 src/study_material_guard.py validate "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/<Topic Title>.md" --min-questions 25 --min-questions-per-chunk 2 --min-facts-per-chunk 2 --min-fact-coverage 0.70
```

### Atomic Extraction Protocol

The extraction ledger is the controlling artifact. Build it before `## Questions`.

Required sections:

```markdown
## Source Chunk Inventory
| Source | TU | Status | Atomic Facts |
|---|---|---|---:|
| Slide 7 | TU-03 | substantive | 4 |

## Atomic Fact Ledger
- AF-001 | TU-03 | Slide 7 | <one atomic fact>
- AF-002 | TU-03 | Slide 7 | <one atomic fact>
```

Question headers must map back to the facts they test:

```markdown
### Q12 [mechanism] (Slide 7) — TU-03 — AF-001, AF-002
```

Coverage rule:

- Recall questions may test one atomic fact.
- Spatial, mechanism, discrimination, integration, clinical, and visual questions may test 2-4 linked atomic facts.
- Do not create a single broad question to "cover" an entire slide. If a slide contains pathway, lesion localization, syndrome, exception, and management implications, those become separate questions or linked multi-fact questions.
- The guard rejects shallow compression, but the agent must still inspect every source chunk and preserve the atomic ledger.

## Classification

| Pattern | Complexity | Question Style |
|---|---|---|
| Definition, name, single fact | `recall` | Short answer or cloze |
| Spatial course or relationship | `spatial` | Relationship prompt |
| Confusable concepts | `discrimination` | MC with close distractors |
| Causal chain | `mechanism` | Two-step reasoning |
| Combined anatomy, physiology, clinical use | `integration` | Vignette |
| Diagram or imaging centered | `visual` | Image-reference prompt |

MC is mainly for discrimination. Default to retrieval prompts.

## Optional RAG Enrichment

Use only for thin mechanism or integration units:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "<teaching unit title>" --stdout --no-frontier
```

RAG content is supplemental. Keep source-file content primary and cite textbook title, edition, and page when RAG is used.

## Output File

Write directly to:

`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/<Topic Title>.md`

Rules:

1. No H1.
2. Start with source metadata, generation date, total questions, and complexity mix.
3. Include `Chunks Processed: N / N`, where both numbers match after extraction.
4. Include `## Source Chunk Inventory`, `## Atomic Fact Ledger`, `## Concept Summary`, and `## Questions`.
5. Every question has complexity, source reference, TU ID, AF ID(s), and answer inside `<details>`.
6. Every MC answer explains why each distractor is wrong.
7. Do not summarize away concepts to reduce length.
8. Do not collapse a dense slide into one concept or one question.

Notify with counts only after the guard passes, then offer: start drilling, review offline, or both.

## Phase 2: Interactive Drill

Before drilling:

```bash
python3 src/study_memory.py summary --topic "<topic>" --limit 8 --scaffold-limit 2
```

The selected document is the curriculum. New documents start at TU-01. Returning documents prioritize previously missed concepts from this same document, then continue forward. Use memory summary output to identify scaffold, must-retest, recent-repair, and handoff concepts for this document. Prior misses from other sessions may appear only under the Requested-Document Priority rule: directly related, close confuser, safety-critical, or one brief due bridge.

## Study Mode Gate

Study Material files can have different educational purposes. Do not assume every vault document needs the same deep Socratic treatment.

Before drilling a vault markdown file, determine the document's study mode. Ask Gabriel to choose:
- **Rapid Review / Jeopardy**: fast source-question calibration.
- **Deep Understanding**: current deep Socratic mechanism-building mode.

If the file is clearly generated from review slides, premade topic questions, lab review, or test-prep material, default suggestion is Rapid Review. If it is a generated report, long synthesis, new primary-source distillation, or material Gabriel explicitly wants to master deeply, default suggestion is Deep Understanding.

### Rapid Review / Jeopardy Mode

Use this for review-material files intended for quick turnaround.

Operating rules:

- Treat the document as a question deck, not as a live body of knowledge requiring expansion at every item.
- Ask the source question as written or lightly cleaned. Do not convert it into a longer vignette unless the source question already is one.
- One question at a time. Preserve throughput.
- After a correct answer: one-line confirmation plus at most one high-yield discriminator, then advance.
- After a partial answer: brief correction, one targeted repair probe only if needed, then continue or mark for later.
- After an incorrect, unsafe, or overconfident-wrong answer: pause for a concise explanation and immediate retest.
- Do not run oral-board-style deepening after every correct answer.
- Do not start with unrelated prior-miss backlog. Prior memory can influence grading and escalation, but it must not derail the selected document.
- Checkpoint every ~10-15 questions or natural section boundary.

Escalate out of Rapid Review only when earned:

- wrong answer
- partial answer missing the key discriminator
- high-confidence wrong answer
- safety-critical misconception
- repeated miss in memory
- Gabriel asks to go deeper
- schema-level mismatch, not just a missing isolated fact

When escalating, name the reason briefly and keep the repair bounded. Choose the specific repair move needed for the miss type. Memory logging captures the outcome via the shared contract's `log-answer` with `--correct`, `--error-type`, `--misconception`, and `--correction` — these fields are the durable record of what happened and why.

### Deep Understanding Mode

Use this for generated reports, new synthesis, unfamiliar mechanisms, oral-board preparation, or when Gabriel explicitly wants mastery.

This preserves the current behavior:

- Socratic branching.
- Progressive reveal after commitment.
- Mechanism-to-management links.
- Clinical transfer and oral-board defense when appropriate.
- Deeper follow-up after shallow correct answers.

Log answers via the shared memory logging contract. The `--correct`, `--error-type`, and `--misconception` fields capture the outcome; the `--correction` field captures what you taught.

Drill one question at a time:

Follow the Cognitive Friction Protocol from the shared learning contract. In interactive drill mode, show only the question stem and the immediate task. Do not print the answer, `<details>` content, explanation, named finding, or source context until after Gabriel answers or explicitly asks to reveal it.

After Gabriel answers, choose the post-answer behavior from the selected study mode. In Deep Understanding mode, follow the teaching principles in the shared contract: reveal progressively, correct with minimum effective explanation, pull deeper with follow-ups. In Rapid Review mode, reveal only enough to grade the answer and maintain momentum unless an escalation trigger fires. Do not dump all nearby essential material from the Study Material note after a shallow correct answer. Save the broader map for a natural boundary, a miss requiring teaching, an explicit reveal request, or a Deep Understanding session.

| Outcome | Response |
|---|---|
| Correct | Brief confirmation plus one enrichment |
| Partial | Acknowledge correct part, probe missing part |
| Incorrect | Socratic redirect before revealing |
| Second miss | Full answer and correction |
| Skip or IDK | Respect it, explain, circle back later |

Ordering: recall, spatial/discrimination, mechanism/integration, visual interspersed. If 2+ misses occur in one TU, add 1-2 alternate-angle probes.

Every evaluated answer follows the shared memory logging contract with `--skill "study-material"`. Use the same `SESSION_TS` for the whole drill. For partial or incorrect answers, include full error metadata (`--error-type`, `--misconception`, `--correction`).

Checkpoint around every 12 questions with strengths, needs work, and options to continue, focus weak areas, or pause.

At section boundaries, use the compression card if it fits the source: one-breath schema, danger rule, discriminator, or rescue move. In Rapid Review mode, keep this to one prompt; in Deep Understanding mode, use it to decide whether to advance or transfer.

## Finish

Run `study_memory.py end-session` with a specific `--next-strategy` for the next drill on this document. Follow the **Post-Session Integrity Verification** protocol from the shared contract. Then follow the **Anki Queue Validation and Flush** protocol — generate cards for incorrect, partial, and high-yield exchanges using `.agents/shared/commands/anki-card-quality.md`, then flush. Clean up `data/Sessions/` temps.
