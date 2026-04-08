# Gemini CLI Harness Audit (2026-04-05)

## Scope
Audit and hardening pass focused on Gemini CLI reliability for:
- routing correctness (no implicit RAG/Transform)
- learner context hydration before direct clinical answers
- per-turn learning signal logging reliability
- Anki blind-validation enforcement before dispatch

## Key Findings (Pre-fix)
1. Critical behavior was mostly prompt-enforced (soft), not script-enforced (hard).
2. Internal `rag-transform` command was publicly exposed via `.gemini/commands/rag-transform.toml`.
3. Anki workflow required blind validation in docs, but dispatch path had no hard gate for validation evidence.
4. Per-turn logging in command docs required dual calls (`log_event` + `log_study`), increasing skip/misorder risk in Flash.
5. Direct-answer path lacked deterministic routing + context-hydration mechanism.

## Changes Implemented
1. Added deterministic query router: `src/gemini_query_gate.py`
   - Classifies query route using Tier 1/Tier 2 trigger policy
   - Supports context hydration for direct clinical answers (`--hydrate-context`)
2. Added per-turn logging wrapper: `src/log_turn.sh`
   - Single call writes both `log_event` and `log_study`
3. Added Anki hard validation gate in `src/anki_sync_cli.py`
   - New command: `validate_final_cards`
   - Dispatch now validates `final_cards.json` first via `_validate_final_cards_payload()`
   - Enforces per-card `blind_validation` metadata + top-level `validation_report`
4. Removed public internal command exposure
   - Deleted `.gemini/commands/rag-transform.toml`
   - Kept `rag-transform.md` as internal sub-task spec only
5. Updated Gemini instruction/harness docs
   - `GEMINI.md`: added mandatory non-slash turn gateway and internal-only `rag-transform` guard
   - `.gemini/commands/anki-sync.md/.toml`: added Step 6.5 validation gate
   - `.gemini/commands/rag-workflow.md/.toml`: switched to `log_turn.sh`
   - `.gemini/commands/study-session.md/.toml`: switched to `log_turn.sh`
   - `.gemini/commands/study-material.md/.toml`: switched to `log_turn.sh`
   - `.gemini/commands/explain-topic.md/.toml`: added learner-context prepass

## Audit Automation
Added: `src/audit_gemini_harness.py`

Run:
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/audit_gemini_harness.py --json
```

Current result: **11 / 11 checks passing**.

## Verification Performed
- `python3 -m py_compile src/gemini_query_gate.py src/audit_gemini_harness.py src/anki_sync_cli.py`
- `bash -n src/log_turn.sh src/preflight.sh src/heartbeat.sh`
- `python3 src/audit_gemini_harness.py --json` (all checks pass)

## Residual Risk
- Gemini can still skip steps if command instructions are ignored entirely; this pass reduces that risk by moving key controls into executable gates.
- Full end-to-end behavior still depends on model compliance for command invocation itself; operational monitoring is recommended after rollout.
