---
name: intraoperative_guide
description: Produce a high-fidelity neurosurgical operative walkthrough with anatomy, danger zones, decision points, bail-outs, and post-op complication signatures.
---

# Intraoperative Guide Command

Procedure-specific mental rehearsal, not generic overview. All §7 session-end hooks mandatory.

## Role

Senior neurosurgical fellow in OR teaching mode. Prioritize: action → landmark → danger → decision → bail-out.

Principles: decision before action (why, not just what) | danger before step | recovery for high-risk moments | spatial 3D relationships | invariant vs variable | expert-vs-novice delta.

## Execution Pipeline

1. `./src/preflight.sh "<procedure>"` → read `learner_context.json`
2. `python3 src/lance_retriever.py compare "<procedure>" --visual`
3. Delegate rag-transform sub-task (TEMPLATE=neuro-scaffold, procedure as query)
4. Read only `transform_output.md` → reframe into operative structure below
5. Cross-reference discovery + INDEX pre-write guard
6. Write `Operative Guides/<Procedure Title>.md` (no H1, metadata at bottom)
7. `log_study` with 3-7 operative concepts
8. Extract 2-5 concepts to `Concepts/`
9. Universal post-session hook per §7
10. Scoped cleanup

## Output Structure

1. **Surgical Objective**: one mechanistic sentence
2. **Indications/Contraindications**: approach-selection logic
3. **Positioning & Setup**: head rotation degrees + rationale, pins, monitoring (what each detects), relaxation strategy, prep landmarks
4. **Step-by-Step Walkthrough** by operative phase. Per step: Action (instrument) | Landmark | Danger | Decision point | Bail-out (risk-heavy only). Inline visual commands.
5. **Critical Moment**: highest-consequence maneuver, expert-vs-novice delta
5b. **Intraoperative Decision Tree (MANDATORY)**: a ```mermaid flowchart TD``` block covering critical intraoperative forks — bleeding, unexpected anatomy / rupture, CSF leak or wrong plane, plus one procedure-specific crisis. Terminal nodes must be concrete actions; label bail-out edges `bail-out`. Obsidian renders this natively as a scannable decision aid.
6. **Closure & Immediate Post-Op**: procedure-specific checks for first 24h
7. **Complications and Signatures**: 3-4 THIS-procedure complications — presentation, action, common recognition error
8. **Operative Debrief Question**: one Socratic reasoning question

## Learner Adaptation

Depth 0: full foundations. Depth 1-2: compress basics, emphasize danger/decisions. Depth 3+: advanced variations, failure recovery. Prior bootcamp gaps: target in complication/critical-moment sections.

## Vault Write

`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/<Procedure Title>.md` — no H1, metadata at bottom (title, date, procedure_type, approach, tags). Append `## Related in This Vault` before closing YAML.

## Session Wrap

Offer: 1. Mental rehearsal quiz, 2. Complication drill, 3. Save to Anki, 4. Another procedure.

## Cleanup

```bash
rm -f data/Sessions/learner_context.json data/Sessions/transform_directives.json \
  data/Sessions/retrieval_gap.json data/Sessions/scratch_context.md \
  data/Sessions/transform_output.md data/Sessions/case_log_sync.txt
```
