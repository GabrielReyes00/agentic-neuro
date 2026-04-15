#!/usr/bin/env bash
# preflight.sh — Batch pre-flight for all learning skills
# Combines: learner context + transform directives + case log sync + optional doc_status
#           + last session narrative + concept review queue + episodic memory recall
# Usage: ./src/preflight.sh "query" [--doc "Study Material/slug.md"] [--skill "study-session"]
#
# Outputs (all to data/Sessions/):
#   learner_context.json         — knowledge graph context for the query
#   transform_directives.json    — pre-computed directives from learner context + confusion matrix
#   case_log_sync.txt            — new case logs found (if any)
#   doc_status.json              — document study state (only if --doc provided)
#   last_session_narrative.json  — most recent session narrative for these topics
#   concept_review_queue.json    — SM-2 scheduled concepts due for review
#   difficulty_target.json       — ZPD difficulty recommendation
#   episodic_memory.json         — past learning exchanges relevant to query

set -euo pipefail

cd /Users/gabrielreyes/agentic-neuro
source .venv/bin/activate

QUERY="${1:?Usage: preflight.sh \"query\" [--doc \"Study Material/slug.md\"] [--skill X]}"
shift

DOC=""
SKILL=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --doc) DOC="$2"; shift 2 ;;
        --skill) SKILL="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

SESSIONS="data/Sessions"
mkdir -p "$SESSIONS"

echo "=== PREFLIGHT START ==="

# 0. Apply decay — passive decay without a daemon; fires at the start of every session
#    so that confidence decay and SM-2 due-date marking are always current, even after
#    study breaks.
echo "[0/8] Applying knowledge decay..."
python3 src/knowledge_graph.py apply_decay 2>&1 | tail -1

# 1. Learner context
echo "[1/8] Fetching learner context..."
python3 src/knowledge_graph.py context "$QUERY" --output "$SESSIONS/learner_context.json" 2>&1

# 2. Transform directives
echo "[2/8] Preparing transform directives..."
python3 src/lance_retriever.py prepare_directives "$QUERY" --output "$SESSIONS/transform_directives.json" 2>&1

# 3. Case log sync — find new case logs not yet in knowledge_graph.db
echo "[3/8] Scanning Case Log for new entries..."
CASE_LOG_DIR="/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Case Log"
SYNC_FILE="$SESSIONS/case_log_sync.txt"

if [[ -d "$CASE_LOG_DIR" ]]; then
    # Use a single Python pass to avoid O(N×M) shell loops on larger case logs.
    NEW_COUNT=$(python3 - <<'PY'
import json
import sqlite3
from pathlib import Path

case_log_dir = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Case Log")
sync_file = Path("data/Sessions/case_log_sync.txt")
db_path = Path("data/knowledge_graph.db")

existing: set[str] = set()
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT se.metadata FROM signal_events se WHERE se.source='case_log'"
        ).fetchall()
        for (raw_meta,) in rows:
            if not raw_meta:
                continue
            try:
                meta = json.loads(raw_meta)
            except Exception:
                continue
            source_file = meta.get("source_file")
            if source_file:
                existing.add(Path(source_file).name)
    finally:
        conn.close()

case_files = sorted(
    p for p in case_log_dir.glob("*.md")
    if p.name != "INDEX.md" and not p.name.startswith("_")
)
new_files = [str(p) for p in case_files if p.name not in existing]
sync_file.write_text("\n".join(new_files) + ("\n" if new_files else ""), encoding="utf-8")
print(len(new_files))
PY
)

    echo "  Found ${NEW_COUNT:-0} new case log(s)"
else
    echo "  Case Log directory not found — skipping"
    > "$SYNC_FILE"
fi

# 4. Doc status (optional)
if [[ -n "$DOC" ]]; then
    echo "[4/8] Checking doc_status for: $DOC"
    python3 src/knowledge_graph.py doc_status "$DOC" > "$SESSIONS/doc_status.json" 2>&1
else
    echo "[4/8] No --doc specified — skipping doc_status"
fi

# 5. Last session narrative — inject prior teaching strategy
echo "[5/8] Fetching last session narrative..."
TOPIC_WORD=$(echo "$QUERY" | awk '{print $1}')
LAST_NAR_ARGS=(python3 src/knowledge_graph.py last_session_narrative)
[[ -n "$SKILL" ]] && LAST_NAR_ARGS+=(--skill "$SKILL")
LAST_NAR_ARGS+=(--topic "$TOPIC_WORD")
"${LAST_NAR_ARGS[@]}" > "$SESSIONS/last_session_narrative.json" 2>/dev/null || echo '{"status":"none_found"}' > "$SESSIONS/last_session_narrative.json"
echo "  Last narrative written to $SESSIONS/last_session_narrative.json"

# 6. Concept review queue — SM-2 scheduled concepts due
echo "[6/8] Fetching concept review queue..."
python3 src/knowledge_graph.py concept_review_queue --n 10 > "$SESSIONS/concept_review_queue.json" 2>/dev/null || echo '{"due_concepts":[],"count":0}' > "$SESSIONS/concept_review_queue.json"
QUEUE_COUNT=$(python3 -c "import json; d=json.load(open('$SESSIONS/concept_review_queue.json')); print(d.get('count',0))" 2>/dev/null || echo 0)
echo "  $QUEUE_COUNT concept(s) due for review"

# 7. ZPD difficulty recommendation
echo "[7/8] Computing difficulty target..."
python3 src/knowledge_graph.py difficulty_target > "$SESSIONS/difficulty_target.json" 2>/dev/null || echo '{"status":"insufficient_data","recommended_depth":2}' > "$SESSIONS/difficulty_target.json"
ZPD_STATUS=$(python3 -c "import json; d=json.load(open('$SESSIONS/difficulty_target.json')); print(d.get('zpd_status','unknown'))" 2>/dev/null || echo "unknown")
echo "  ZPD status: $ZPD_STATUS"

# 8. Episodic memory recall — retrieve past learning exchanges relevant to query
echo "[8/8] Recalling episodic memory..."
python3 src/knowledge_graph.py recall "$QUERY" --max 5 --compact --sqlite-only \
  --output "$SESSIONS/episodic_memory.json" 2>/dev/null \
  || echo '{"exchanges":[],"episode_summaries":[],"patterns":{}}' > "$SESSIONS/episodic_memory.json"
RECALL_COUNT=$(python3 -c "import json; d=json.load(open('$SESSIONS/episodic_memory.json')); print(len(d.get('exchanges',[])))" 2>/dev/null || echo 0)
echo "  $RECALL_COUNT relevant past exchange(s) recalled"

echo "=== PREFLIGHT COMPLETE ==="
echo "Outputs:"
echo "  $SESSIONS/learner_context.json"
echo "  $SESSIONS/transform_directives.json"
echo "  $SESSIONS/case_log_sync.txt ($(wc -l < "$SYNC_FILE" | tr -d ' ') new)"
[[ -n "$DOC" ]] && echo "  $SESSIONS/doc_status.json"
echo "  $SESSIONS/last_session_narrative.json"
echo "  $SESSIONS/concept_review_queue.json ($QUEUE_COUNT due)"
echo "  $SESSIONS/difficulty_target.json (zpd=$ZPD_STATUS)"
echo "  $SESSIONS/episodic_memory.json ($RECALL_COUNT recalled)"
