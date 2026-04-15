#!/usr/bin/env python3
"""Memory context injection for agent CLI hooks.

Reads stdin for the hook payload, queries the knowledge graph for current
session state and relevant episodic memories, outputs a compact memory
block. Claude-style hooks consume the plaintext block directly. Gemini hooks
require JSON, so this script emits `additionalContext` for BeforeAgent events.

Usage:
  python3 src/precompact_memory_inject.py
"""

from __future__ import annotations

import json
import sys
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from kg_constants import BASE_DIR
sys.path.insert(0, str(BASE_DIR / "src"))


def _load_hook_payload() -> dict[str, object]:
    """Read hook payload from stdin, defaulting to an empty dict."""
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return {}
        return {str(key): value for key, value in payload.items()}
    except Exception:
        return {}


# Claude Code sends PascalCase event names; Gemini sends lowercase/snake_case.
_CLAUDE_HOOK_EVENTS = frozenset({
    "PreCompact", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "Stop", "Notification",
})


def _hook_event_name(payload: Mapping[str, object]) -> str:
    return str(payload.get("hook_event_name") or payload.get("hookEventName") or "").strip()


def _is_gemini_hook(payload: Mapping[str, object]) -> bool:
    """Return True when invoked by Gemini CLI (non-Claude hook event)."""
    name = _hook_event_name(payload)
    return bool(name) and name not in _CLAUDE_HOOK_EVENTS


def _is_claude_structured_hook(payload: Mapping[str, object]) -> bool:
    """Return True when invoked by a known Claude Code hook event."""
    return _hook_event_name(payload) in _CLAUDE_HOOK_EVENTS


def _gemini_output(additional_context: str = "") -> None:
    """Emit Gemini BeforeAgent hook-compatible JSON."""
    payload: dict[str, object] = {"suppressOutput": True}
    if additional_context:
        payload["hookSpecificOutput"] = {"additionalContext": additional_context}
    print(json.dumps(payload))


def _claude_output(additional_context: str = "", event_name: str = "") -> None:
    """Emit Claude hook-compatible JSON.

    UserPromptSubmit supports hookSpecificOutput.additionalContext with hookEventName.
    PreCompact and all other Claude hooks inject context via top-level systemMessage.
    """
    payload: dict[str, object] = {"suppressOutput": True}
    if additional_context:
        if event_name == "UserPromptSubmit":
            payload["hookSpecificOutput"] = {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": additional_context,
            }
        else:
            payload["systemMessage"] = additional_context
    print(json.dumps(payload))


def _recent_session_exchanges(kg, since_iso: str) -> list[sqlite3.Row]:
    """Return compact exchange rows from the active session window."""
    return kg.conn.execute(
        """SELECT le.session_ts, le.turn_number, le.concept_text, le.answer_text,
                  le.answer_correct, le.error_type, le.misconception,
                  le.root_cause, le.teaching_approach, le.question_text,
                  le.correction_text, le.retrieval_sources,
                  t.display_name AS topic_display,
                  me.payload_json
           FROM learning_exchanges le
           LEFT JOIN topics t ON le.topic_id = t.topic_id
           LEFT JOIN memory_events me ON le.memory_event_id = me.memory_event_id
           WHERE le.session_ts >= ?
           ORDER BY le.session_ts DESC, le.turn_number DESC
           LIMIT 15""",
        (since_iso,),
    ).fetchall()


def _payload(row: sqlite3.Row) -> dict[str, object]:
    """Return parsed memory_event payload for a learning exchange row."""
    try:
        data = json.loads(row["payload_json"] or "{}")
        if not isinstance(data, dict):
            return {}
        return {str(key): value for key, value in data.items()}
    except Exception:
        return {}


def _clip(text: object | None, limit: int = 140) -> str:
    """Clip text compactly on a word boundary for hook context."""
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    head = clean[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return f"{head}..."


def _sentence(text: str) -> str:
    """Ensure a clipped phrase has one clean sentence terminator."""
    clean = text.strip()
    if not clean:
        return ""
    return clean if clean.endswith((".", "?", "!", "...")) else f"{clean}."


def _append_session_summary(lines: list[str], recent: list[sqlite3.Row]) -> list[str]:
    """Append current-session topic and correctness summary."""
    topics = sorted(set(
        str(row["topic_display"] or row["concept_text"]) for row in recent
        if row["topic_display"] or row["concept_text"]
    ))
    correct = sum(1 for row in recent if int(row["answer_correct"] or 0) == 2)
    incorrect = sum(1 for row in recent if int(row["answer_correct"] or 0) == 0)
    partial = sum(1 for row in recent if int(row["answer_correct"] or 0) == 1)
    lines.append(f"Topics this session: {', '.join(topics[:5])}")
    lines.append(f"Exchanges: {len(recent)} total, {correct} correct, "
                 f"{partial} partial, {incorrect} incorrect")
    lines.append("")
    return topics


def _append_error_summary(lines: list[str], recent: list[sqlite3.Row]) -> None:
    """Append compact errors that should persist in active agent context."""
    errors = [row for row in recent if int(row["answer_correct"] or 0) == 0]
    if not errors:
        return
    lines.append("Errors to re-test:")
    for error in errors[:5]:
        concept = _clip(error["concept_text"], 60)
        misconception = _clip(error["misconception"], 110)
        correction = _clip(error["correction_text"], 120)
        root = _clip(error["root_cause"], 130)
        payload = _payload(error)
        remediation = _clip(payload.get("remediation"), 130)
        line = f"  - {concept}"
        if error["error_type"]:
            line += f" [{error['error_type']}]"
        if misconception:
            line += f" (misconception: {misconception})"
        if root:
            line += f" Root cause: {_sentence(root)}"
        if correction:
            line += f" [correct: {correction}]"
        if remediation:
            line += f" Next: {_sentence(remediation)}"
        lines.append(line)
    lines.append("")


def _append_partial_summary(lines: list[str], recent: list[sqlite3.Row]) -> None:
    """Append partial answers that should be repaired, not treated as unknown."""
    partials = [row for row in recent if int(row["answer_correct"] or 0) == 1]
    if not partials:
        return
    lines.append("Partial answers to repair:")
    for row in partials[:5]:
        payload = _payload(row)
        concept = _clip(row["concept_text"], 60)
        misconception = _clip(row["misconception"], 110)
        root = _clip(row["root_cause"], 130)
        remediation = _clip(payload.get("remediation") or row["correction_text"], 130)
        line = f"  - {concept}"
        if row["error_type"]:
            line += f" [{row['error_type']}]"
        if misconception:
            line += f" Partial gap: {_sentence(misconception)}"
        if root:
            line += f" Root cause: {_sentence(root)}"
        if remediation:
            line += f" Next: {_sentence(remediation)}"
        lines.append(line)
    lines.append("")


def _append_correct_calibration(lines: list[str], recent: list[sqlite3.Row]) -> None:
    """Append correct-answer nuance so agents avoid flattening mastery."""
    correct_rows = [row for row in recent if int(row["answer_correct"] or 0) == 2]
    if not correct_rows:
        return

    entries = []
    for row in correct_rows:
        payload = _payload(row)
        confidence = str(payload.get("response_confidence") or "")
        approach = str(row["teaching_approach"] or "")
        concept = _clip(row["concept_text"], 60)
        note = ""
        if confidence == "low":
            note = "correct but low confidence; reinforce briefly, do not reteach from scratch"
        elif "superficial" in approach:
            enrich = _clip(row["correction_text"], 130)
            note = "correct but shallow"
            if enrich:
                note += f"; enrich with: {enrich}"
        elif row["answer_text"] and len(row["answer_text"]) > 120:
            note = "strong mechanistic explanation; use as an anchor/transfer point"
        if note:
            entries.append(f"  - {concept}: {note}.")

    if entries:
        lines.append("Correct-answer calibration:")
        lines.extend(entries[:5])
        lines.append("")


def _append_teaching_approaches(lines: list[str], recent: list[sqlite3.Row]) -> None:
    """Append teaching approaches used in the active session."""
    approaches_used = {
        str(row["teaching_approach"])
        for row in recent
        if row["teaching_approach"]
    }
    if approaches_used:
        lines.append(f"Teaching approaches used: {', '.join(sorted(approaches_used))}")


def _append_next_session_strategy(
    lines: list[str],
    kg,
    topics: list[str],
    active_session_ts: str,
) -> None:
    """Append the most relevant recent next-session strategy if available."""
    try:
        narrative_rows: list[sqlite3.Row] = kg.conn.execute(
            """SELECT next_session_strategy, topics_json, session_ts, skill
               FROM session_narratives
               WHERE next_session_strategy IS NOT NULL
                 AND next_session_strategy != ''
                 AND session_ts >= ?
               ORDER BY session_ts DESC
               LIMIT 10""",
            (active_session_ts,),
        ).fetchall()
        topic_terms = [topic.lower() for topic in topics]
        narrative_row = None
        for row in narrative_rows:
            try:
                narrative_topics = json.loads(row["topics_json"] or "[]")
                if not isinstance(narrative_topics, list):
                    narrative_topics = []
            except Exception:
                narrative_topics = []
            haystack = " ".join(str(topic).lower() for topic in narrative_topics)
            if haystack and any(term and (term in haystack or haystack in term) for term in topic_terms):
                narrative_row = row
                break
        if narrative_row and narrative_row["next_session_strategy"]:
            lines.append("")
            lines.append("Next-session strategy (from last completed session):")
            lines.append(f"  {_clip(narrative_row['next_session_strategy'], 300)}")
    except Exception:
        pass


def _append_recent_evolution(lines: list[str], kg, cutoff_iso: str) -> None:
    """Append recent concept status transitions."""
    try:
        rows: list[sqlite3.Row] = kg.conn.execute(
            """SELECT ce.timestamp, ce.trigger_type, ce.previous_status, ce.status,
                      ce.evolution_note, cm.concept_text
               FROM concept_evolution ce
               JOIN concept_mastery cm ON ce.concept_id = cm.concept_id
               WHERE ce.timestamp >= ?
               ORDER BY ce.timestamp DESC
               LIMIT 8""",
            (cutoff_iso,),
        ).fetchall()
        if not rows:
            return
        lines.append("")
        lines.append("Recent concept status transitions (last 7 days):")
        for event in rows[:5]:
            concept = _clip(event["concept_text"], 60)
            note = _clip(event["evolution_note"], 100)
            trigger_type = event["trigger_type"] or ""
            previous_status = event["previous_status"] or "?"
            new_status = event["status"] or "?"
            lines.append(f"  - {concept}: {previous_status} → {new_status} ({trigger_type})")
            if note:
                lines.append(f"    {note}")
    except Exception:
        pass


def _append_prior_memory(
    lines: list[str],
    kg,
    topics: list[str],
    prior_cutoff: str,
    before_iso: str,
) -> None:
    """Append relevant prior-session memory for current topics."""
    if not topics:
        return
    try:
        topic_conditions = " OR ".join(
            "t.display_name LIKE ?" for _ in topics[:3]
        )
        topic_params = [f"%{topic}%" for topic in topics[:3]]
        rows: list[sqlite3.Row] = kg.conn.execute(
            f"""SELECT le.concept_text, le.answer_correct, le.misconception
                 FROM learning_exchanges le
                 LEFT JOIN topics t ON le.topic_id = t.topic_id
                 WHERE le.session_ts >= ?
                   AND le.session_ts < ?
                   AND ({topic_conditions})
                 ORDER BY le.session_ts DESC
                 LIMIT 5""",
            [prior_cutoff, before_iso] + topic_params,
        ).fetchall()
        if not rows:
            return
        lines.append("")
        lines.append("Relevant prior session memory:")
        for exchange in rows[:3]:
            correct_label = {0: "INCORRECT", 1: "PARTIAL", 2: "CORRECT"}.get(
                int(exchange["answer_correct"] or 0), "?"
            )
            concept = (exchange["concept_text"] or "")[:40]
            misconception = (exchange["misconception"] or "")[:50]
            one_liner = f"{concept} ({correct_label})"
            if misconception:
                one_liner += f" -- {misconception}"
            lines.append(f"  - {one_liner}")
    except Exception:
        pass


def _build_memory_block(kg) -> str:
    """Build compact active-session memory text, or return empty string."""
    now = datetime.now(timezone.utc)
    two_hours_ago = (now - timedelta(hours=2)).isoformat()

    recent = _recent_session_exchanges(kg, two_hours_ago)
    if not recent:
        return ""

    lines = ["## Active Session Memory (auto-injected)"]
    lines.append("")
    topics = _append_session_summary(lines, recent)
    _append_error_summary(lines, recent)
    _append_partial_summary(lines, recent)
    _append_correct_calibration(lines, recent)
    _append_teaching_approaches(lines, recent)
    active_session_ts = max(row["session_ts"] for row in recent if row["session_ts"])
    _append_next_session_strategy(lines, kg, topics, active_session_ts)
    _append_recent_evolution(lines, kg, (now - timedelta(days=7)).isoformat())
    _append_prior_memory(
        lines,
        kg,
        topics,
        prior_cutoff=(now - timedelta(days=30)).isoformat(),
        before_iso=two_hours_ago,
    )
    lines.append("")
    lines.append("(End of injected session memory)")
    return "\n".join(lines)


def main() -> int:
    hook_payload = _load_hook_payload()
    hook_name = _hook_event_name(hook_payload)
    gemini_hook = _is_gemini_hook(hook_payload)
    claude_hook = _is_claude_structured_hook(hook_payload)

    # Import KG
    try:
        from knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
    except Exception:
        if gemini_hook:
            _gemini_output()
        elif claude_hook:
            _claude_output(event_name=hook_name)
        return 0  # silent failure — don't block the agent

    try:
        output = _build_memory_block(kg)
        if gemini_hook:
            _gemini_output(output)
        elif claude_hook:
            _claude_output(output, event_name=hook_name)
        elif output:
            print(output)

        kg.close()
    except Exception:
        try:
            kg.close()
        except Exception:
            pass
        if gemini_hook:
            _gemini_output()
        elif claude_hook:
            _claude_output(event_name=hook_name)
        return 0  # never block the agent

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
