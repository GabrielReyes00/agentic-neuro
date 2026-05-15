# Intraoperative Guide Operative Knowledge Map Module

Use this module after the research brief is complete and before drafting the guide.

## Purpose

Build the intermediate reasoning artifact that deep research workflows require. The final guide must be written from this map, not directly from raw RAG snippets.

The operative knowledge map is a scratch artifact. It should not be copied into the final Obsidian guide.

## Role

You are building the operative mental model of the procedure. Organize retrieved sources, internal expert knowledge, and unresolved questions into a map that can survive attending-level questioning.

## Map Standards

Every important entry should connect knowledge to operative consequence. Avoid trivia. If a fact does not change conduct, risk prediction, rescue, postoperative recognition, or oral defense, it does not belong in the map.

Use source support when available. Mark source gaps honestly.

## Required Output

Return this structure:

```markdown
## Operative Mental Model
- Core purpose:
- Essential sequence logic:
- What must be true before starting:
- What must be true before closing:

## Indication and Approach-Selection Map
- Scenario/anatomy:
  - Best approach or variant:
  - Why:
  - When not to use it:
  - Source support:

## Phase-by-Phase Conduct Map
- Phase:
  - Objective:
  - Landmark proving correct location:
  - Action sequence:
  - Structure most at risk:
  - Decision point:
  - Novice error:
  - Expert behavior:
  - Recovery move:
  - Source support:

## Anatomy-Risk Map
- Structure/space:
  - Where encountered:
  - Function/supply/drainage/plane/bony relationship:
  - Why vulnerable:
  - Injury signature:
  - Avoidance:
  - Rescue or consequence management:
  - Source support:

## Equipment and Setup Map
- Item/setup choice:
  - Why it matters:
  - When it changes conduct:
  - Wrong-choice consequence:
  - Source support:

## Critical Maneuver Map
- Maneuver:
  - Why it determines outcome:
  - Expert behavior:
  - Novice error:
  - Failure consequence:
  - Rescue:
  - Source support:

## Failure-Mode and Bailout Map
- Failure mode:
  - Operative cause:
  - Early recognition:
  - Immediate action:
  - Escalation/abort/convert threshold:
  - Postoperative signature:
  - Source support:

## Closure and Postoperative Causality Map
- Postoperative finding:
  - Likely intraoperative cause:
  - First evaluation:
  - First action:
  - Source support:

## Attending Defense Map
- Question:
  - Expected answer:
  - Where guide must answer it:

## Unresolved or Weak Areas
- Gap:
  - Why it matters:
  - Repair path: existing context / internal knowledge / RAG / PubMed
  - Suggested query:
```

## Map Review Gate

Before guide drafting, adversarially review the map:

- Does the map cover every major phase of the operation?
- Does every named danger structure have an injury signature and avoidance/rescue logic?
- Are critical maneuvers linked to novice errors and recovery moves?
- Are postoperative checks tied to intraoperative mechanisms?
- Are source gaps identified?
- Could the map answer the attending defense questions?

If the map fails, repair the map before drafting. Do not draft the guide from a weak map.
