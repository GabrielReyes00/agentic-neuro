# Service Log

`/service-log` is the service-debrief entry point to
`.agents/shared/commands/shift-debrief.md`. Follow that artifact workflow while
preserving site/service provenance for rotations, local conventions, and
operational habits.

## Service Context

De-identify first. Resolve the active rotation:

```bash
python3 src/study_memory.py rotation-current
python3 src/study_memory.py rotation-start --service "<service>" --site "<site>" [--pgy <n>] [--block "<label>"]
```

Use `rotation-start` only when there is no active rotation or the debrief names a
different service/site. Preserve the returned rotation identifier.

- Portable clinical teaching uses `--origin assessed`.
- A site/service habit, order set, workflow, or preference uses `--origin
  service`, the rotation identifier, and `--convention` when applicable.
- Service-specific context uses `startup-recall --lens service --service
  "<service>" --site "<site>"`.
- `service_gaps` leads the queue; `conventions` are locally confirmable reminders;
  `formal_secondary` is capped supporting evidence; `rubric_open` may steer
  competency targets. Honor `weighting_policy: service_primary_formal_capped`.

Use Shift Debrief installation and `shift-debrief-candidate-add` semantics.
Initial capture creates no Anki cards or mastery. If Gabriel accepts Socratic
review, evaluated local answers retain `--origin service` and local provenance;
evaluated portable knowledge retains the assessed namespace.
