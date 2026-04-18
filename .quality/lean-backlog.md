# Delete-First Lean Backlog

Status: accepted items complete
Score: 95/100
Last updated: 2026-04-15

## Metrics

| Metric | Baseline | Current | Net |
|---|---:|---:|---:|
| Command-doc LOC, including shared cores | ~4,350 | 1,582 | ~-2,768 |
| Tracked diff LOC | 7,214 touched | 176 added / 7,038 deleted | -6,862 |
| Shared command cores | 0 | 16 files / 1,342 LOC | +1,342 |
| Per-agent command files | 30 full docs | 30 wrappers / 240 LOC | large reduction |
| `knowledge_graph_cli.py` | 1,186 | 1,086 | -100 |
| `kg_learning.py` | 2,828 | 2,783 | -45 |
| `lance_retriever.py` | 3,625 | 3,302 | -323 |
| `universal_post_session_hook.py` | 737 | 726 | -11 |
| Historical plan docs | 2,592 | 0 | -2,592 |
| `scripts/topic_hygiene.py` | 462 | 0 | -462 |
| `requirements.txt` | 23 | 20 | -3 |

Scorecard:

| Category | Points | Status |
|---|---:|---|
| Skill Text Deduplication | 25/25 | All Claude/Gemini command bodies share agent-agnostic cores; required per-agent `.md` files remain |
| CLI / Command Surface Consolidation | 18/20 | Removed memory aliases from KG CLI, removed Lance no-op cache command/flag, removed one stale backfill command |
| Dead / Legacy Code Deletion | 15/15 | Deleted stale Agent Plans and one-time topic hygiene script after reference checks |
| Large Module Simplification | 14/15 | Added retrieval/session behavior tests, removed unreferenced Lance diagnostics, and slimmed post-session dashboard rendering |
| Shell / Workflow Slimming | 8/10 | Existing shell helper extraction retained and verified; no new shell orchestration added |
| Dependency / Data Hygiene | 10/10 | Removed unused `requests`, ignored backup noise, cleaned generated local noise, tracked only lean backlog under `.quality` |
| Test Efficiency | 4/5 | Added focused retrieval/session tests only where they unlocked net-negative deletion |

## Completed Items

| ID | Category | Files | Before | After | Net | Risk | Verification | Rollback |
|---|---|---|---:|---:|---:|---|---|---|
| LEAN-001 | Skill Text Deduplication | `.claude/commands/*.md`, `.gemini/commands/*.md`, `.agents/shared/commands/*.md` | ~4,350 command-doc LOC | 1,582 command-doc LOC | ~-2,768 | Low | `wc -l .claude/commands/*.md .gemini/commands/*.md .agents/shared/commands/*.md`; `rg 'Read and follow' .claude/commands .gemini/commands` | Restore per-agent command bodies from git history |
| LEAN-002 | CLI / Command Surface | `src/lance_retriever.py` | 3,625 | 3,608 | -17 | Low | `rg 'clear_cache|force_refresh|force-refresh' src/lance_retriever.py .agents .claude .gemini CLAUDE.md GEMINI.md` has no hits | Re-add parser option and no-op function from git history |
| LEAN-003 | CLI / Command Surface | `src/knowledge_graph_cli.py`, `CLAUDE.md`, `GEMINI.md` | KG CLI exposed memory aliases | Memory routes through `src/memory_orchestrator.py` | -93 in CLI | Low | `python3 src/knowledge_graph.py --help` has no `memory_*`; `python3 src/memory_orchestrator.py --help` lists memory commands | Re-add alias parser branches and docs |
| LEAN-004 | Dead / Legacy Code | `Agent Plans/*.txt` | 2,592 | 0 | -2,592 | Low | `rg 'Agentic Improvements|Long-term Agentic Memory Plan|Repo Refactor Plan|Agent Plans' . --glob '!Agent Plans/*.txt'` has no hits | Restore deleted files from git history |
| LEAN-005 | Dead / Legacy Code | `scripts/topic_hygiene.py` | 462 | 0 | -462 | Medium | `rg 'topic_hygiene' .` has no hits | Restore script from git history if the old hardcoded migration is needed |
| LEAN-006 | CLI / Command Surface | `src/kg_learning.py`, `src/knowledge_graph_cli.py`, `CLAUDE.md` | `backfill_specificity` method and parser | Removed | -52 | Medium | `rg 'backfill_specificity|backfill_topic_specificity' .` has no hits | Restore method and parser from git history |
| LEAN-007 | Dependency / Data Hygiene | `requirements.txt` | `requests>=2.31` | removed | -3 | Low | `rg 'import requests|requests\\.' src scripts tests` has no hits | Re-add dependency if future code imports it |
| LEAN-008 | Dependency / Data Hygiene | `.gitignore`, repo-local generated files | `.quality/` fully ignored; generated noise present | `lean-backlog.md` tracked, generated quality state ignored; `.DS_Store`/`__pycache__` removed | 0 tracked LOC | Low | `git status --short`; `.gitignore` allows `.quality/lean-backlog.md` | Revert `.gitignore` hunk if `.quality` should remain fully local |
| LEAN-009 | Large Module Simplification | `src/lance_retriever.py`, `tests/test_lance_retriever.py` | Retrieval diagnostics wrote sidecars and exposed debug CLIs | Removed `passage_manifest`, `retrieval_coverage`, `pipeline_attrition`, `audit_citations`, `attrition_report`; retained scratch-context IDs | -327 in module | Medium | `python3 -m unittest tests.test_lance_retriever`; `rg 'audit_citations|attrition_report|passage_manifest|retrieval_coverage|pipeline_attrition' src tests .gitignore` has no hits | Restore diagnostic functions/parser from git history |
| LEAN-010 | Retrieval Behavior Fix | `src/lance_retriever.py`, `tests/test_lance_retriever.py` | Append merge parser did not handle `[P#] [TEXTBOOK THEORY]` blocks | Source-block regex now accepts optional passage IDs; merge dedup covered by test | +1 net code line, unlocks safe diagnostic deletion | Low | `test_merge_source_blocks_deduplicates_and_preserves_frontier` | Revert regex change |
| LEAN-011 | Session Behavior Coverage | `src/kg_learning.py`, `tests/test_knowledge_graph.py` | Session narrative fingerprint behavior untested | Added test for topic fingerprint match/no-match and key-confusion JSON decoding | test-only | Low | `test_last_session_narrative_matches_topic_fingerprint` | Remove test if replaced by broader KG behavior suite |
| LEAN-012 | Large Module Simplification | `src/universal_post_session_hook.py` | Four repeated vault asset render blocks | Single loop renders assets with per-section empty text | -11 | Low | `python3 -m py_compile src/universal_post_session_hook.py` | Restore explicit blocks from git history |

## Deferred Candidates

These are intentionally not open backlog items because reference or data-state proof is insufficient for same-pass deletion:

| Candidate | Reason deferred |
|---|---|
| `migrate_confusion_matrix`, `seed_prerequisites`, `seed_topic_adjacency`, `backfill_topic_fingerprints` | Still documented as manual maintenance, schema comments reference them, and live DB state was not audited in this pass |
| Deep ranking/filtering changes in `lance_retriever.py` | Core retrieval quality still needs stable LanceDB fixture assertions before changing ranking, filtering, parent expansion, or axis budgeting |
| `kg_memory.py` recall fusion simplification | Reference checks show helpers are live; deletion would need recall-ranking fixtures covering structured, keyword, FTS, and semantic branches |
| Further `universal_post_session_hook.py` rendering changes | Small dashboard duplication was removed; larger rendering moves need golden-output tests to avoid vault format drift |
| Top-level `CLAUDE.md` / `GEMINI.md` shared-core extraction | Possible future reduction; deferred because these are agent bootstrap contracts and need agent-specific smoke tests |

## Final Verification Commands

Required before marking this pass complete:

```bash
python3 -m unittest discover -s tests
python3 -m py_compile src/*.py src/anki_sync/*.py
bash -n src/heartbeat.sh src/preflight.sh scripts/sync_vault.sh
python3 src/knowledge_graph.py --help
python3 src/memory_orchestrator.py --help
python3 src/lance_retriever.py --help
```
