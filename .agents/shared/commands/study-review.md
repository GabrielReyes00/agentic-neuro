# Study Review

Doc-anchored Socratic session from an existing `Study Material/<file>.md` note.

Follow `.agents/shared/commands/learning-session-contract.md` for all shared pedagogy (Cognitive Friction Protocol, Progressive Landscape Reveal, Mastery Ladder, Domain Playbooks, Capture Contract).

---

## Pre-Session Setup

### Step 0: Identify the document

Derive the slug from the user's request (e.g., "EVD Management" from "let's review EVD management"). If ambiguous, ask. If the Study Material file does not exist, invoke `/study-material` silently first.

### Step 1: Recall prior context (silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py recall \
  --doc "Study Material/<slug>.md" \
  --topic "<doc topic>"
```

Set one `SESSION_TS` at the first learner-facing question and reuse it for the entire session:

```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```

Apply Recall Interpretation Rules (see shared contract):
- If prior data exists: open with a one-sentence recap of the last session and last strategy, then move directly to questioning. Do not re-explain known concepts.
- If no prior data: start at the beginning of the document (TU-01 / first section).
- Use `Next strategy` as the opening directive.
- Retest all `OPEN ERRORS` before moving to new territory.
- Never repeat any question from `RECENT EXCHANGES` — use that list to find new angles on the same concepts.
- Skip `KNOWN CONCEPTS` unless they are directly prerequisite to a new concept being tested.

**Requested-Document Priority**: Prior memory context is allowed only when the concept is directly prerequisite, confusable, safety-critical, or a single brief bridge. The requested document is the primary curriculum. Never let prior-topic recall displace forward progress in the document.

---

## Session Execution

### Turn Contract

- Ask exactly one question, then stop.
- Start with active recall or a clinical decision; never lecture before Gabriel answers.
- Use the document's section order as a scaffold, not a script. Prioritize:
  1. Open error retests (new angle, matched to error_type)
  2. Gaps from prior sessions (doc-specific)
  3. New, unreviewed sections of the document
  4. Transfer challenges (known concepts applied in new context)
- Move up the mastery ladder: clinical decision → mechanism → discriminator → management consequence → complication rescue → near-transfer → oral-board defense.
- Keep the requested document primary. Honor the `Next strategy` from recall, but do not jump to unrelated prior topics.

### Post-Answer Policy

After every evaluated answer, do exactly four things:
1. **Verdict**: `Correct`, `Partial`, or `Not quite`
2. **One correction or nuance** (for partial/wrong: minimal discriminator to repair; for correct: mechanism, complication, exception, or transfer)
3. **One management or anatomic consequence** tied to the concept
4. **Next question**

No topic tours, broad maps, or extra teaching layers after routine answers. Raise fidelity on correct answers; do not summarize what Gabriel already proved. Treat correct-but-shallow answers as partial when intern-critical action, threshold, contraindication, or rescue is missing.

For partial/wrong: name the exact failure, give the minimal discriminator, then retest the same concept in a near-transfer vignette before marking it repaired.

### Unknown-Unknown Policy

Probes must stay adjacent and management-relevant. Choose from: prerequisite, close confuser, exception, threshold inversion, anatomy/approach risk, failure-to-rescue trigger, or delayed complication. Do not jump to disconnected novelty while a source concept, prior miss, or repair check is still active.

---

## Memory Logging (silent, after every evaluated answer)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" \
  --topic "<doc topic>" \
  --concept "<specific concept tested>" \
  --question "<your question, verbatim>" \
  --answer "<Gabriel's answer, verbatim>" \
  --correct <0|1|2> \
  --doc "Study Material/<slug>.md" \
  --skill "study-review" \
  [--correction "<corrected fact>"] \
  [--error-type "<type>"] \
  [--misconception "<specific wrong belief>"]
```

Correctness: `2` = correct | `1` = partial (right direction, missing key detail) | `0` = wrong or misconception

---

## Session End

When coverage reaches ~80% of the document or the natural session end is reached:

1. **Summarize**: what was retested, what new material was covered, what gaps remain, one learner-pattern insight.

2. **Run end-session** (silent):
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "<1-3 sentence recap>" \
  --next-strategy "<specific directive for next session>"
```
`--next-strategy` must be actionable: name the concept, the error type, and the teaching move.
GOOD: "Retest EVD waveform troubleshooting with a new bedside vignette — partial on previous attempt. Then advance to aSAH grading scale distinctions."
BAD: "Continue reviewing EVD management."

3. **Upsert** `Review Sessions/<Title> Review.md` — one living file per source document. Format per CLAUDE.md §10:
   - `## Concept Map Status` table (concept, status, last tested)
   - `## Session Log` with `### Session N` blocks
   - `## Progress Over Sessions` table
   - Metadata YAML at bottom (no H1, bottom-only)

4. **Final Artifact Guard**:
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/learning_artifact_guard.py \
  --artifact-type study-review \
  --path "Review Sessions/<Title> Review.md"
```

5. **Concept extraction** per CLAUDE.md §7c. Clean up `data/Sessions/` temps.
