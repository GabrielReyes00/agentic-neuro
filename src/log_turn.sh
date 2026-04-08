#!/usr/bin/env bash
# log_turn.sh — single-call wrapper for log_event + log_study.
# Reduces multi-command drift in interactive learning loops.

set -euo pipefail

cd /Users/gabrielreyes/agentic-neuro
source .venv/bin/activate

TOPIC=""
TOPICS=""
SOURCE=""
SIGNAL_TYPE=""
CATEGORY=""
DEPTH=2
UNDERSTOOD=""
GAPS=""
GAP_DETAILS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --topic) TOPIC="$2"; shift 2 ;;
    --topics) TOPICS="$2"; shift 2 ;;
    --source) SOURCE="$2"; shift 2 ;;
    --signal-type) SIGNAL_TYPE="$2"; shift 2 ;;
    --category) CATEGORY="$2"; shift 2 ;;
    --depth) DEPTH="$2"; shift 2 ;;
    --understood) UNDERSTOOD="$2"; shift 2 ;;
    --gaps) GAPS="$2"; shift 2 ;;
    --gap-details) GAP_DETAILS="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$TOPIC" ]] && { echo "Error: --topic is required" >&2; exit 1; }
[[ -z "$SOURCE" ]] && { echo "Error: --source is required" >&2; exit 1; }
[[ -z "$SIGNAL_TYPE" ]] && { echo "Error: --signal-type is required" >&2; exit 1; }

if [[ -z "$TOPICS" ]]; then
  TOPICS="$TOPIC"
fi

python3 src/knowledge_graph.py log_event \
  --topic "$TOPIC" \
  --source "$SOURCE" \
  --signal-type "$SIGNAL_TYPE" \
  --depth "$DEPTH" \
  --category "$CATEGORY"

LOG_STUDY_CMD=(python3 src/knowledge_graph.py log_study --topics "$TOPICS" --depth "$DEPTH" --source "$SOURCE")

if [[ -n "$UNDERSTOOD" ]]; then
  LOG_STUDY_CMD+=(--understood "$UNDERSTOOD")
fi
if [[ -n "$GAPS" ]]; then
  LOG_STUDY_CMD+=(--gaps "$GAPS")
fi
if [[ -n "$GAP_DETAILS" ]]; then
  LOG_STUDY_CMD+=(--gap-details "$GAP_DETAILS")
fi

"${LOG_STUDY_CMD[@]}"
