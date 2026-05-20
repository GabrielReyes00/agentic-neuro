# Review Artifacts

Single-purpose contract for routine learning artifacts and vault destinations.

Session bookkeeping lives entirely in `data/study_memory.db`. No skill writes session logs to a vault folder. Post-session integrity verification confirms the database write.

## Auto-Regenerated Interfaces

Routine learning-session bookkeeping lives in the memory database; use `study_memory.py summary` for learner-state context unless a workflow explicitly writes a vault artifact.

These are read-only outputs. Agents never hand-edit them.

- `Dashboard.md`: live snapshot of coverage, open errors, weak concepts, stale knowledge, and recent sessions.
- `ACGME Readiness.md`: PGY-1 curriculum view with progress overlay and higher-PGY catalog.
- `ACGME Canvases/*.canvas`: one canvas per ACGME milestone, every topic colored by mastery.
- `Concepts/INDEX.md`: domain-grouped glossary index.

## Vault-Producing Skills

| Skill | Vault destination | Purpose |
|---|---|---|
| `study-material` | `Study Material/<Title>.md` | Q&A document |
| `consult` | `Consults/<Topic Title>.md` | Pocket card |
| `generate-report` | `Reports/<Title>.md` | Encyclopedic reference |
| `intraoperative-guide` | `Operative Guides/<Title>.md` | Operative rehearsal guide |
| `grand-rounds` | `Presentations/Cases\|Articles/<Title>.md` | Presentation note |

`study-review` writes no vault artifact in either invocation mode; the memory layer is the durable record. No H1 in any vault file because filename is the title. YAML metadata belongs at bottom.

## Cleanup

Remove only workflow-owned transient files under `data/Sessions/`. Do not use broad cleanup.
