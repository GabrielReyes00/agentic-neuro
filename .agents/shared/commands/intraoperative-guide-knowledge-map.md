# Intraoperative Guide Operative Knowledge Map Module

Use this module after the structured source cards and coverage ledger are complete and before drafting the guide.

## Purpose

Build the intermediate reasoning artifact that deep-research workflows require. The final guide must be written from this map, not directly from raw RAG snippets.

The operative knowledge map is a scratch artifact. It should not be copied into the final Obsidian guide.

The map's completeness is independently audited by the dedicated **map-completeness reviewer** described in `.agents/shared/commands/intraoperative-guide-map-review.md` before synthesis begins. Iterating on the map is cheap; iterating on prose is expensive. Spend effort here.

## Role

You are building the operative mental model of the procedure. Organize retrieved sources, internal expert knowledge, and unresolved questions into a map that can survive attending-level questioning and that addresses every Coverage Matrix block from decomposition.

Use `source_cards.jsonl` and `coverage_ledger.json` as the retrieval layer. A short research brief may be consulted if present, but it is not canonical. Do not read or paste raw RAG files unless you are resolving a specific source dispute or a named gap from a reviewer.

## Map Standards

Every important entry should connect knowledge to operative consequence. Avoid trivia. If a fact does not change conduct, risk prediction, rescue, postoperative recognition, or oral defense, it does not belong in the map.

Use source support when available. Mark source gaps honestly. The map should resolve toward the 85% resident-mastery depth target.

## Structured Map Budget

The map is a planning artifact, not the guide. Prefer structured block data over prose. Write the canonical map to:

```text
data/Sessions/<Title>/knowledge_map.json
```

Optional markdown may be generated for human debugging, but reviewers should receive `knowledge_map.json`, `coverage_ledger.json`, and only the relevant source-card rows by default.

Keep the structured map dense:

- Intermediate procedures: target 1,200-2,200 words equivalent.
- Complex procedures: target 2,200-3,800 words equivalent.
- Simple procedures: target 700-1,200 words equivalent.

If a section is straightforward, use compact bullets with the conduct consequence rather than expanding prose. Spend words only where they alter conduct, risk recognition, rescue, or attending defense. Source support should usually be source-card IDs, not re-quoted source text.

## Canonical JSON Shape

Use stable block IDs so reviewers and repair cycles can point to exact gaps without re-reading prose:

```json
{
  "procedure_title": "<Title>",
  "complexity": "intermediate",
  "blocks": {
    "operative_mental_model": {
      "points": ["..."],
      "source_card_ids": ["Q1-CARD-03"]
    },
    "anatomy_risk": {
      "entries": [
        {
          "structure": "recurrent laryngeal nerve",
          "where": "...",
          "injury_signature": "...",
          "avoidance": "...",
          "rescue": "...",
          "source_card_ids": ["Q3-CARD-01"]
        }
      ]
    },
    "failure_modes": {
      "entries": [
        {
          "failure": "vertebral artery injury",
          "recognition": "...",
          "immediate_action": "...",
          "escalation": "...",
          "postoperative_signature": "...",
          "source_card_ids": ["Q4-CARD-02"]
        }
      ]
    }
  },
  "unresolved_or_weak": []
}
```

The exact nested fields may vary by procedure, but every Coverage Matrix block must have a stable block ID, status in `coverage_ledger.json`, and enough conduct-changing content for synthesis.

## Required Output

If a markdown debug view is needed, use this structure. Sections are organized as first-principle knowledge blocks shared across all neurosurgical procedures.

```markdown
## Operative Mental Model
- Core purpose:
- Essential sequence logic:
- What must be true before starting:
- What must be true before closing:

## Pathology and Natural History
- Disease mechanism:
- Biomechanics or pathophysiology relevant to operation:
- Untreated trajectory:
- When natural history forces surgery:
- Source support:

## Workup and Surgical Decision-Making
- Required imaging (sequence/plane/finding):
  - Decision threshold or measurement:
  - Source support:
- Adjunct studies (EMG/NCV, CTA/DSA, CT myelogram, dynamic films, perfusion, fMRI/DTI, neuropsych):
  - When ordered:
  - What changes the plan:
- Timing logic:

## Indication and Approach-Selection Map
- Scenario/anatomy:
  - Best approach or variant:
  - Why:
  - When not to use it:
  - Comparator data when relevant:
  - Source support:

## Preoperative Planning Map
- Implant/graft selection:
- Side selection rationale:
- Image review checklist:
- Team/ancillary readiness:
- Consent-specific risks beyond generic:

## Room, Positioning, and Equipment Map
- Table/position/head fixation:
- Imaging modalities in room:
- Microscope/endoscope/loupes:
- Retractor system(s):
- Navigation/IOM/ultrasound/fluoroscopy:
- Hemostatic kit and adjuncts:
- Sterile prep boundaries:

## Anesthetic and Physiologic Plan Map
- MAP / CPP / ICP targets:
- Ventilation strategy:
- Paralytic posture (compatibility with neuromonitoring):
- Burst suppression / hypothermia when relevant:
- Brain relaxation strategies:
- Cuff pressure / airway logic:
- IV/arterial access, vasoactive readiness:
- Specific anesthesia-surgeon communication points:
- Source support:

## Neuromonitoring Strategy Map
- Modalities used (SSEP, MEP, EMG, BAER, EEG, cranial nerve, EcoG):
  - Why used here:
  - Signal-change threshold:
  - Surgical response algorithm if lost:
- Justification if monitoring is intentionally omitted:
- Source support:

## Hemostasis Strategy Map
- Phase:
  - Predictable bleeding source:
  - Proximal/distal control point:
  - Tool and technique (bipolar setting, hemostatic agent, packing, clip-trap-repair):
  - Crisis pathway / transfusion threshold:
  - Source support:

## Phase-by-Phase Conduct Map (pre-OR, intra-OR, post-OR)
- Phase:
  - Objective:
  - Landmark proving correct location:
  - Action sequence:
  - Structure most at risk:
  - Decision point:
  - Novice error:
  - Expert behavior:
  - Recovery move:
  - **Step rationale chain** (mechanical/anatomic goal → why this technique vs alternative → consequence if skipped → downstream step it enables):
  - Source support:

(Include pre-OR phases — workup, plan, consent, setup — and post-OR phases — extubation, PACU, 24h, 72h, 30d, follow-up — using the same field set.)

## Anatomy-Risk Map with Neurophysiologic Consequence
- Structure/space:
  - Where encountered:
  - Function / blood supply / drainage / plane / bony relationship:
  - Neurophysiologic role (what is lost if injured):
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
  - Immediate action (executable):
  - Escalation/abort/convert threshold:
  - Postoperative signature:
  - Source support:

## Endpoint / Completion Criteria Map
- What must be true before closure (decompression endpoint, resection threshold, clipping/coiling confirmation, hardware position, hemostasis, monitoring stability):
- Intraoperative confirmation tools used (ICG, doppler, intraop angio, intraop MRI/CT, neuromonitoring stability, fluoroscopy):
- What confirms "good enough" vs "redo before closing":
- Source support:

## Closure and Postoperative Causality Map
- Postoperative finding:
  - Likely intraoperative cause:
  - Expected vs alarm postop imaging finding:
  - First evaluation:
  - First action:
  - Op-note essential specific to this procedure:
  - Follow-up imaging cadence:
  - Source support:

## Outcomes and Evidence Map
- Outcome / trial / guideline:
  - Effect size or comparator:
  - Practice impact:
  - Source support:

## Patient-Specific Modifiers Map
- Modifier (host factor, anatomic variant, prior surgery, pediatric/elderly/pregnancy):
  - How it changes conduct:
  - Source support:

## OR Team Choreography Map (when conduct-relevant)
- Closed-loop call point:
  - Trigger:
  - Verbal cue:
  - Expected response from team:

## Attending Defense Map
- Question (from decomposition):
  - Expected answer:
  - Where guide must answer it:

## Unresolved or Weak Areas
- Gap:
  - Rubric block affected:
  - Why it matters:
  - Repair path: existing context / internal knowledge / RAG / PubMed
  - Suggested query:
```

## Self-Triage Before Map-Review Subagent

Before handing the map to the map-completeness reviewer, run a short self-triage:

- Does the map cover every Coverage Matrix block from decomposition?
- Does every named danger structure have an injury signature and avoidance/rescue logic?
- Does every operative phase carry a step-rationale chain, not just a purpose?
- Are pre-OR and post-OR phases populated with the same conduct discipline as intra-OR?
- Are anesthesia, neuromonitoring, hemostasis, and endpoint criteria explicit?
- Are postoperative checks tied to intraoperative mechanisms?
- Are source gaps honestly flagged in `Unresolved or Weak Areas`?

Self-triage is not a substitute for the map-completeness review subagent. It exists only to reduce trivially-blocking reviewer feedback.

## Handoff to Map-Completeness Review

Once self-triage is clean, invoke `.agents/shared/commands/intraoperative-guide-map-review.md`. Do **not** begin synthesis until that module returns `MAP_APPROVED` and writes the verdict JSON. If `MAP_GAPS` is returned, repair using the assigned path, then resubmit. The map may be revised across multiple cycles before synthesis begins; this is the cheap iteration phase.

Handoff should include only the decomposition, the compact research brief/source cards, the map, and a short verdict-chain summary. Do not include raw RAG dumps by default.
