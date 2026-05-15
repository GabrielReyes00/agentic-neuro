# Intraoperative Guide Research Module

Use this module whenever the main `/intraoperative-guide` workflow reaches operative research. This module is agent-agnostic and should be read freshly at the research checkpoint.

## Purpose

Build a compact, high-yield source pack for one operative guide without bloating the final synthesis context. The output of this module is not the guide. It is a research brief that the operative knowledge-map builder can use to construct the procedure model.

## Role

You are the operative research fellow. Your job is to retrieve and extract conduct-changing knowledge: operative sequence, anatomy-risk relationships, instruments, decision points, pitfalls, bail-outs, variants, and postoperative signatures.

Do not write polished prose. Do not summarize everything retrieved. Extract what changes what a resident must do, anticipate, explain, or rescue in the OR.

## Serial Retrieval Rule

Run `lance_retriever.py compare` queries in series. Do not run multiple retrieval calls in parallel; the local embedding stack can contend during model loading and stall. Added latency is acceptable because operative guides are generated one procedure at a time.

Established anatomy and classic operative technique should usually use `--no-frontier`:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "<focused operative query>" --stdout --no-frontier
```

Omit `--no-frontier` when modern literature materially affects patient selection, approach comparison, outcomes, implants, devices, endoscopy, navigation/robotics, radiosurgery adjuncts, monitoring, or complication rates.

## Initial Query Set

Use the decomposition module's retrieval plan as the starting point. Choose exact queries for the procedure, but cover these domains unless clearly inapplicable:

- Operative sequence and named phases.
- Positioning, incision, exposure, bone work, reconstruction, closure.
- Surgical anatomy, corridors, fascial planes, bony limits, venous drainage, vascular territories, cranial nerves, tracts, perforators, and adjacent compartments.
- Danger zones and injury signatures.
- Equipment and setup: blades, retractors, drill bits, microscope/endoscope modes, navigation, fluoroscopy, ultrasound, monitoring, hemostatic tools, clips, shunts, grafts, implants, drains, and closure materials when they change conduct.
- Critical maneuvers and expert-vs-novice errors.
- Bail-outs for bleeding, lost plane, wrong exposure, CSF leak, swelling, hardware malposition, implant failure, inability to proceed, or procedure-specific crisis.
- Immediate postoperative surveillance and complication signatures.
- Variants, conversions, abort criteria, and approach-selection alternatives.

## Research Brief Output

Return a concise research brief with this structure. It should be compact enough to support knowledge mapping without dragging raw retrieval dumps into the synthesis stage:

```markdown
## Source Pack
- Source mix:
- Retrieval limitations:

## Operative Sequence Extracts
- Phase:
  - Conduct-changing details:
  - Source support:

## Anatomy-Risk Extracts
- Structure/space:
  - Why it matters:
  - Injury signature:
  - Avoidance or rescue:
  - Source support:

## Equipment and Setup Extracts
- Item/setup choice:
  - When it matters:
  - Consequence of wrong choice:
  - Source support:

## Critical Maneuver Extracts
- Maneuver:
  - Expert behavior:
  - Novice error:
  - Consequence:
  - Rescue:
  - Source support:

## Pitfalls, Bail-Outs, and Complications
- Problem:
  - Mechanism:
  - Early recognition:
  - Immediate action:
  - Postoperative surveillance:
  - Source support:

## Variants and Decision Branches
- Branch:
  - Trigger:
  - Different conduct:
  - Source support:

## Unresolved Questions
- Question:
  - Why it matters:
  - Repair path: existing context / internal knowledge / RAG / PubMed
  - Suggested focused query:
```

## Context Discipline

If a subagent is used for research, it should return only the research brief and the exact query list it ran. It should not return full retrieval dumps unless the main agent explicitly requests a narrow passage.
