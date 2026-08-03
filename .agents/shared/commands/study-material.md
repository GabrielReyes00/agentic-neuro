# Study Material

Transform a supplied PDF, PPTX, or vault Markdown file into validated active
recall material, then optionally drill it. General questions and resident
simulations do not use this workflow. Artifact generation is exposure, not
learner mastery.

Use `learning-session-contract.md` for phase routing. The focused authorities
are `memory-operations.md`, `memory-retrieval.md`, `vault-intelligence.md`,
`adaptive-teaching-doctrine.md`, `anki-session-workflow.md`, and
`anki-card-quality.md`.

## Generate

1. Infer a concise Title Case topic. Use topic-scoped `startup-recall` only when
   learner context will materially improve question design; the target file does
   not yet exist, so never invent a doc-profile path.
2. Inspect the complete source, including PPTX notes and meaningful images or PDF
   tables/figures. Enumerate all chunks before extraction:
   - PPTX: slides, notes, and image descriptions;
   - PDF: pages, captions, and tables;
   - Markdown: `##` sections.
3. Classify each chunk as substantive or excluded administrative/duplicate
   content. Record every chunk and exclusion in `## Source Chunk Inventory`.
4. Map substantive chunks to coherent `TU-XX` teaching units. Adjacent chunks
   may share a unit, but no substantive source content may disappear.
5. Before writing questions, extract every nontrivial testable relationship,
   step, discriminator, mechanism, sign, exception, or consequence into an
   `AF-###` atomic fact with its source and TU.
6. Build questions from the ledger. Every TU and every ledger fact must be
   assessed. A question may cover up to four tightly related facts; split broader
   prompts. Question count therefore follows source density, not a fixed floor or
   per-slide quota.

Use `.agents/shared/commands/rag-routing.md` only when the source is thin,
ambiguous, or requires source-sensitive verification. RAG is supplemental and
must retain textbook/page provenance. For optional related personal context:

```bash
python3 src/vault_retriever.py recall "<topic or source concept>" --task study-material-generation --limit 5
```

The supplied file remains primary. Skip both enrichments when they add no value.

## Artifact Contract

Write only to:

`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/<Topic Title>.md`

Never accept a repo-local `Documents/Obsidian/...` shadow. If direct vault writes
are unavailable, draft to `data/Sessions/study_material_<slug>.md` and install
through the guard.

Use top-of-file native frontmatter and no H1:

```yaml
---
artifact_type: study-material
status: current
domain: anatomy
summary: One-line content-specific summary.
aliases: []
generated: YYYY-MM-DD
tags: [type/study-material, domain/anatomy]
source_files: []
---
```

After frontmatter, include source, generated date, `Total Questions`, complexity
mix, and `Chunks Processed: N / N`, followed by:

```markdown
## Source Chunk Inventory
| Source | TU | Status | Atomic Facts |
|---|---|---|---:|
| Slide 7 | TU-03 | substantive | 4 |

## Atomic Fact Ledger
- AF-001 | TU-03 | Slide 7 | <one atomic fact>

## Concept Summary

## Questions
### Q1 [mechanism] (Slide 7) — TU-03 — AF-001, AF-002
**Question?**

<details><summary>Answer</summary>
Answer with the needed mechanism, discriminator, or consequence.
</details>
```

Every question header carries complexity, source, TU, and AF references; every
question has a `<details>` answer. Use recall for isolated facts, spatial prompts
for relationships, discrimination for confusers, mechanism for causal chains,
integration/clinical prompts for combined decisions, and visual prompts for
images. Do not make a multi-question bank recall-only. Multiple choice is mainly
for discrimination, and its answer must explain each distractor.

Install and validate:

```bash
python3 src/study_material_guard.py install --draft "data/Sessions/study_material_<slug>.md" --title "<Topic Title>" --json
python3 src/study_material_guard.py validate "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/<Topic Title>.md" --json
```

Repair failures and rerun. Do not begin a drill until the real-vault file passes.
Surface only the path, chunk/fact/question counts, and actionable failures. After
validation, extract 0–5 genuinely novel concepts under `concept-extraction.md`;
zero is valid and existing concepts require reviewed merge semantics.

## Drill

Read the complete installed note, set one `SESSION_TS`, and run:

```bash
python3 src/study_memory.py startup-recall --profile doc --topic "<topic>" --doc "Study Material/<Title>.md" --session "$SESSION_TS"
```

The selected file is the curriculum. New review begins with its first uncovered
TU; returning review addresses same-document misses and repairs before moving
forward. Other memories may enter only as a direct prerequisite, confuser,
safety issue, or one brief due bridge. At point of need, related vault context
may help repair an answer but never replace the source ledger or question bank:

```bash
python3 src/vault_retriever.py recall "<topic or missed concept>" --task doc-review --limit 5
```

Ask Gabriel to choose, with a recommendation based on the source:

- **Rapid Review:** preserve source-question throughput. After a correct answer,
  confirm briefly and advance; after a partial answer, repair the missing edge;
  after an incorrect, unsafe, or confidently wrong answer, teach concisely and
  retest. Escalate depth only for a meaningful miss or explicit request.
- **Deep Understanding:** use Socratic branching, progressive reveal,
  mechanism-to-management links, changed-frame transfer, and oral-board defense
  when appropriate.

In both modes, ask one question and stop without exposing the answer or source
context. After commitment, grade, reveal only the next useful layer, and follow
`adaptive-teaching-doctrine.md`. Checkpoint at natural TU or cognitive-load
boundaries rather than a fixed question count.

Every assessed answer follows `memory-operations.md` with
`--skill study-material`; include specific error metadata for partial or
incorrect answers. Create Anki cards only when the evaluated exchange meets
`anki-session-workflow.md` eligibility—not from passive generation or routine
correct recall.

## Finish

Run `end-session` with a document-specific `--next-strategy`, perform the shared
integrity check, and review/check/flush the Anki queue. Remove only named
workflow-owned temporary drafts; preserve provenance ledgers and never clean
`data/Sessions/` broadly.
