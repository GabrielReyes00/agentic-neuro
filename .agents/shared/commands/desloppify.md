---
name: desloppify
description: Code quality audit and single-fix improvement loop for agentic-neuro. First invocation scans the entire codebase and builds a prioritized backlog. Each subsequent invocation fixes exactly one issue and pauses for confirmation before the next pass.
---

# desloppify — Code Quality Loop

One issue fixed per invocation. State persists between runs. You control the pace.

---

## Entry Logic

```bash
cd /Users/gabrielreyes/agentic-neuro && ls .quality/backlog.md 2>/dev/null && echo "FIX_MODE" || echo "SCAN_MODE"
```

- **SCAN_MODE** (file missing) → run Phase 1
- **FIX_MODE** (file exists) → run Phase 2

---

## Phase 1: Scan Mode (first invocation only)

Audit all 7 quality categories. Collect concrete, actionable findings. Write the scored backlog.

### 1.1 Initialize

```bash
cd /Users/gabrielreyes/agentic-neuro && mkdir -p .quality
grep -q "^\.quality" .gitignore || echo ".quality/" >> .gitignore
```

### 1.2 Category Scans

Run ALL of the following scans before writing anything. Collect findings as you go.

---

#### Category A: Shell Complexity [max 15 pts]

Read these files in full:

```bash
cd /Users/gabrielreyes/agentic-neuro && wc -l scripts/sync_vault.sh
```

Then read each one:
- `scripts/sync_vault.sh`

Flag each of the following as a finding:

1. **Embedded Python heredoc** (`<<'PY'` ... `PY` blocks) — each block is a separate finding. These are untestable, invisible to static analysis, and break if indentation or quoting changes. Penalty: **-4 pts each**.

2. **`sed -i ''` on structured data** (markdown tables, YAML blocks, key: value lines) — fragile string replacement on structured formats that belong in Python. Penalty: **-2 pts each**.

3. **Bash function or code block >40 lines** doing logic (conditionals, loops, data transformation) that would be clearer and testable as a Python function. Penalty: **-2 pts** per block over 40 lines.

Cap total deduction at -15.

---

#### Category B: Type Coverage [max 20 pts]

Find public methods missing return type annotations across the critical API surface:

```bash
cd /Users/gabrielreyes/agentic-neuro && grep -n "^    def [a-z]\|^def [a-z]" \
  src/study_memory.py \
  src/lance_retriever.py \
  src/anki_queue.py \
  
  src/learning_artifact_guard.py \
  | grep -v "^\s*#" | grep -v " -> " | head -60
```

Flag each public method (no leading `_`) without a `->` return type as a finding. Focus on methods that are called from skill files or from other modules — internal helpers are lower priority.

For each finding: read the actual method signature to confirm it lacks annotations and is public-facing.

Penalty: **-2 pts** per untyped public method in a critical module. Cap at -20.

---

#### Category C: KG Contract Compliance [max 25 pts]

This is the highest-risk category. Undocumented commands cause silent pipeline failures.

**Step 1** — Extract documented commands from CLAUDE.md §13. Read the Command Reference section:

```bash
cd /Users/gabrielreyes/agentic-neuro && grep -A 200 "## §13 Command Reference" CLAUDE.md | grep -E "^\w|^# " | head -60
```

List every subcommand that `study_memory.py` is documented to accept (e.g., `recall`, `log-answer`, `end-session`, `status`, `add-alias`).

**Step 2** — Extract actual implemented subcommands:

```bash
cd /Users/gabrielreyes/agentic-neuro && grep -n "add_parser\|\.add_parser" src/study_memory.py | head -80
```

**Step 3** — Cross-reference. For each mismatch:
- Documented in CLAUDE.md but not in argparse → **-5 pts** (dangerous: skill files call a command that doesn't exist)
- In argparse but not documented in CLAUDE.md §12 → **-3 pts** (undiscoverable by agents)

Cap total deduction at -25.

---

#### Category D: Skill Parity [max 10 pts]

```bash
cd /Users/gabrielreyes/agentic-neuro && \
  ls .claude/commands/*.md | xargs -I{} basename {} .md | sort > /tmp/_des_claude.txt && \
  ls .gemini/commands/*.md | xargs -I{} basename {} .md | sort > /tmp/_des_gemini.txt && \
  diff /tmp/_des_claude.txt /tmp/_des_gemini.txt
```

Flag skills with no counterpart on the other platform: **-3 pts each**.

For matched skills with counterparts, compare the step ordering and behavioral logic (not metadata/frontmatter). Pick 3-4 matched pairs most likely to have drifted (e.g., `study-session`, `rag-workflow`, `intern-bootcamp`, `anki-sync`) and read both versions of each. Flag significant behavioral divergence: **-2 pts each**.

Cap total deduction at -10.

---

#### Category E: Dead / Orphaned Code [max 15 pts]

Find functions defined across all src modules:

```bash
cd /Users/gabrielreyes/agentic-neuro && grep -rn "^def \|^    def " src/*.py \
  | grep -v "__init__\|__repr__\|__str__\|__enter__\|__exit__\|__del__" \
  | grep -v "\.pyc" | head -80
```

For any function that looks potentially unreferenced, check if it's called anywhere:

```bash
cd /Users/gabrielreyes/agentic-neuro && grep -rn "FUNCTION_NAME" src/ .claude/commands/ .gemini/commands/ .agents/ CLAUDE.md
```

Also check for unused imports in the most import-heavy files:

```bash
cd /Users/gabrielreyes/agentic-neuro && grep -n "^import \|^from " \
  src/study_memory.py src/lance_retriever.py src/anki_queue.py \
  src/learning_artifact_guard.py | head -50
```

Penalty: **-4 pts** per confirmed orphaned function (defined, never called, not part of public API contract). **-1 pt** per confirmed unused import. Cap at -15.

---

#### Category F: Docstring Quality [max 10 pts]

The mixin classes are the most-called API surface. Check their public methods for docstrings:

```bash
cd /Users/gabrielreyes/agentic-neuro && grep -n "    def [a-z]\|^def [a-z]" \
  src/study_memory.py src/learning_artifact_guard.py
```

For each public method found, read 2-3 lines after the `def` line to check if a docstring (`"""`) immediately follows. Methods with no docstring where the logic is non-obvious are findings.

Penalty: **-2 pts** per public mixin method with no docstring and non-trivial logic. Cap at -10.

---

#### Category G: Test Coverage [max 5 pts]

```bash
cd /Users/gabrielreyes/agentic-neuro && \
  ls tests/ test_*.py src/test_*.py 2>/dev/null || echo "NO_TEST_INFRASTRUCTURE"
```

The 5 critical paths — each untested costs **-1 pt**:
1. `study_memory.py` → `log-answer` argument validation and concept upsert
2. `study_memory.py` → `recall` topic matching with alias expansion
3. `study_memory.py` → `end-session` stats computation and strategy persistence
4. `lance_retriever.py` → `search` fusion and reranking pipeline
5. `anki_queue.py` → enqueue validation and novelty dedup behavior

Cap at -5.

---

### 1.3 Compute Score and Write Backlog

After all 7 scans, compute:

```
initial_score = 100 - (total deductions across all categories, respecting per-category caps)
```

Create `.quality/backlog.md` with this exact structure:

```markdown
# Desloppify Backlog

## Score
**Current: XX/100** | Scan date: YYYY-MM-DD | Items resolved: 0 | Items remaining: N

## Rubric
| Category | Max Pts | Lost | Remaining |
|---|---|---|---|
| A: Shell Complexity | 15 | X | X |
| B: Type Coverage | 20 | X | X |
| C: KG Contract Compliance | 25 | X | X |
| D: Skill Parity | 10 | X | X |
| E: Dead/Orphaned Code | 15 | X | X |
| F: Docstring Quality | 10 | X | X |
| G: Test Coverage | 5 | X | X |
| **Total** | **100** | **XX** | **XX** |

## Queue

### [DES-001] Category A — Short descriptive title
**File**: scripts/sync_vault.sh:42
**Category**: A
**Severity**: high
**Points**: 4
**Status**: open
**Issue**: One-sentence description of exactly what is wrong and why it matters.
**Fix**: Concrete, actionable instruction — what to change, where, and what the result should look like.

---

### [DES-002] ...
```

**Ordering rules**: Sort by Severity (high → medium → low), then by Points (most first), then Category C before others when tied. Severity mapping: Category C findings = high; Category A embedded Python = high; Category B/E = medium; Category D/F/G = low.

**Write the file using the Write tool.**

---

### 1.4 Show Report and Stop

Display the full rubric table and queue to the user. Then stop and ask:

```
Scan complete. Initial score: XX/100. N issues queued across 7 categories.

Highest-priority item: [DES-001] — <title> (+X pts when fixed)

Run /desloppify again to fix DES-001. Or review the backlog at .quality/backlog.md first.
```

**Do not proceed to Phase 2. Stop here.**

---

## Phase 2: Fix Mode (every invocation after the first)

### 2.1 Read Current Backlog

```bash
cd /Users/gabrielreyes/agentic-neuro && cat .quality/backlog.md
```

Find the **first item** where `**Status**: open`. If no open items remain, show the final score and declare completion — do not ask to run again.

Note the item's ID, category, file(s), points, and the Fix instruction.

### 2.2 Read the Target File(s) in Full

Read every file listed in the item's `**File**:` field using the Read tool. Understand the surrounding context fully before making any edit.

### 2.3 Apply the Fix

Follow the `**Fix**:` instruction precisely. Adhere to CLAUDE.md §1 directives throughout:
- No new files unless the fix genuinely requires one (e.g., extracting an embedded Python block to a module)
- Scope is limited to the specific issue — do not clean up surrounding code
- No comments added unless the logic is genuinely non-obvious after the fix
- Prefer Edit over Write for existing files

**Category-specific guidance:**

- **A (Shell heredoc)**: Extract the Python block to a standalone helper function in an appropriate existing `src/` module. Replace the heredoc in the shell script with a `python3 src/<module>.py <subcommand> "$ARG1" "$ARG2"` call. The helper must accept the same inputs via `sys.argv` or argparse and produce the same output. Do not rewrite the entire shell script — scope to the single heredoc being resolved.

- **A (sed -i on structured data)**: Replace `sed -i ''` lines with a targeted Python one-liner or helper that uses proper string/regex operations with encoding safety. Same scope constraint.

- **B (Type annotations)**: Add `->` return type and parameter type annotations to the specific method. Import any needed types from `typing` or `collections.abc` at the top of the file. Do not add annotations to other methods not in this item's scope.

- **C (Contract mismatch)**: Either add the missing argparse subcommand handler (if the command is genuinely needed and its behavior is defined in CLAUDE.md), or update CLAUDE.md §13 to remove/correct the stale entry. Confirm with the fix instruction which direction applies.

- **D (Skill parity)**: Update the lagging skill file to match the leading one. Do not introduce new behavior — only sync what already exists in one but not the other.

- **E (Dead code)**: Delete the orphaned function or unused import. Verify with grep that nothing references it first.

- **F (Docstring)**: Add a concise docstring immediately after the `def` line. One sentence on what the method does, one on key parameters if non-obvious. No elaborate type documentation — type annotations cover that.

- **G (Test)**: Create `tests/test_<module>.py` (create `tests/__init__.py` if needed). Write a focused unit or integration test for the specific critical path. Use the real database/files where practical; mock only external services (AnkiConnect, PubMed).

### 2.4 Verify the Fix

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 -c "
import sys
sys.path.insert(0, 'src')
# For Python changes — confirm the module imports cleanly
import <changed_module>
print('Import OK')
"
```

For shell script changes:
```bash
bash -n scripts/sync_vault.sh && echo "Syntax OK"
```

For skill file changes: confirm the edited behavior is consistent with CLAUDE.md §4–§10.

### 2.5 Update the Backlog

Using the Edit tool on `.quality/backlog.md`:

1. Change `**Status**: open` → `**Status**: resolved` on the fixed item
2. Update the Score header line:
   - Increment `Items resolved` by 1
   - Decrement `Items remaining` by 1
   - Add the item's Points to the Current score number
3. Update the Rubric table: subtract the item's Points from the "Lost" column of its category row, add them to "Remaining"

### 2.6 Report and Pause

Show the user:

```
Fixed: [DES-XXX] <title>
File: <path:line>
Change: <one sentence describing what was changed and why>

Score: XX → YY/100 (+Z pts)
Items resolved: N | Items remaining: M
```

Then identify the next open item from the backlog and pause:

```
Next up: [DES-XXX+1] <title> (+Z pts)

Run /desloppify to fix it. Or stop here — state is saved.
```

**Do not fix the next item. Stop here.**

---

## Scoring Rubric

| Category | Max | Priority Rationale |
|---|---|---|
| C: KG Contract Compliance | 25 | Missing commands cause silent skill failures — highest patient-safety risk for a clinical learning tool |
| B: Type Coverage | 20 | Untyped public API on a 2200-LOC KnowledgeGraph class causes call-site bugs that are hard to trace |
| E: Dead/Orphaned Code | 15 | Misleads future edits; inflates cognitive load on already-dense modules |
| A: Shell Complexity | 15 | Embedded Python in bash is untestable, breaks on encoding edge cases, and is invisible to linters |
| F: Docstring Quality | 10 | Mixin API called by all 14 skills — missing docs means misuse goes undetected |
| D: Skill Parity | 10 | Claude/Gemini behavioral drift means one agent silently gets incorrect guidance |
| G: Test Coverage | 5 | Zero tests means no regression safety net on the record-answer → KG → vault pipeline |

The score only improves when code is actually changed. Do not mark an item resolved without making the fix.

---

## Rescan Rule

After every **5 resolved items**, re-run Phase 1 before the next fix. Some fixes (especially Category C and A) expose new findings that weren't visible before. Rescan to keep the backlog accurate. When rescanning: do not reset the score — carry forward the current resolved count and score, then add any new findings found.

---

## Key Rules

1. One fix per invocation. Always stop and ask after the fix.
2. Never delete items from the backlog — only change their Status.
3. Never mark resolved without making the actual code change.
4. Always read the full file before editing — understand context before touching anything.
5. Fixes must be consistent with CLAUDE.md conventions (§1 universal directives, §4 vault structure, §11 data locations, §12 command reference).
6. Shell script fixes are scoped to the specific block — never rewrite an entire script in one pass.
7. `.quality/backlog.md` is the single source of truth for progress. Do not track state anywhere else.
