# Review Artifacts

Single-purpose contract for routine learning artifacts and vault destinations.

Session bookkeeping lives entirely in `data/study_memory.db`. No skill writes session logs to a vault folder. Post-session integrity verification confirms the database write.

## Auto-Regenerated Interfaces

Routine learning-session bookkeeping lives in the memory database. Use
`study_memory.py startup-recall` for teaching/workflow context; raw `summary` is
reserved for dashboards and deliberate audits. Vault artifact writes remain
workflow-specific.

These are read-only outputs. Agents never hand-edit them.

- `Dashboard.md`: live snapshot of coverage, open errors, weak concepts, stale knowledge, and recent sessions.
- `ACGME Readiness.md`: PGY-1 curriculum view with progress overlay and higher-PGY catalog.
- `ACGME Canvases/*.canvas`: one canvas per ACGME milestone, every topic colored by mastery.
- `Concepts/INDEX.md`: domain-grouped concept-card index.

## Vault-Producing Skills

| Skill | Vault destination | Purpose |
|---|---|---|
| `study-material` | `Study Material/<Title>.md` | Q&A document |
| `consult` | `Consults/<Topic Title>.md` | Pocket card |
| `shift-debrief` | `Shift Debriefs/<Topic Title>.md` | De-identified service-teaching artifact |
| `generate-report` | `Reports/<Title>.md` | Encyclopedic reference |
| `intraoperative-guide` | `Operative Guides/<Title>.md` | Operative rehearsal guide |
| `grand-rounds` | `Presentations/Cases\|Articles/<Title>.md` | Presentation note |
| `journal-club` | `Journal Club/<Short Article Title>.md` | Article mastery dossier |

`shift-debrief` and `journal-club` artifact generation do not establish learner
mastery; learner-state evidence arises only from later tested review. `study-review`
writes no vault artifact in either invocation mode; the memory layer is the durable
record. No H1 in any vault file because filename is the title. YAML metadata belongs
in native top-of-file Obsidian frontmatter.

Managed binary companions:

| Artifact | Vault destination |
|---|---|
| Journal Club PDF | `Journal Club/Sources/<Short Article Title>.pdf` |
| Article presentation deck | `Presentations/Decks/Articles/<Title>.pptx` |
| Case presentation deck | `Presentations/Decks/Cases/<Title>.pptx` |
| Study-source deck or handout | `Study Material/Sources/<Title>.<ext>` |

After any managed binary import or move, refresh `src/vault_library.py` and require
zero integrity failures.

## Cleanup

Remove only manifest-registered `transient` files beneath the current
`RUN_DIR`. Do not use broad cleanup or touch legacy session files.
