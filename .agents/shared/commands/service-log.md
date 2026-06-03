# Service Log

Daily service-rotation capture: one de-identified dictation becomes service-origin memory plus one short teaching/quiz turn. No vault artifact is written; `data/study_memory.db` is the durable record.

Use for `/service-log`, "today on <service> at <site>...", or short daily service debriefs. Use `/brain-dump` for artifact-producing ward teaching capture, `/consult` for direct management questions, and `/study-review` for formal review.

Follow:
- `adaptive-teaching-doctrine.md` for the probe/teaching turn.
- `memory-operations.md` and `memory-retrieval.md` for session and recall semantics.
- `anki-card-quality.md` for explicitly requested cards.

## Boundaries

- De-identify before retrieval, teaching, memory writes, or Anki: remove names, MRNs, room/bed IDs, full DOBs, exact unique timelines, and other patient identifiers. Ask for a sanitized restatement if meaning is lost.
- Every service memory write uses `--origin service` and a valid active or explicit rotation. Never log service material as `assessed`.
- Clinical gaps key to the service and carry across sites/years. Institutional habits, order sets, and workflow preferences use `--convention` and stay local to service x site.
- Memory reads/writes are invisible bookkeeping. Never print commands, raw stdout/stderr, or recall payloads into the learner transcript.
- Exposure is not mastery. Grade only the answer Gabriel gives in the teaching turn.
- Stay light: no report-scale RAG. Run at most one focused verification query for a management-changing claim when needed.

## Workflow

1. Resolve rotation.

```bash
python3 src/study_memory.py rotation-current
python3 src/study_memory.py rotation-start --service "<service>" --site "<site>" [--pgy <n>] [--block "<label>"]
```

Use `rotation-start` only when no active rotation exists or the dictation names a different service/site. Capture `rotation_id` when returned; `log-answer --origin service` may otherwise use the active rotation.

2. Run silent service recall.

```bash
python3 src/study_memory.py startup-recall --lens service --service "<service>" --site "<site>" [--rotation <id>] [--context "<upcoming/context>"]
```

Interpret the payload as:
- `service_gaps`: primary queue.
- `conventions`: site-local reminders, not universal teaching.
- `formal_secondary`: capped domain-matched assessed study, useful for depth but not priority.
- `rubric_open`: competency targets worth steering toward.
- `weighting_policy: service_primary_formal_capped`: lead with service gaps; formal material can inform, not dominate.

3. Extract one teaching edge from the dictation: trigger, reported action/rule, and the mechanism/threshold/discriminator/management consequence. Identify whether it is a portable clinical gap or a local convention.

4. Teach briefly. Ask one calibrated probe and stop. After Gabriel answers, grade briefly, reveal the next useful layer, and avoid a broad lecture unless asked.

5. Log the graded result.

```bash
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" \
  --topic "<clinical topic>" \
  --concept "<concept>" \
  --question "<probe>" \
  --answer "<de-identified learner answer>" \
  --correct <0|1|2> \
  --skill service-log \
  --origin service \
  [--rotation <rotation_id>] \
  [--competency-target "<rubric slug>"] \
  [--convention] \
  --tested-claim "<claim tested>" \
  --corrected-rule "<correct rule>" \
  --clinical-consequence "<management consequence>"
```

Link `--competency-target` when a rubric target clearly maps. Use `--convention` only for site-local practice, and do not encode identifiers in any field.

6. Close the session.

```bash
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "<sanitized daily service learning>" \
  --next-strategy "<next shift probe or rubric edge>" \
  --json
```

## Optional Anki

Do not auto-card. If explicitly requested, route cards to `Neurosurgery::Service Learning` with `service-learning`, `service/<service>`, and `site/<site>` tags. Do not card conventions or unverified high-stakes specifics as settled universal facts.

## Anticipatory Review

For "what should I review to stay sharp on <service>", run:

```bash
python3 src/study_memory.py startup-recall --lens service --service "<service>" --context "<upcoming case/topic>"
```

Lead with `service_gaps` and `rubric_open`; use `formal_secondary` only as capped support.

## Completion

Surface only the de-identified teaching edge/correction, active rotation, convention or verification caveat if relevant, and card count if cards were created.
