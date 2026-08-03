# Intraoperative Guide Decomposition Module

Use this module immediately after procedure resolution and complexity routing, before RAG retrieval.

## Purpose

Create a procedure-specific research and mastery blueprint. This prevents generic retrieval and stops the guide from becoming a section-filling exercise.

The output is not the guide. It is a decomposition plan that tells the researcher what must be learned, tells the map builder what mental model must exist, and tells the reviewers what coverage must be tested.

## Role

You are the operative planning fellow. Your job is to break the requested procedure into the first-principle knowledge blocks a resident must master to understand, perform, troubleshoot, and defend the operation.

## Depth Anchor: Standalone Preoperative Readiness

The guide must give a neurosurgery resident the cognitive structure to plan,
mentally execute, recognize danger, recover, and defend the procedure while
stating what still requires hands-on OR/cadaver experience or atlas figures.
Use observable readiness outcomes, not an unverifiable mastery percentage.

The Coverage Matrix below operationalizes this target. Every block must be
addressed or marked not applicable with a reason. Sections may be compact when a
domain is genuinely simple, but no domain may be silently dropped.

## Decomposition Rules

Do not use arbitrary numerical quotas for steps, instruments, or citations. The decomposition should be as large or small as the procedure requires, but it must be specific to the operation.

For each domain, ask: *"What knowledge changes conduct, safety, interpretation, rescue, or oral defense?"*

## Required Output

Return this structure:

```markdown
## Procedure Frame
- Title:
- Complexity: simple | intermediate | complex
- Canonical operation:
- Common variants:
- Likely pathologies/indications:
- Main operative objective:

## Coverage Matrix (depth anchor — every block must be addressable)

Mark each block with the planned source (RAG / PubMed / internal knowledge / textbook page) and a one-line scope note. Blocks may be compact if genuinely simple for this procedure.

- [ ] **Pathology and Natural History** — disease mechanism, biomechanics or pathophysiology, untreated trajectory, when natural history forces surgery
- [ ] **Workup and Surgical Decision-Making** — imaging sequences/planes/findings with thresholds, adjunct studies (EMG/NCV, CTA/DSA, CT myelogram, dynamic films, perfusion, fMRI/DTI, neuropsych), timing logic
- [ ] **Indications, Contraindications, and Approach Selection** — branch logic, alternatives, contraindications by host/anatomy/pathology
- [ ] **Preoperative Planning** — implant/graft selection, side selection, image review checklist, team and ancillary readiness, consent specifics
- [ ] **Room, Positioning, and Equipment Setup** — table, head fixation, imaging, microscope/endoscope, retractor systems, navigation, hemostatic kit, instrument cart
- [ ] **Anesthetic and Physiologic Plan** — MAP/CPP targets, ventilation strategy, paralytic posture, burst suppression or hypothermia when relevant, brain relaxation, cuff pressure, IV/arterial access, vasoactive readiness
- [ ] **Neuromonitoring Strategy** — modalities (SSEP, MEP, EMG, BAER, EEG, cranial nerve, EcoG), thresholds for signal change, surgical response algorithms; or explicit justification when omitted
- [ ] **Hemostasis Strategy** — phase-by-phase bleeding sources, proximal/distal control points, bipolar/hemostatic agent choices, transfusion thresholds, crisis logic
- [ ] **Step-by-Step Operative Walkthrough with Step Rationale** — every step pairs action with mechanical/anatomic *why*, downstream consequence, novice error, expert behavior, recovery
- [ ] **Critical Moments** — highest-risk maneuvers isolated with consequence
- [ ] **Surgical Anatomy with Neurophysiologic Consequence** — every named structure linked to function/supply/plane/injury syndrome/avoidance/rescue
- [ ] **Pitfalls and Fail-Safe Plans** — mechanism-linked, executable bail-outs
- [ ] **Endpoint / Completion Criteria** — what must be true before closure; intraoperative confirmation tools (ICG, doppler, intraop angio, intraop MRI/CT, neuromonitoring stability)
- [ ] **Variants and Intraoperative Decision Branches** — including conversion/staging/abort criteria
- [ ] **Closure and Immediate Postoperative Management** — extubation criteria, drain/wound care, op-note essentials specific to this procedure
- [ ] **Complications and Signatures** — postop imaging interpretation (expected vs alarm), causal chain back to operative step
- [ ] **Outcomes and Evidence** — modern outcomes, comparative evidence, effect sizes, practice-changing trials/guidelines
- [ ] **Patient-Specific Modifiers** — host factors, anatomic variants, prior surgery, pediatric/elderly/pregnancy when relevant
- [ ] **OR Team Choreography** — closed-loop communication at time-out, vascular control, neuromonitoring change, transfusion, conversion, abort (compact when not critical)
- [ ] **Pre-Scrub Mental Rehearsal** — highest-yield mistakes, each with a verbal cue and immediate avoidance/recovery

## Pre-OR, Intra-OR, Post-OR Phase Skeleton

Treat pre-OR and post-OR as phases with the same conduct discipline as intra-OR.

### Pre-OR phases
- Phase:
  - Objective:
  - Decision point:
  - Information needed (imaging, labs, exam, consent specifics):
  - Failure mode if rushed:
  - What changes the surgical plan if discovered now:

### Intra-OR phases
- Phase:
  - Objective:
  - Landmark proving correct location:
  - Action sequence:
  - Main danger / structure at risk:
  - Expected decision point:
  - Likely novice failure mode:
  - Step rationale (why this technique, downstream consequence):

### Post-OR phases
- Phase (extubation, PACU, 24h, 72h, 30d, follow-up cadence):
  - Objective:
  - Expected findings vs alarm findings:
  - Causal link back to operative step when complication appears:
  - Follow-up imaging/timing:

## Anatomy-Risk Targets
- Structure/space:
  - Where encountered:
  - Function or supply or drainage:
  - Why vulnerable:
  - Deficit or complication if injured:
  - Avoidance maneuver:
  - Rescue option:
  - What source should support it:

## Failure Modes To Explain
- Failure mode:
  - Operative cause to investigate:
  - Recognition clue:
  - Immediate rescue:
  - Postoperative signature:

## Attending Defense Questions
- Question:
  - What a complete guide must answer:

## Retrieval Plan (per-domain matrix)

For each Coverage Matrix block, list at least one specific query unless the
block is genuinely covered by internal expert knowledge alone. Assign the
smallest sufficient source tier from
`.agents/shared/commands/rag-routing.md`.

- Query:
  - Coverage block addressed:
  - Purpose:
  - Retrieval tier: textbook_mini | textbook_full | current_primary | internal
  - Source type expected: textbook | anatomy atlas | PubMed/guideline | internal expert knowledge

## Verdict JSON

Write decomposition status to:

```text
data/Sessions/<Title>/verdicts/decomposition.json
```

Format:

```json
{
  "checkpoint": "decomposition",
  "procedure_title": "<Title>",
  "complexity": "simple" | "intermediate" | "complex",
  "coverage_matrix_blocks": <integer, count of blocks marked planned>,
  "coverage_matrix_complete": true | false,
  "phase_skeleton_includes_pre_op": true | false,
  "phase_skeleton_includes_post_op": true | false,
  "attending_defense_question_count": <integer>,
  "retrieval_query_count": <integer>,
  "timestamp": "<ISO-8601>"
}
```
```

## Optional Calibration Examples

When the procedure family matches, consult
`data/reference/operative-decomposition-examples.md`. It is reference data, not a
second policy source; the current procedure's Coverage Matrix still controls.

## Good Decomposition Behavior

A good decomposition reads like a curriculum, not a search log. Every Coverage Matrix block is named, with at least a one-line scope plan even when the block will be compact. The retrieval plan is a per-domain matrix, not a generic query list. The phase skeleton spans pre-OR through post-OR.
