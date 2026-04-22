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
#   proactive_probe.json         — queued prerequisite blind-spot probe, if any
#   difficulty_target.json       — ZPD difficulty recommendation
#   adaptive_next_item.json      — IRT/ZPD next concept candidates
#   adaptive_teaching.json       — sparse-aware teaching approach recommendation
#   tutor_strategy.json          — hidden control loop/question-job/mastery-ladder policy
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
echo "[0/12] Applying knowledge decay..."
python3 src/knowledge_graph.py apply_decay 2>&1 | tail -1

# 1. Learner context
echo "[1/12] Fetching learner context..."
python3 src/knowledge_graph.py context "$QUERY" --output "$SESSIONS/learner_context.json" 2>&1

# 2. Transform directives
echo "[2/12] Preparing transform directives..."
python3 src/lance_retriever.py prepare_directives "$QUERY" --output "$SESSIONS/transform_directives.json" 2>&1

# 3. Case log sync — find new case logs not yet in knowledge_graph.db
echo "[3/12] Scanning Case Log for new entries..."
CASE_LOG_DIR="/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Case Log"
SYNC_FILE="$SESSIONS/case_log_sync.txt"

if [[ -d "$CASE_LOG_DIR" ]]; then
    NEW_COUNT=$(python3 src/case_log_sync.py)

    echo "  Found ${NEW_COUNT:-0} new case log(s)"
else
    echo "  Case Log directory not found — skipping"
    > "$SYNC_FILE"
fi

# 4. Doc status (optional)
if [[ -n "$DOC" ]]; then
    echo "[4/12] Checking doc_status for: $DOC"
    python3 src/knowledge_graph.py doc_status "$DOC" > "$SESSIONS/doc_status.json" 2>&1
else
    echo "[4/12] No --doc specified — skipping doc_status"
fi

# 5. Last session narrative — inject prior teaching strategy
echo "[5/12] Fetching last session narrative..."
TOPIC_WORD=$(echo "$QUERY" | awk '{print $1}')
LAST_NAR_ARGS=(python3 src/knowledge_graph.py last_session_narrative)
[[ -n "$SKILL" ]] && LAST_NAR_ARGS+=(--skill "$SKILL")
LAST_NAR_ARGS+=(--topic "$TOPIC_WORD")
"${LAST_NAR_ARGS[@]}" > "$SESSIONS/last_session_narrative.json" 2>/dev/null || echo '{"status":"none_found"}' > "$SESSIONS/last_session_narrative.json"
echo "  Last narrative written to $SESSIONS/last_session_narrative.json"

# 6. Concept review queue — SM-2 scheduled concepts due
echo "[6/12] Fetching concept review queue..."
python3 src/knowledge_graph.py concept_review_queue --n 10 > "$SESSIONS/concept_review_queue.json" 2>/dev/null || echo '{"due_concepts":[],"count":0}' > "$SESSIONS/concept_review_queue.json"
QUEUE_COUNT=$(python3 -c "import json; d=json.load(open('$SESSIONS/concept_review_queue.json')); print(d.get('count',0))" 2>/dev/null || echo 0)
echo "  $QUEUE_COUNT concept(s) due for review"

# 6b. Proactive prerequisite probe — consume one queued unknown-unknown if available
echo "[7/12] Checking proactive prerequisite probe..."
python3 src/unknown_unknowns_scout.py pop --output "$SESSIONS/proactive_probe.json" >/dev/null 2>&1 \
  || echo '{"ok":true,"status":"none"}' > "$SESSIONS/proactive_probe.json"
PROBE_STATUS=$(python3 -c "import json; d=json.load(open('$SESSIONS/proactive_probe.json')); print(d.get('status','none'))" 2>/dev/null || echo "none")
echo "  Proactive probe: $PROBE_STATUS"

# 7. ZPD difficulty recommendation
echo "[8/12] Computing difficulty target..."
python3 src/knowledge_graph.py difficulty_target > "$SESSIONS/difficulty_target.json" 2>/dev/null || echo '{"status":"insufficient_data","recommended_depth":2}' > "$SESSIONS/difficulty_target.json"
ZPD_STATUS=$(python3 -c "import json; d=json.load(open('$SESSIONS/difficulty_target.json')); print(d.get('zpd_status','unknown'))" 2>/dev/null || echo "unknown")
echo "  ZPD status: $ZPD_STATUS"

# 7b. Adaptive next item and teaching approach
echo "[9/12] Computing adaptive next item..."
python3 src/memory_orchestrator.py next-item --mode zpd --topic "$QUERY" --limit 5 > "$SESSIONS/adaptive_next_item.json" 2>/dev/null \
  || echo '{"ok":true,"items":[],"count":0}' > "$SESSIONS/adaptive_next_item.json"
NEXT_COUNT=$(python3 -c "import json; d=json.load(open('$SESSIONS/adaptive_next_item.json')); print(d.get('count',0))" 2>/dev/null || echo 0)
echo "  Adaptive candidate(s): $NEXT_COUNT"

echo "[10/12] Recommending teaching approach..."
python3 src/memory_orchestrator.py recommend-approach --concept "$QUERY" > "$SESSIONS/adaptive_teaching.json" 2>/dev/null \
  || echo '{"ok":true,"approach":"clinical_vignette_transfer","backoff_level":"default","sparse":true}' > "$SESSIONS/adaptive_teaching.json"
TEACHING_APPROACH=$(python3 -c "import json; d=json.load(open('$SESSIONS/adaptive_teaching.json')); print(d.get('approach','unknown'))" 2>/dev/null || echo "unknown")
echo "  Teaching approach: $TEACHING_APPROACH"

# 7c. Hidden tutor strategy — control loop, question job, mastery ladder, playbook
echo "[11/12] Building hidden tutor strategy..."
TUTOR_ARGS=(python3 src/memory_orchestrator.py tutor-strategy "$QUERY" --probe-json "$SESSIONS/proactive_probe.json" --output "$SESSIONS/tutor_strategy.json")
[[ -n "$SKILL" ]] && TUTOR_ARGS+=(--skill "$SKILL")
"${TUTOR_ARGS[@]}" >/dev/null 2>&1 \
  || echo '{"ok":true,"control_state":"calibrate","question_job":"diagnostic_calibration"}' > "$SESSIONS/tutor_strategy.json"
QUESTION_JOB=$(python3 -c "import json; d=json.load(open('$SESSIONS/tutor_strategy.json')); print(d.get('question_job','unknown'))" 2>/dev/null || echo "unknown")
echo "  Question job: $QUESTION_JOB"

# 8. Episodic memory recall — retrieve past learning exchanges relevant to query
echo "[12/12] Recalling episodic memory..."
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
echo "  $SESSIONS/proactive_probe.json (status=$PROBE_STATUS)"
echo "  $SESSIONS/difficulty_target.json (zpd=$ZPD_STATUS)"
echo "  $SESSIONS/adaptive_next_item.json ($NEXT_COUNT candidates)"
echo "  $SESSIONS/adaptive_teaching.json (approach=$TEACHING_APPROACH)"
echo "  $SESSIONS/tutor_strategy.json (question_job=$QUESTION_JOB)"
echo "  $SESSIONS/episodic_memory.json ($RECALL_COUNT recalled)"
