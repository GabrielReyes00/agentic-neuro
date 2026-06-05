# Service Log

Deprecated compatibility surface. New clinical-experience capture should use `/brain-dump`, which now owns de-identified service teaching, Brain Dump artifacts, service-origin review candidates, optional Socratic conversion, and service/site memory logging.

Keep this file only so older wrappers still have a safe route. Do not add new behavior here. If `/service-log` is invoked, follow `.agents/shared/commands/brain-dump.md` and preserve these service-memory rules:

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

```bash
python3 src/study_memory.py startup-recall --lens service --service "<service>" --site "<site>" [--rotation <id>] [--context "<upcoming/context>"]
```

Interpret the payload as:
- `service_gaps`: primary queue.
- `conventions`: site-local reminders, not universal teaching.
- `formal_secondary`: legacy capped formal support; do not use it unless explicitly requested because current service-specific recall should stay service/local.
- `rubric_open`: competency targets worth steering toward.
- `weighting_policy: service_primary_formal_capped`: lead with service gaps; formal material can inform, not dominate.
