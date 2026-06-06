# Service Log

`/service-log` is the service-debrief entry point for clinical experience capture. It uses the `/brain-dump` artifact workflow and preserves service/site memory primitives for local conventions, operational habits, and rotation-specific learning.

If `/service-log` is invoked, follow `.agents/shared/commands/brain-dump.md` and apply these service-memory rules:

- De-identify before retrieval, teaching, memory writes, Anki, or vault persistence.
- Use the Brain Dump workflow's artifact write and atomic review-candidate logging.
- For local service/site knowledge, resolve or start the rotation, then log candidates and evaluated Socratic answers with `--origin service`, `--rotation <id>`, and `--convention` when the teaching is a site-local habit, order set, workflow, or preference.
- For portable clinical knowledge, use `--origin assessed` so general topic review can surface it.
- Service-specific recall still uses `startup-recall --lens service --service "<service>" --site "<site>"`.
- Do not create Anki cards during capture; create cards only after evaluated Socratic answers.

## Backend Primitives Kept

The service-memory backend remains active and is used by `/brain-dump` when needed:

```bash
python3 src/study_memory.py rotation-current
python3 src/study_memory.py rotation-start --service "<service>" --site "<site>" [--pgy <n>] [--block "<label>"]
```

Use `rotation-start` only when no active rotation exists or the dictation names a different service/site. Capture `rotation_id` when returned; `log-answer --origin service` may otherwise use the active rotation.

Retrieve service memory using the service-specific `startup-recall` command from `memory-operations.md`.

Interpret the payload as:
- `service_gaps`: primary queue.
- `conventions`: site-local reminders, not universal teaching.
- `formal_secondary`: capped formal support available when Gabriel explicitly asks to compare local practice against formal knowledge.
- `rubric_open`: competency targets worth steering toward.
- `weighting_policy: service_primary_formal_capped`: lead with service gaps; formal material can inform, not dominate.
