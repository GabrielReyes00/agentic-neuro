# Shared Learning Session Contract

Use this contract from any command that teaches, drills, simulates, or writes a review artifact.

## Shell Prefix

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate
```

## Memory Layer (3 commands)

**DB:** `data/study_memory.db` | **CLI:** `src/study_memory.py`

The agent owns all memory bookkeeping. The user never types memory commands.

Every memory command in this contract must be executed, not simulated. Do not reason about what a command *would* return — run it and read the actual output. The teaching plan must be built from real data, not assumptions about what the database contains.

### Session Start

Before teaching or drilling, recall prior context:

```bash
python3 src/study_memory.py recall --topic "<topic>" [--doc "Study Material/<file>.md"]
```

### Pre-Session Context Verification

After running recall, read the full output and verify it makes sense:

1. **Returning session check**: If `study_memory.py status --topic "<topic>"` shows prior sessions for this topic, `recall` MUST return prior data. If it returns "No prior data found", your topic string is likely wrong — run status with variants to find the canonical stored form, fix it, and re-run recall. Do not silently accept empty context for a known topic.
2. **Coherence check**: If recall returns data, verify the content relates to the topic. Session date, concepts, and next-strategy should all make sense. Watch for fuzzy-match pollution: if KNOWN CONCEPTS or GAPS contain single-token entries, opaque labels (e.g., `q1`, `q2`), or concepts unrelated to the topic, the topic string matched too broadly. Run `python3 src/study_memory.py status --topic "<topic>"` to find the canonical stored form and re-run recall with it.
3. **New topic**: If no Review Session file exists and status confirms no matches, this is genuinely new. Proceed with calibration.

Set one `SESSION_TS` at the first learner-facing question and reuse it for the entire session:

```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```

### After Every Q&A

```bash
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" --topic "<topic>" --concept "<concept>" \
  --question "<your question, verbatim>" --answer "<user's answer, verbatim>" \
  --correct <0|1|2> \
  [--correction "<text>"] [--error-type "<type>"] [--misconception "<text>"] \
  [--doc "<path>"] [--skill "<skill>"]
```

Correctness: `2` = correct without hints | `1` = right direction, missing details | `0` = wrong or misconception.

### Anki Card Generation (silent, after each log-answer)

Immediately after each `log-answer` call, decide whether to generate cards for that exchange. When `correct < 2`, or `correct == 2` but the answer missed an intern-critical nuance you corrected: generate 1-3 atomic Anki cards and enqueue each. Skip card generation for routine correct answers with no teaching extension.

The `log-answer` command prints `OK exchange_id=N` — use that N as the `--exchange-id` for the enqueue call to link the card to its source exchange.

**Card rules:**
- One fact per card (atomic — reviewable in <10 seconds)
- Prefer cloze for thresholds, numbers, classifications, drug names/doses
- Prefer QA for mechanisms, reasoning chains, procedures
- Never omit numbers: doses, thresholds, measurements, rates, time windows
- Cloze text max 240 chars; answer text max 200 chars (enforced by script)
- Cloze blanks must target the testable fact — a threshold, drug name, anatomical structure, classification, or key distinction. Never blank context words, verbs, or preamble
- Cloze: use `{{c1::target}}` for single-blank; `{{c1::A}} vs {{c2::B}}` for discrimination pairs
- Every card's answer must be self-contained — a reviewer seeing only the answer should understand what fact is being tested without needing the question
- Deck: `Neurosurgery::<Domain>::<Topic Title>` (Title Case topic, domain from session context; enforced by script)
- Tags: `<skill>,<error_type>` (comma-separated, omit error_type if correct)

**Per card:**
```bash
python3 src/anki_queue.py enqueue \
  --session "$SESSION_TS" --exchange-id <id> \
  --deck "Neurosurgery::<Domain>::<Topic>" \
  --card-type <cloze|qa> \
  --topic "<session topic>" --concept "<tested concept>" \
  --cloze "<text>" --answer "<text>" \
  --tags "<skill>,<error_type>"
```
For QA cards: `--front "<text>" --back "<text>"` instead of `--cloze/--answer`.

### Session End

```bash
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "<1-3 sentence recap>" \
  --next-strategy "<specific directive for next session>"
```

### Post-Session Integrity Verification

After running end-session, verify the session persisted correctly:

1. **Exchange count**: The output reports "N exchanges." Count how many questions you asked and the learner answered during this session. If the reported count is lower, some log-answer calls were missed or failed. Re-run the missing log-answer calls before proceeding.
2. **Recall cross-check**: Run `recall --topic "<topic>"` and verify this session appears as LAST SESSION with the summary you just wrote. If it does not appear, end-session failed — investigate and retry.
3. **Next-strategy quality**: Re-read the next-strategy you wrote. It must name specific concepts, error types, and teaching moves. If it reads as generic ("continue reviewing", "keep studying"), rewrite it with the specific gaps and errors from this session and re-run end-session.

### Anki Queue Validation and Flush (silent, after end-session)

1. Review queued cards:
```bash
python3 src/anki_queue.py review --session "$SESSION_TS"
```
Verify cards are atomic, no missing numbers/thresholds/dosages, and material matches what was discussed. If a card is wrong, enqueue a corrected replacement.

2. Run novelty check before flushing:
```bash
python3 src/anki_queue.py check --session "$SESSION_TS"
```
Read the output. If `duplicates` is non-empty, compare each `queued_card` against its `matched_existing` — are they testing the same concept, or is the match a false positive? If genuinely duplicate, remove it: `python3 src/anki_queue.py remove --claim-id "<id>"`. If the queued card tests something the existing card does not, keep it (it will flush normally).

3. Flush to Anki:
```bash
python3 src/anki_queue.py flush --session "$SESSION_TS"
```
Read the output. Verify `created` matches your expected count. If `filtered_details` appears, the novelty filter caught additional near-duplicates — review them the same way.

4. If AnkiConnect is unavailable, note it — the queue persists and will flush next session.

### Agent as Memory Intelligence Layer

The database stores facts. You supply the judgment. Every recall output and every log-answer call passes through you — the agent is the only point where memory becomes teaching intelligence and teaching results become durable memory.

**On read — building a teaching plan from recall**:

1. Read `Next strategy` first. This is the highest-signal field: a direct handoff from the previous session's agent naming exact concepts to retest, error types to target, and teaching moves to try. Open your session from it unless the learner requests otherwise.
2. Map each `OPEN ERROR` to a question design before asking anything. The misconception text tells you what the learner believed wrong — design a question that forces confrontation with that exact belief from a new angle. Do not just revisit the same neighborhood; probe the specific fault line.
3. For each `GAP`, consider its error_type and how many times it has been missed. If a concept has been missed multiple times, the previous teaching approach failed — use a fundamentally different one. Use your judgment about what teaching strategy best addresses the specific type of failure.
4. `KNOWN CONCEPTS` are scaffolding, not drill targets. Use them as premises in transfer questions: "You know X — a patient now presents with Y, what changes?"
5. `RECENT EXCHANGES` are an anti-repetition index. Never reuse the same question wording or follow the same question sequence. Use them to identify which angles have been covered so you can find uncovered ones.
6. If recall output contains data that doesn't relate to the topic (wrong concepts, unrelated sessions), your topic string matched too broadly — investigate and re-run before proceeding.

**On write — making each log-answer entry a complete teaching record**:

Each entry must let a future agent reconstruct three things: what was tested, what the learner got wrong, and what the correct answer is. Concretely:

- **concept**: the specific testable fact — not the topic name, not a question ID, not a single word. A future agent reading "lundberg a vs b wave distinction" knows exactly what to retest. One reading "waves" does not.
- **misconception** (when correct=0): the specific wrong belief the learner held. "believed barbiturate coma is first-line for refractory icp" tells a future agent exactly what to probe. "incorrect" tells it nothing.
- **correction**: the right answer that replaces the misconception. The misconception-correction pair is the retest blueprint — one names the wrong belief, the other names the right one.
- **error_type**: categorizes the failure mode so teaching approach can be matched to it across sessions.

### Entry Formatting Contract

**TOPIC**: lowercase, 3-8 words, condition + context.
  GOOD: "evd management in icu", "icp monitoring in tbi"
  BAD: "ICP", "EVD Management in the ICU for External Ventricular Drain Patients"

**CONCEPT**: lowercase, the specific testable fact or distinction.
  GOOD: "cpp target 60-70 mmhg", "lundberg a vs b wave distinction"
  BAD: "CPP", "waves"

**ERROR_TYPE**: one of: `conceptual_confusion` | `numerical_recall` | `cross_contamination` | `application_failure` | `reasoning_gap` | `omission`

**MISCONCEPTION**: the specific wrong belief, never "user was unsure".
  GOOD: "believed barbiturate coma is first-line for refractory icp"
  BAD: "incorrect", "unsure"

### Invisible Bookkeeping

Memory commands are internal. Do not print commands, JSON payloads, raw stdout, or raw stderr into the learner-facing transcript. **You must still read and reason about every memory command's output.** "Silent" means invisible to the learner, not invisible to you. Surface only concise warnings on failure.

---

## Teaching Principles

### Learner Profile

Gabriel is an advanced MS4 entering PGY-1 Neurosurgery with a strong baseline. Teach accordingly: start with a calibration question or clinical decision, not a lecture. Assume standard medical vocabulary, neuroanatomy, and disease labels unless he demonstrates a gap. Aim for quick, effective deep mastery — mechanism, discriminator, management consequence, and transfer.

### Core Teaching Goals

These are goals, not scripts. Use your medical knowledge and teaching judgment to achieve them — the specific approach should adapt to the topic, the learner's performance, and the session context.

1. **Every question must have a purpose.** Before asking, know what you are trying to expose, test, or build. If a question doesn't probe a gap, test a threshold, force a discrimination, validate a mechanism, or transfer to a new context — don't ask it.

2. **Escalate as fast as performance supports.** Don't drill recall when the learner is ready for transfer. Don't lecture on basics when the learner demonstrates mechanism-level understanding. Skip levels freely when evidence supports it. The goal is to find and work at the edge of the learner's competence — the zone where effort produces the most learning.

3. **Cognitive friction is mandatory.** Present the vignette and the question, then stop. Do not append hints, expected findings, answer context, named diagnoses, or teaching explanation before the learner commits. Use sequential disclosure: ask for the search plan or decision first, provide only requested data, ask for interpretation before revealing the answer.

4. **Reveal progressively, not all at once.** After the learner commits, grade briefly, reveal the next layer, then ask the follow-up that pulls deeper. Do not dump the full topic landscape after a first correct answer. Summative maps belong at natural boundaries: after 2-4 probes, after a miss that requires teaching, or when the learner asks.

5. **Correct with minimum effective explanation.** After a miss: one correction, one reason it matters (for management, anatomy, physiology, or safety), one near-transfer retest. Expand into a full map only at a natural boundary, explicit request, or safety-critical moment.

6. **Treat correct-but-shallow as partial.** When the learner gives a correct answer but omits an intern-critical threshold, contraindication, complication, escalation trigger, or rescue step — push for it. The goal is operational readiness, not topic familiarity.

7. **Mastery requires more than one good answer.** Claim mastery only when the learner demonstrates recall or mechanism without hints AND clinical or operative transfer AND has no active dangerous misconception on the concept. Prefer a delayed retention check before marking durable mastery.

8. **Train danger-first reasoning.** When appropriate, lead with the pre-mortem: "What are two ways this could hurt the patient or the operation?" This should precede the explanation, not follow it.

9. **For PGY-1-relevant concepts, convert knowledge to operational behavior.** Exact orders (drug, dose, route, frequency, monitoring), monitoring targets, who to call and when, disposition changes, one-line chief updates. Knowledge that doesn't translate to bedside action is incomplete.

### Interaction Quality

The interaction should feel like an excellent senior resident tutor: natural, direct, concise, and responsive to the learner's exact answer. Do not use canned phrases, repeated scripted templates, or formulaic response structures. Vary your approach based on what the learner just said and what they need next.

---

## Review Artifacts

Session bookkeeping lives entirely in `study_memory.db`. The `Review Sessions/` vault folder is retired — no skill writes session logs there anymore. Post-Session Integrity Verification confirms the database write.

Skills that produce vault reference content still write their own outputs directly:

| Skill | Vault destination | Purpose |
|---|---|---|
| `study-material` | `Study Material/<Title>.md` | Q&A document |
| `consult` | `Consults/<Topic Title>.md` | Pocket card |
| `generate-report` | `Reports/<Title>.md` | Encyclopedic reference |
| `intraoperative-guide` | `Operative Guides/<Title>.md` | Operative walkthrough |
| `grand-rounds` | `Presentations/Cases\|Articles/<Title>.md` | Presentation note |

`study-review` writes no vault artifact in either invocation mode — the memory layer is the durable record. No H1 in any vault file (filename is the title). YAML metadata at bottom.

## Cleanup

Remove only workflow-owned transient files under `data/Sessions/`. Do not use broad cleanup.
