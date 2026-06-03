# Service Log

Capture the day's learning on a service rotation in one pass: log it to the service-rotation
memory layer AND immediately find the gap and teach it. One voice dictation should produce both
durable memory and a short, high-yield learning moment. This is the daily front door to
continuous, service-anchored growth — the texture of a rotation (recurring orders, imaging,
consults, corrections, the day's case mix) turned into tracked competence.

Follow `.agents/shared/commands/adaptive-teaching-doctrine.md` for the teaching turn,
`memory-operations.md`/`memory-retrieval.md` for memory semantics, and
`anki-card-quality.md` for any explicitly requested cards. This contract wins for `/service-log`.

## When To Use

- Explicit `/service-log`.
- A dictation that opens with the service-rotation frame, e.g. "today on tumor service at
  MD Anderson, I managed / learned / got corrected on...".
- Any short daily debrief of what was managed, ordered, followed up, consulted, or taught on a
  specific service rotation.

Do not use for:
- A de-identified one-off ward teaching point for later review with full source verification: that
  is `/brain-dump` (heavier, artifact-producing, RAG-verified).
- A direct management question needing an answer or pocket card: `/consult`.
- Formal document/topic review or weak-spot drilling: `/study-review`.

`/service-log` and `/brain-dump` are siblings. `/brain-dump` produces a verified vault artifact for
exposure capture and writes only a memory anchor. `/service-log` produces no vault artifact, is
ultra-light, and DOES write tracked service-origin learner state (gaps, competency progress) so the
rotation compounds day over day.

## Success Criterion

In one short exchange Gabriel has (1) the day's learning logged to the active rotation as
provenance-isolated service memory, and (2) at least one targeted teaching/quiz moment on the gap
the dictation revealed — not a lecture, a probe and a correction.

## Hard Boundaries

1. **De-identify before any processing or persistence.** Strip names, MRNs, room/bed identifiers,
   full dates of birth, and unique patient timelines before retrieval, teaching, or memory writes.
   Generalize to clinically necessary descriptors ("post-op posterior fossa patient"). If
   de-identification removes the educational meaning, ask for a sanitized restatement first.
2. **Service memory is provenance-isolated.** Every memory write uses `--origin service` and binds
   to the active rotation. Service-origin gaps must never be logged as `assessed`, and never leak
   into formal review. The seal is enforced in code; do not work around it.
3. **Capture clinical gaps and conventions distinctly.** A portable clinical gap (mechanism,
   threshold, management consequence) keys to the *service* and carries across sites and years. An
   institutional habit / order set / workflow preference is a `--convention` and keys to
   (service x site) — it must not be taught as universal truth.
4. **Memory remains invisible.** Never narrate stored gaps, rubric state, or inferred learner level
   to Gabriel. Surface only the teaching and a concise confirmation.
5. **Exposure is not mastery.** A reported lesson is evidence of encounter. Only the answer Gabriel
   actually gives in the teaching turn is graded; log that result honestly (`--correct 0/1/2`).
6. **Stay light.** No report-scale RAG campaign. At most one focused verification query for a
   single management-changing claim, and only when needed.

## Workflow

### 1. Resolve The Rotation

Parse the service and site from the dictation. Ensure the active rotation matches:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py rotation-current
```

- If no active rotation, or the dictation names a different service/site, open one (this also
  seeds the service competency rubric from the ACGME catalog on first touch):

```bash
python3 src/study_memory.py rotation-start --service "<service>" --site "<site>" [--pgy <n>] [--block "<label>"]
```

Capture the returned `rotation_id`; service-origin writes default to the active rotation when
`--rotation` is omitted. A service-origin write without a valid active or explicit rotation is
invalid and must be fixed by opening/resolving the rotation first.

### 2. Silent Service-Lens Context

```bash
python3 src/study_memory.py startup-recall --lens service --service "<service>" --site "<site>"
```

Read `service_gaps` (primary), `conventions` (site-local), `formal_secondary` (capped,
domain-matched assessed study — let it inform depth, never dominate), and `rubric_open`. Use this to
decide what to probe and at what level. Do not state what memory returned. Honor the
`weighting_policy` in the payload.

### 3. Extract The Teaching Edge

From the de-identified dictation, identify for each point:

- **Trigger**: the situation, order, imaging, consult, or correction.
- **Reported rule / action**: what was done or taught.
- **Edge**: the mechanism, threshold, discriminator, or management consequence that is the actual
  learning — and whether it is a portable clinical gap or an institutional convention.

Detect recurring patterns ("I keep placing this order / following this imaging"): the learning is
the principle behind the repetition and the variation Gabriel is not yet seeing.

### 4. Teach In One Pass (the second bird)

Pick the single highest-yield edge. Ask one calibrated probe per
`adaptive-teaching-doctrine.md` — stop and let Gabriel answer (cognitive friction is mandatory; do
not append the answer). Then grade briefly and reveal the next useful layer. This is a short
moment, not a lecture.

### 5. Log Service-Origin Memory

`SESSION_TS` is set at the first learner-facing question per `memory-operations.md`. For each
genuine gap surfaced (use the graded result of the teaching turn):

```bash
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" \
  --topic "<clinical topic>" \
  --concept "<concept>" \
  --question "<the probe asked>" \
  --answer "<learner answer, de-identified>" \
  --correct <0|1|2> \
  --skill "service-log" \
  --origin service \
  [--rotation <rotation_id>] \
  [--competency-target "<rubric slug>"] \
  --tested-claim "<the claim being tested>" \
  --corrected-rule "<the correct rule, when missed>" \
  --clinical-consequence "<why it changes management>"
```

- Add `--convention` for institutional/order-set/workflow points so they stay (service x site)
  local and are never taught as universal fact.
- Link `--competency-target` when the point maps to a rubric item (advances it off `open`).
- Do not log identifiable patient detail in any field.

Close the session:

```bash
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "<sanitized: what was learned/corrected on the rotation today>" \
  --next-strategy "<what to probe next shift, or which rubric edge to steer toward>" \
  --json
```

### 6. Optional Anki (only if requested)

Do not auto-card. If Gabriel asks, route every card to the provenance-isolated deck:

`Neurosurgery::Service Learning`

Tag `service-learning` plus appropriate domain/service tags. Do not encode a `--convention` point or
an unverified high-stakes specific as settled fact; if a number is load-bearing and unverified, run
the one focused RAG check first or omit it.

## Anticipatory Mode (manual)

When Gabriel asks "what should I review to stay sharp on <service>" or "what's coming on this
rotation", run the service lens with an optional upcoming-case context string and blend service +
capped formal:

```bash
python3 src/study_memory.py startup-recall --lens service --service "<service>" --context "<upcoming case/topic>"
```

Lead with `service_gaps` and `rubric_open`; let `formal_secondary` inform depth. This is manual in
v1 — not tied to the calendar.

## Completion

Surface concisely:

- the de-identified teaching edge and the one-line correction;
- the active rotation (service @ site) the learning was logged to;
- whether any point was marked a local convention or remains verification-worthy;
- card count only if cards were explicitly created.

Never print memory commands, payloads, or raw stdout/stderr into the transcript.
