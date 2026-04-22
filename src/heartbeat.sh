#!/usr/bin/env bash
# heartbeat.sh — Batch heartbeat logging for all learning skills
# Supports two modes:
#   DOC-ANCHORED (default): log_doc_progress + log_study + optional Obsidian <slug>_review.md
#   SESSION MODE (--session-mode): log_study + log_session_narrative (at complete) + optional Obsidian
#
# Doc-anchored usage (study-material):
#   ./src/heartbeat.sh \
#     --doc "Study Material/slug.md" --doc-type "study-material" \
#     --covered "Q1,Q2,Q3" --understood "Q1,Q3" \
#     --missed '[{"concept":"Q2","error_type":"numerical_recall","misconception":"...","root_cause":"...","error_process":"..."}]' \
#     --coverage-pct 25 --total 12 --topics "topic1,topic2" --depth 3 \
#     [--obsidian-write --topic-name "Brain Anatomy" --slug "brain_anatomy" ...]
#
# Session mode usage (study-session, rag-workflow, intern-bootcamp):
#   ./src/heartbeat.sh --session-mode \
#     --skill "study-session" --slug "pcoma_aneurysm" --topics "PComA anatomy" \
#     --depth 2 --domain "vascular" \
#     --understood "concept A" --gaps "concept B" \
#     --turn-num 4 --status "in-progress|complete" \
#     [--narrative-summary "..." --next-strategy "..." --narrative-failures '[...]'] \
#     [--obsidian-write --topic-name "PComA Aneurysm" \
#      --understood-detail "..." --gaps-detail "..."]

set -euo pipefail

cd /Users/gabrielreyes/agentic-neuro
source .venv/bin/activate

# Parse args
SESSION_MODE=false
DOC="" DOC_TYPE="" COVERED="" UNDERSTOOD="" MISSED="[]" COV_PCT=0 TOTAL=0
TOPICS="" DEPTH=2 GAPS="" GAP_DETAILS=""
OBSIDIAN_WRITE=false TOPIC_NAME="" SLUG="" SESSION_NUM=0 SCORE=""
SKILL="study-material" DOMAIN="general" UNDERSTOOD_DETAIL="" GAPS_DETAIL=""
TURN_NUM=0 STATUS="in-progress"
# Redesign Phase: narrative args
NARRATIVE_SUMMARY="" NEXT_STRATEGY="" NARRATIVE_FAILURES="[]" NARRATIVE_SUCCESSES="[]"
KEY_CONFUSIONS="[]" DEPTH_PROFILE="{}"
# Iteration 3: ZPD tracking
SESSION_SUCCESS_RATE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --session-mode) SESSION_MODE=true; shift ;;
        --doc) DOC="$2"; shift 2 ;;
        --doc-type) DOC_TYPE="$2"; shift 2 ;;
        --covered) COVERED="$2"; shift 2 ;;
        --understood) UNDERSTOOD="$2"; shift 2 ;;
        --missed) MISSED="$2"; shift 2 ;;
        --coverage-pct) COV_PCT="$2"; shift 2 ;;
        --total) TOTAL="$2"; shift 2 ;;
        --topics) TOPICS="$2"; shift 2 ;;
        --depth) DEPTH="$2"; shift 2 ;;
        --gaps) GAPS="$2"; shift 2 ;;
        --gap-details) GAP_DETAILS="$2"; shift 2 ;;
        --obsidian-write) OBSIDIAN_WRITE=true; shift ;;
        --topic-name) TOPIC_NAME="$2"; shift 2 ;;
        --slug) SLUG="$2"; shift 2 ;;
        --session-num) SESSION_NUM="$2"; shift 2 ;;
        --score) SCORE="$2"; shift 2 ;;
        --skill) SKILL="$2"; shift 2 ;;
        --domain) DOMAIN="$2"; shift 2 ;;
        --understood-detail) UNDERSTOOD_DETAIL="$2"; shift 2 ;;
        --gaps-detail) GAPS_DETAIL="$2"; shift 2 ;;
        --turn-num) TURN_NUM="$2"; shift 2 ;;
        --status) STATUS="$2"; shift 2 ;;
        # Redesign Phase: narrative args
        --narrative-summary) NARRATIVE_SUMMARY="$2"; shift 2 ;;
        --next-strategy) NEXT_STRATEGY="$2"; shift 2 ;;
        --narrative-failures) NARRATIVE_FAILURES="$2"; shift 2 ;;
        --narrative-successes) NARRATIVE_SUCCESSES="$2"; shift 2 ;;
        --key-confusions) KEY_CONFUSIONS="$2"; shift 2 ;;
        --depth-profile) DEPTH_PROFILE="$2"; shift 2 ;;
        --session-success-rate) SESSION_SUCCESS_RATE="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

[[ -z "$TOPICS" ]] && { echo "Error: --topics required" >&2; exit 1; }

echo "=== HEARTBEAT ==="

# ---- Step 1: log_doc_progress (doc-anchored mode only) ----
if [[ "$SESSION_MODE" == false ]]; then
    [[ -z "$DOC" ]] && { echo "Error: --doc required in doc-anchored mode" >&2; exit 1; }
    echo "[1/3] log_doc_progress..."
    python3 src/knowledge_graph.py log_doc_progress \
        --doc "$DOC" \
        --doc-type "${DOC_TYPE:-study-material}" \
        --covered "$COVERED" \
        --understood "$UNDERSTOOD" \
        --missed "$MISSED" \
        --coverage-pct "$COV_PCT" \
        --total-concepts "$TOTAL" 2>&1
else
    echo "[1/3] Session mode — skipping log_doc_progress"
fi

# ---- Step 2: log_study ----
echo "[2/3] log_study..."
LOG_STUDY_ARGS=(python3 src/knowledge_graph.py log_study --topics "$TOPICS" --depth "$DEPTH")

[[ -n "$UNDERSTOOD" ]] && LOG_STUDY_ARGS+=(--understood "$UNDERSTOOD")
[[ -n "$GAPS" ]] && LOG_STUDY_ARGS+=(--gaps "$GAPS")
[[ -n "$GAP_DETAILS" ]] && LOG_STUDY_ARGS+=(--gap-details "$GAP_DETAILS")

"${LOG_STUDY_ARGS[@]}" 2>&1

# ---- Step 2b: Real-time Anki queue flush ----
# Flush at every heartbeat. min-queue throttles no-op flushes when the queue
# is empty (passive-only turns, suppressed answers). The session-end heartbeat
# always attempts a flush to drain any remaining candidates.
ANKI_MIN_QUEUE=3
if [[ "$STATUS" == "complete" ]]; then
    ANKI_MIN_QUEUE=1
fi
python3 src/memory_orchestrator.py --quiet flush-anki-queue --min-queue "$ANKI_MIN_QUEUE" 2>/dev/null || true

# ---- Step 3: Obsidian write (optional) ----
if [[ "$OBSIDIAN_WRITE" == true ]]; then
    echo "[3/3] Obsidian review session write..."

    VAULT="/Users/gabrielreyes/Documents/Obsidian/agentic-neuro"
    REVIEW_DIR="$VAULT/Review Sessions"
    DATE=$(date +%Y-%m-%d)
    TIME=$(date +%H:%M)

    [[ -z "$SLUG" ]] && { echo "Error: --slug required for --obsidian-write" >&2; exit 1; }
    [[ -z "$TOPIC_NAME" ]] && TOPIC_NAME="$SLUG"

    mkdir -p "$REVIEW_DIR"

    if [[ "$SESSION_MODE" == true ]]; then
        # ---- SESSION MODE: standalone session file with crash-safe checkpoints ----
        SESSION_FILE="$REVIEW_DIR/${SLUG}.md"

        if [[ -f "$SESSION_FILE" ]]; then
            if [[ "$STATUS" == "complete" ]]; then
                # Replace last IN-PROGRESS status with COMPLETE
                python3 src/heartbeat_utils.py mark-complete "$SESSION_FILE"
                # ---- log_session_narrative (Redesign Phase) ----
                if [[ -n "$NEXT_STRATEGY" || -n "$NARRATIVE_SUMMARY" ]]; then
                    echo "[session-narrative] Logging session narrative..."

                    # Auto-derive key_confusions if not provided by the agent
                    if [[ "$KEY_CONFUSIONS" == "[]" ]]; then
                        DERIVED_CONFUSIONS=$(python3 src/knowledge_graph.py derive_session_confusions \
                            --skill "$SKILL" --hours 4 2>/dev/null | python3 -c \
                            "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('confusions',[]))) if d.get('count',0)>0 else print('[]')" 2>/dev/null || echo "[]")
                        [[ "$DERIVED_CONFUSIONS" != "[]" ]] && KEY_CONFUSIONS="$DERIVED_CONFUSIONS"
                    fi

                    NARRATIVE_ARGS=(python3 src/knowledge_graph.py log_session_narrative --skill "$SKILL" --topics "$TOPICS")
                    [[ -n "$NARRATIVE_SUMMARY" ]] && NARRATIVE_ARGS+=(--summary "$NARRATIVE_SUMMARY")
                    [[ -n "$NEXT_STRATEGY" ]] && NARRATIVE_ARGS+=(--strategy "$NEXT_STRATEGY")
                    [[ "$NARRATIVE_FAILURES" != "[]" ]] && NARRATIVE_ARGS+=(--teaching-failures "$NARRATIVE_FAILURES")
                    [[ "$NARRATIVE_SUCCESSES" != "[]" ]] && NARRATIVE_ARGS+=(--teaching-successes "$NARRATIVE_SUCCESSES")
                    [[ "$KEY_CONFUSIONS" != "[]" ]] && NARRATIVE_ARGS+=(--key-confusions "$KEY_CONFUSIONS")
                    [[ "$DEPTH_PROFILE" != "{}" ]] && NARRATIVE_ARGS+=(--depth-profile "$DEPTH_PROFILE")
                    [[ -n "$SESSION_SUCCESS_RATE" ]] && NARRATIVE_ARGS+=(--session-success-rate "$SESSION_SUCCESS_RATE")
                    NARRATIVE_ARGS+=(--turns "$TURN_NUM")
                    "${NARRATIVE_ARGS[@]}" 2>&1
                fi

                # Append final session summary
                cat >> "$SESSION_FILE" << FINAL_EOF

---

## Session Summary
**Score**: $SCORE

**Understood**: $UNDERSTOOD_DETAIL
**Gaps**:
$(echo "$GAPS_DETAIL" | tr '|' '\n' | sed 's/^/- /')
FINAL_EOF
                echo "Finalized: $SESSION_FILE"
            else
                # Append checkpoint block
                cat >> "$SESSION_FILE" << CHECKPOINT_EOF

### Checkpoint — Turn $TURN_NUM — $TIME
**Topics active**: $TOPICS
**Understood so far**: $UNDERSTOOD_DETAIL
**Active gaps**: $GAPS_DETAIL
**Status**: IN-PROGRESS
CHECKPOINT_EOF
                echo "Checkpoint appended: $SESSION_FILE (Turn $TURN_NUM)"

                # Partial session narrative at checkpoint (for crash-safe continuity)
                # Fires only when --narrative-summary is provided — establishes
                # a forward-looking record so last_session_narrative returns
                # useful context even if the session is compacted or interrupted.
                if [[ -n "$NARRATIVE_SUMMARY" ]]; then
                    PARTIAL_NARRATIVE_ARGS=(python3 src/knowledge_graph.py log_session_narrative
                        --skill "$SKILL" --topics "$TOPICS"
                        --summary "$NARRATIVE_SUMMARY"
                        --turns "$TURN_NUM")
                    [[ -n "$NEXT_STRATEGY" ]] && PARTIAL_NARRATIVE_ARGS+=(--strategy "$NEXT_STRATEGY")
                    [[ "$NARRATIVE_FAILURES" != "[]" ]] && PARTIAL_NARRATIVE_ARGS+=(--teaching-failures "$NARRATIVE_FAILURES")
                    [[ "$KEY_CONFUSIONS" != "[]" ]] && PARTIAL_NARRATIVE_ARGS+=(--key-confusions "$KEY_CONFUSIONS")
                    "${PARTIAL_NARRATIVE_ARGS[@]}" 2>&1 || true  # never fail the checkpoint
                fi
            fi
        else
            # Create new session file with first checkpoint
            cat > "$SESSION_FILE" << SESSION_CREATE_EOF
## Checkpoints

### Checkpoint — Turn $TURN_NUM — $TIME
**Topics active**: $TOPICS
**Understood so far**: $UNDERSTOOD_DETAIL
**Active gaps**: $GAPS_DETAIL
**Status**: IN-PROGRESS

---
date: $DATE
skill: "$SKILL"
topic: "$TOPICS"
domain: "$DOMAIN"
status: "$STATUS"
tags:
  - type/session
  - skill/$SKILL
  - domain/$DOMAIN
  - source/agent
---
SESSION_CREATE_EOF
            echo "Created: $SESSION_FILE"
        fi

        # Update INDEX.md for session mode
        INDEX_FILE="$REVIEW_DIR/INDEX.md"
        if [[ ! -f "$INDEX_FILE" ]]; then
            cat > "$INDEX_FILE" << INDEX_EOF
# Review Sessions Index

| Document | Last Studied | Skill | Status |
|----------|-------------|-------|--------|
| [$TOPIC_NAME](${SLUG}.md) | $DATE | $SKILL | $STATUS |
INDEX_EOF
            echo "Created: $INDEX_FILE"
        else
            if grep -q "${SLUG}.md" "$INDEX_FILE"; then
                # Update existing row
                python3 src/heartbeat_utils.py update-session-index "$INDEX_FILE" "$SLUG" "$TOPIC_NAME" "$DATE" "$SKILL" "$STATUS"
            else
                echo "| [$TOPIC_NAME](${SLUG}.md) | $DATE | $SKILL | $STATUS |" >> "$INDEX_FILE"
            fi
            echo "Updated: $INDEX_FILE"
        fi
    else
        # ---- DOC-ANCHORED MODE: <slug>_review.md (existing behavior) ----
        REVIEW_FILE="$REVIEW_DIR/${SLUG}_review.md"
        COVERED_RANGE="$COVERED"

        if [[ -f "$REVIEW_FILE" ]]; then
            # --- UPSERT: append new session block ---
            python3 src/heartbeat_utils.py update-review-metadata "$REVIEW_FILE" "$DATE" "$SESSION_NUM" "$COV_PCT"

            cat >> "$REVIEW_FILE" << SESSION_EOF

### Session $SESSION_NUM — $DATE
**Coverage**: $COVERED_RANGE | **Score**: $SCORE

**Understood**: $UNDERSTOOD_DETAIL
**Gaps**:
$(echo "$GAPS_DETAIL" | tr '|' '\n' | sed 's/^/- /')
SESSION_EOF

            echo "Updated: $REVIEW_FILE (Session $SESSION_NUM)"
        else
            # --- CREATE: new review session file ---
            cat > "$REVIEW_FILE" << REVIEW_EOF
## Concept Map Status
| Topic | Questions | Cumulative Score | Status |
|-------|-----------|-----------------|--------|
| (updated by agent at session end) | | | |

---

## Session Log

### Session $SESSION_NUM — $DATE
**Coverage**: $COVERED_RANGE | **Score**: $SCORE

**Understood**: $UNDERSTOOD_DETAIL
**Gaps**:
$(echo "$GAPS_DETAIL" | tr '|' '\n' | sed 's/^/- /')

---
title: "Review Sessions: $TOPIC_NAME"
source_document: "$DOC"
study_material: "$DOC"
total_topics: $TOTAL
total_questions: $TOTAL
last_studied: $DATE
session_count: $SESSION_NUM
coverage_pct: $COV_PCT
tags:
  - type/session
  - skill/$SKILL
  - domain/$DOMAIN
  - source/agent
---
REVIEW_EOF

            echo "Created: $REVIEW_FILE"
        fi

        # Update INDEX.md for doc-anchored mode
        INDEX_FILE="$REVIEW_DIR/INDEX.md"
        if [[ ! -f "$INDEX_FILE" ]]; then
            cat > "$INDEX_FILE" << INDEX_EOF
# Review Sessions Index

| Document | Last Studied | Sessions | Coverage |
|----------|-------------|----------|----------|
| [$TOPIC_NAME](${SLUG}_review.md) | $DATE | $SESSION_NUM | ${COV_PCT}% |
INDEX_EOF
            echo "Created: $INDEX_FILE"
        else
            if grep -q "${SLUG}_review.md" "$INDEX_FILE"; then
                # Update existing row
                python3 src/heartbeat_utils.py update-docanchor-index "$INDEX_FILE" "$SLUG" "$TOPIC_NAME" "$DATE" "$SESSION_NUM" "$COV_PCT"
            else
                echo "| [$TOPIC_NAME](${SLUG}_review.md) | $DATE | $SESSION_NUM | ${COV_PCT}% |" >> "$INDEX_FILE"
            fi
            echo "Updated: $INDEX_FILE"
        fi
    fi
else
    echo "[3/3] Obsidian write skipped (--obsidian-write not set)"
fi

echo "=== HEARTBEAT COMPLETE ==="
