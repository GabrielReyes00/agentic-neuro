# Study Material Generator and Drill

Use for explicit file-based study requests from PDF, PPTX, or vault markdown. Do not use this for general questions or intern simulation.

Follow `.agents/shared/commands/learning-session-contract.md`.

## Phase 1: Generate Material

1. Infer a clean Title Case topic from the filename.
2. Run preflight and read learner context.
3. If the source is already marked `Generation Mode: [+RAG]`, skip the RAG opt-in prompt. Otherwise ask whether to enrich with local RAG.
4. Enumerate all chunks before extraction:
   - PPTX: slides, titles, body, notes, image descriptions.
   - PDF: pages, headers, body, captions, tables.
   - Vault markdown: `##` headings as chunks.
5. Process each chunk in order. Assign `TU-XX` teaching units. Do not batch or skip chunks.
6. Verify `Chunks processed: N / N`.
7. Build a concept map with a strict 1:1 concept-to-question mapping.

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
python3 src/lance_retriever.py compare "<teaching unit title>" --no-learner --no-frontier
```

RAG content is supplemental. Keep source-file content primary and cite textbook title, edition, and page when RAG is used.

## Output File

Write directly to:

`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/<Topic Title>.md`

Rules:

1. No H1.
2. Start with source metadata, generation date, total questions, and complexity mix.
3. Include `## Concept Summary` and `## Questions`.
4. Every question has complexity, source reference, TU ID, and answer inside `<details>`.
5. Every MC answer explains why each distractor is wrong.
6. Do not summarize away concepts to reduce length.

Notify with counts and offer: start drilling, review offline, or both.

## Phase 2: Interactive Drill

Before drilling:

```bash
python3 src/knowledge_graph.py doc_status "Study Material/<Topic Title>.md"
python3 src/memory_orchestrator.py document-profile --doc "Study Material/<Topic Title>.md" --doc-type "study-material" --text
```

The selected document is the curriculum. New documents start at TU-01. Returning documents prioritize previously missed concepts from this same document, then continue forward. Prior misses from other sessions may appear only under the Requested-Document Priority rule: directly related, close confuser, safety-critical, or one brief due bridge.

## Study Mode Gate

Study Material files can have different educational purposes. Do not assume every vault document needs the same deep Socratic treatment.

Before drilling a vault markdown file, determine the document's study mode:

1. Run `document-profile` for the vault-relative path.
2. If the returned profile has a confident stored `preferred_study_mode`, use it and briefly state the mode.
3. If no confident preference exists, ask Gabriel to choose:
   - **Rapid Review / Jeopardy**: fast source-question calibration.
   - **Deep Understanding**: current deep Socratic mechanism-building mode.
4. Store the choice immediately:

```bash
python3 src/memory_orchestrator.py --quiet document-profile \
  --doc "Study Material/<Topic Title>.md" \
  --doc-type "study-material" \
  --study-mode "rapid_review|deep_understanding" \
  --source-kind "review_material|generated_report|study_material" \
  --pacing-goal "throughput|mastery" \
  --confidence 0.9 \
  --mode-reason "User selected this pacing for this document" \
  --apply
```

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

When escalating, name the reason briefly and keep the repair bounded. Log the answer with `--teaching-approach "rapid_review_jeopardy"` for routine items, or `--teaching-approach "rapid_review_escalated_deep_dive"` when escalation occurs. Use `--depth 1` for simple deck checks, `--depth 2` for discriminator/mechanism repair, and `--depth 3` only for clinical decision transfer.

### Deep Understanding Mode

Use this for generated reports, new synthesis, unfamiliar mechanisms, oral-board preparation, or when Gabriel explicitly wants mastery.

This preserves the current behavior:

- Socratic branching.
- Progressive reveal after commitment.
- Mechanism-to-management links.
- Clinical transfer and oral-board defense when appropriate.
- Deeper follow-up after shallow correct answers.

Log answers with teaching approaches such as `deep_understanding_progressive_reveal`, `mechanism_to_management`, `clinical_transfer`, or the more specific approach actually used.

Drill one question at a time:

Follow the Cognitive Friction Protocol from the shared learning contract. In interactive drill mode, show only the question stem and the immediate task. Do not print the answer, `<details>` content, explanation, named finding, or source context until after Gabriel answers or explicitly asks to reveal it.

After Gabriel answers, choose the post-answer behavior from the selected study mode. In Deep Understanding mode, follow the Progressive Landscape Reveal Protocol. In Rapid Review mode, reveal only enough to grade the answer and maintain momentum unless an escalation trigger fires. Do not dump all nearby essential material from the Study Material note after a shallow correct answer. Save the broader map for a natural boundary, a miss requiring teaching, an explicit reveal request, or a Deep Understanding session.

| Outcome | Response |
|---|---|
| Correct | Brief confirmation plus one enrichment |
| Partial | Acknowledge correct part, probe missing part |
| Incorrect | Socratic redirect before revealing |
| Second miss | Full answer and correction |
| Skip or IDK | Respect it, explain, circle back later |

Ordering: recall, spatial/discrimination, mechanism/integration, visual interspersed. If 2+ misses occur in one TU, add 1-2 alternate-angle probes.

Every evaluated answer follows the shared memory logging contract with `--skill "study-material"`. Use the same `SESSION_TS` for the whole drill. For partial or incorrect answers, include full error metadata and log the correction as passive teaching. If a question asks the learner to apply source-file material to a clinical/operative scenario, also log `record-transfer`.

Checkpoint around every 12 questions with strengths, needs work, and options to continue, focus weak areas, or pause.

## Finish

Run a final heartbeat with doc coverage, outcome, specific gap details, and Obsidian write. Then run `finish-session --session-ts "$SESSION_TS" --skill "study-material" --topic "<Topic Title>" --repair-fragments --mode apply --text` before the post-session hook. Update the living review file, progress tables, and Study Material index. Offer Anki only for incorrect/skipped/high-yield cards, then invoke `/anki-sync` if selected.
