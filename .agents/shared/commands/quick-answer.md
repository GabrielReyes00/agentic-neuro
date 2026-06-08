# Quick Answer

Lightweight memory-enabled answering for isolated neurosurgery, neuroanatomy, neurocritical care, radiology, and related clinical questions.

Use this when the user wants a brief direct answer, not a report, consult pocket card, operative guide, study review, artifact, RAG workflow, or prior-memory-driven session.

This command intentionally does **not** use `.agents/shared/commands/learning-session-contract.md`.

Use `.agents/shared/commands/vault-intelligence.md` only when field-aware Obsidian context would improve a brief answer.

## When to Use

- Explicit `/quick-answer` invocation.
- Brief isolated questions that should be answered directly and then logged.
- Examples: "which pressor is best for induced hypertension and why?", "how does the Edinger-Westphal pathway work?", "how do you classify spine trauma radiographs?"

Do not use for:
- Ward-management consults that should produce a pocket card (`/consult`).
- Deep research or citation-dense synthesis (`/generate-report`).
- Operative rehearsal guides (`/intraoperative-guide`).
- Active recall, weak-spot drilling, or document-anchored review (`/study-review`).

## Workflow

### 1. Answer Normally

Do not run memory summary at session start.
Do not run RAG by default.
Do not write a vault artifact.
Do not force a teaching format, verification questions, or a fixed response length.

Answer the user's question in the style and depth that best fits the question. Use tools only when the question requires current verification, the user asks for sources, or local context is needed.

When prior vault context may improve accuracy or personalization without turning the answer into a full consult, query field-aware vault intelligence:

```bash
python3 src/vault_retriever.py recall "<focused question>" --task quick-answer --limit 3
```

For service/site/local-practice questions, use `--task service-local`. Treat retrieved vault sections as supplemental context. Absence from the vault is not absence from neurosurgery knowledge; use native clinical knowledge and formal verification when needed.

### 2. Memory Write

After the answer, silently create one memory entry for the exchange.

`study_memory.py log-answer` requires both `--question` and `--answer`; for quick answers, use:
- `--question`: the user's original question, verbatim or near-verbatim.
- `--answer`: a compact 1-3 sentence summary of the explanation given.
- `--correct 2`: this is a teaching/answering exchange, not learner performance grading.
- `--concept`: the main concept taught.
- `--skill "quick-answer"`.
- `--teaching-intent "quick_answer_reference"`.
- `--coverage-role "synthesis"`.
- `--answer-mode "after_teaching"`.

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00) && \
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" \
  --topic "<canonical topic, lowercase, 3-8 words>" \
  --concept "<main concept>" \
  --question "<user question>" \
  --answer "<compact summary of the answer provided>" \
  --correct 2 \
  --skill "quick-answer" \
  --tested-claim "<what the answer clarified>" \
  --learner-claim "<question-only exchange; no learner performance assessed>" \
  --learning-operation "<mechanism|discrimination|sequencing|quantification|transfer|recall>" \
  --teaching-intent "quick_answer_reference" \
  --coverage-role "synthesis" \
  --answer-mode "after_teaching"
```

Then close the memory session:

```bash
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "<1-2 sentence summary of the question answered>" \
  --next-strategy "<specific future retest or review angle if this topic is revisited>" \
  --json
```

Read command output silently. Surface only a concise warning if memory logging fails.

Quick-answer sessions are low-stakes reference captures. They should persist in `topics`, `concepts`, `sessions`, `exchanges`, and `claim_results`, but they should not count toward the curation threshold, create session-handoff retrieval cards, or mark a learner claim as durable mastery.

Memory-stack interpretation:
- `skill = quick-answer` means "question asked and answer explained," not "learner demonstrated knowledge."
- These entries are sorted under their resolved topic and concept so future agents can see that the topic has come up.
- They are weak reference evidence for curation. Use them to enrich context or notice adjacency, but do not use quick-answer alone to assert a recurring weakness, durable mastery, `confused_with` relationship, or directed `prerequisite` relationship.
- If later `/study-review`, `/consult`, or `/study-material` sessions test the same concept, those higher-signal entries should dominate learner-state and curation judgment.

### 3. Optional Anki

Do not create Anki cards automatically.

If the answer contained durable high-yield material, ask briefly at the end whether to make cards. If the user says no or does not respond, stop. If the user says yes, create 1-3 atomic cards using `.agents/shared/commands/anki-card-quality.md`, then run:

```bash
python3 src/anki_queue.py review --session "$SESSION_TS" --json
python3 src/anki_queue.py check --session "$SESSION_TS"
python3 src/anki_queue.py flush --session "$SESSION_TS"
```

Parse Anki JSON silently and surface only card counts or actionable blockers.

Use deck format `Neurosurgery::<Domain>::<Topic Title>` and tag `quick-answer`.

## Completion

The command is complete after the direct answer and memory `end-session` write. Anki is complete only when explicitly requested by the user.
