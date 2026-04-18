---
name: log_improvement
description: Document the current iteration's agentic improvements to Agentic Improvements.txt for recursive AI improvement loops. Run this after completing an improvement cycle.
---

# Log Improvement Iteration

You are documenting a completed improvement iteration for the recursive AI improvement loop. The output is appended to `Agentic Improvements.txt` at the repo root and must be optimized for AI model consumption — the next model reads this to understand what changed, what passed, and what to improve next.

## Execution Pipeline

1. **Gather current state metrics** (run all silently):
   ```bash
   # Database state
   python3 -c "
   import sqlite3; conn = sqlite3.connect('data/knowledge_graph.db'); conn.row_factory = sqlite3.Row
   for t in ['topics','curriculum_topics','concept_mastery','concept_relationships','signal_events','session_narratives','anki_card_stats']:
       c = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]; print(f'{t}: {c}')
   "
   # Vault file counts
   VAULT="/Users/gabrielreyes/Documents/Obsidian/agentic-neuro"
   for d in Concepts Reports "Operative Guides" "Study Material" "Review Sessions" "Error Atlas" "ACGME Canvases"; do
     echo "$d: $(find "$VAULT/$d" -name "*.md" 2>/dev/null | wc -l | tr -d ' ') files"
   done
   # Vault format audit is now covered by the post-session hook format guards.
   # Post-session hook test
   python3 src/universal_post_session_hook.py --skill "audit" --topics "audit" --vault-writes "" --report-out /tmp/audit_hook.json 2>/dev/null
   python3 -c "import json; r=json.load(open('/tmp/audit_hook.json')); print('hook ok:', r.get('ok')); print('metrics:', json.dumps(r.get('metrics',{})))"
   # Canvas stats
   python3 src/vault_canvas_builder.py 2>/dev/null | python3 -c "import sys,json; print(json.loads(sys.stdin.read()))"
   # Git log for iteration commits
   git log --oneline -20
   ```

2. **Read the existing Agentic Improvements.txt** to understand the document structure and the last iteration number.

3. **Review all changes made in this session.** Use `git diff` and `git status` to identify what files changed. Read modified files if needed to understand the change. Also review any task lists or conversation context for what was accomplished and why.

4. **Compose the iteration entry.** Append to section 10 (ITERATION LOG) of `Agentic Improvements.txt`. Follow this exact structure:

```
  ITERATION N (YYYY-MM-DD to YYYY-MM-DD):
    MOTIVATION: <1-2 sentences: what prompted this iteration>
    CHANGES:
      + <new_file.py> (NEW) — <what it does, key design decisions>
      * <modified_file.py> — <what changed and why>
      - <deleted_file.py> — <why removed>
    PASSED:
      - <benchmark description>: <result>
      [one line per validation from section 7 that was run]
    FAILED/DEFERRED:
      - <what didn't work and why>
    DB STATE DELTA:
      <any table row count changes from previous iteration>
    VAULT STATE DELTA:
      <any file count changes from previous iteration>
```

5. **Update sections 2 (DATABASE STATE) and the vault file counts in section 1a** with current numbers.

6. **Update section 5 (KNOWN LIMITATIONS)** — remove items that were fixed, add new items discovered during this iteration.

7. **Re-prioritize section 6 (FUTURE DIRECTIONS)** based on what was learned. Move completed items out. Add new ideas. Re-rank if priorities shifted.

8. **Write the updated file** using the Edit tool to append/modify the relevant sections.

## Quality Criteria

The document must answer these questions for the next AI model:
- What is the CURRENT state of every component? (not historical — update stale numbers)
- What CHANGED in this iteration and WHY?
- What PASSED validation and what DIDN'T?
- What should the NEXT iteration focus on and WHY?
- What INVARIANTS must never be violated?

Write for an AI that has never seen this repo. Be precise with file paths, line counts, table names, and metric values. Avoid vague language ("improved performance" — say "edge count increased from 2 to 10"). Include the exact commands to validate claims.
