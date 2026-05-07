# Study Session Architect

Use only when the user explicitly asks what to study, requests a study plan, or wants a study session.

Follow `.agents/shared/commands/learning-session-contract.md`.

## Step 0: Recall and Continuity

```bash
python3 src/study_memory.py recall --topic "<topic or general>"
python3 src/study_memory.py status
```

If the user has not specified a topic, use `status` output to identify weak concepts and open errors, then propose a topic. If the user asks "what should I study?", pick the topic with the most open errors or weakest concepts and explain why.

If `recall` returns prior data, apply the Recall Interpretation Rules from the shared contract. Shape the session around `Next strategy`, retest `OPEN ERRORS`, skip `KNOWN CONCEPTS`, and never repeat `RECENT EXCHANGES`.

If the user has selected a specific Obsidian document, apply Requested-Document Priority: use the document as the primary curriculum and weave prior context only when directly prerequisite, confusable, safety-critical, or a single brief bridge.

## Step 1: Compose Session Plan

| Component | Time | Source | Skip Rule |
|---|---:|---|---|
| Error Retests | 5 min | Open errors from recall | Skip if none |
| Gap Remediation | 10 min | Gaps from recall, matched by error_type | Skip if none |
| New Territory | 10 min | Uncovered concepts from doc or topic | Never skip |
| Transfer Challenge | 5 min | Known concepts applied in new context | Skip if none |

Redistribute skipped time to New Territory.

Remediation routing (from recall interpretation rules):

| Error type | Mode |
|---|---|
| `numerical_recall` | Clinical vignette where the number changes the plan |
| `conceptual_confusion` | Forced discrimination |
| `cross_contamination` | Confusable-pair side-by-side |
| `application_failure` | New clinical context |
| `reasoning_gap` | Causal scaffold |
| `omission` | Case where omitted element causes harm |

## Step 2: Present Plan

Show components, selected topics, mode rationale, and any skipped components. Ask for approval before execution.

## Step 3: Execute

Ask one question at a time. After every evaluated learner answer, run `log-answer` silently with `--skill "study-session"`.

Follow Cognitive Friction Protocol: each prompt ends at the question. No hints, no answer context, no teaching until after the learner commits.

Follow Progressive Landscape Reveal: grade briefly, reveal one layer, ask the targeted follow-up.

Component behavior:

1. Error Retests: probe the misconception from a new angle (never the same question). Use the error_type to pick the teaching move.
2. Gap Remediation: use the error-matched mode from the table above.
3. New Territory: start with calibration if topic is new, then advance up the mastery ladder.
4. Transfer Challenge: one scenario applying a known concept in a new clinical context.

## Step 4: Summary and Finish

Summarize outcomes: what was retested, what was newly learned, what gaps remain, one learner-pattern insight.

Run `end-session` with a specific `--next-strategy` that tells the next agent exactly what to do. Offer Anki, another session, or end.

Write a rich final draft to `data/Sessions/study_session_<slug>_artifact.md`, then install and validate with the Final Artifact Guard (see shared contract).

The final note must include: Session Plan, Question And Answer Log, Component Outcomes, Gaps And Error Metadata, Next Session Priority.

Run concept extraction per CLAUDE.md protocol. Clean up `data/Sessions/` temps.
