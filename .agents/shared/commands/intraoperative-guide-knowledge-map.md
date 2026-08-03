# Intraoperative Guide Knowledge Map

Build the structured operative model after research and before prose. The final
guide is written from this map, not raw retrieval. The map is internal scratch
data and must address every procedure-specific Coverage Matrix block.

## Inputs And Output

Read:

- `decomposition.json` and its Coverage Matrix;
- `source_cards.jsonl`;
- `coverage_ledger.json`;
- an optional short research brief only when useful.

Write `data/Sessions/<Title>/knowledge_map.json`. Reviewers receive this map, the
ledger, and only source cards relevant to the blocks they inspect. Raw retrieval
enters only for a named source dispute.

## Map Standard

Include knowledge only when it changes selection, conduct, risk prediction,
rescue, postoperative recognition, or attending defense. Every applicable block
needs a stable ID, support status, and enough reasoning for prose synthesis.
Prefer compact structured fields over paragraphs; there is no word quota.

Canonical shape:

```json
{
  "procedure_title": "<Title>",
  "complexity": "simple|intermediate|complex",
  "core_operative_model": ["<sequence or causal frame>"],
  "blocks": {
    "<Coverage Matrix block id>": {
      "status": "covered|internal_only|weak|unresolved",
      "purpose": "<why this block changes conduct>",
      "entries": [
        {
          "decision_or_step": "<trigger, phase, structure, or problem>",
          "action": "<what to do>",
          "rationale": "<mechanical/anatomic goal and why this method>",
          "risk_or_failure": "<what fails if omitted or done wrongly>",
          "recognition": "<intraoperative or postoperative signature>",
          "avoidance_or_rescue": "<executable response>",
          "endpoint_or_next_step": "<what this enables or confirms>",
          "source_card_ids": ["T03-C02"]
        }
      ],
      "internal_only_justification": null
    }
  },
  "cross_block_edges": [
    {
      "from": "<block/entry>",
      "to": "<block/entry>",
      "relationship": "enables|injures|signals|changes_plan|requires_rescue"
    }
  ],
  "attending_defense": [
    {"question_id": "<id>", "expected_answer": "<answer>", "map_blocks": ["<id>"]}
  ],
  "unresolved_or_weak": [
    {"block_id": "<id>", "why_it_matters": "<consequence>", "repair_path": "<path>"}
  ]
}
```

Adapt nested fields to the procedure, but preserve the essential relationships:

- decision trigger → chosen branch → alternative rejected;
- phase objective → landmark → action → step rationale → downstream enablement;
- anatomy/function or blood supply → vulnerability → injury signature →
  avoidance/rescue;
- failure mechanism → early recognition → immediate action → escalation/abort;
- endpoint → confirmation tool → acceptable versus redo-before-closure boundary;
- postoperative finding → likely operative cause → first evaluation/action;
- patient modifier, evidence boundary, or local variation → changed conduct.

Name equipment only when it changes preparation or use. Include anesthesia,
monitoring, hemostasis, team communication, outcomes, and follow-up only to the
extent their Coverage Matrix blocks are applicable; an intentional omission must
remain explicit in the ledger.

## Self-Triage And Review

Before independent review, confirm:

- every Coverage Matrix block maps to a block or justified non-applicability;
- every major phase carries rationale and an endpoint, not sequence alone;
- danger anatomy has injury signatures and avoidance/rescue;
- predictable crises have executable actions and escalation thresholds;
- postoperative alarms trace back to plausible operative mechanisms;
- source and internal-only boundaries match the coverage ledger;
- unresolved items are named rather than hidden.

Self-triage does not replace the independent map review defined in
`intraoperative-guide-map-review.md`. Do not synthesize prose until that review
writes `MAP_APPROVED`; repair and resubmit any `MAP_GAPS` verdict.
