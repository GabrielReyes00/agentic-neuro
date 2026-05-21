# Generate Report Synthesis Map

Use this module after `source_cards.jsonl` and `coverage_ledger.json` are complete and no required ledger block has `status: gap`.

## Purpose

Build the intermediate synthesis artifact that prevents reports from becoming stitched RAG summaries. The final report must be written from this map, not directly from raw retrieval dumps.

Write the canonical map to:

```text
data/Sessions/<Title>/report_knowledge_map.json
```

## Map Shape

```json
{
  "report_title": "<Title>",
  "topic": "<canonical topic>",
  "sections": [
    {
      "section_id": "clinical_utility",
      "target_heading": "Clinical Utility & Quick Reference",
      "claims": [
        {
          "claim": "Specific management-changing claim.",
          "why_it_matters": "Clinical, operative, diagnostic, or oral-board consequence.",
          "source_card_ids": ["Q1-CARD-01", "PMID26738503-CARD-01"],
          "provenance_tier": "source_grounded",
          "citation_plan": ["Author et al., 2016", "Youmans 8th Ed, p. 777"],
          "uncertainty_or_limitations": null
        }
      ]
    }
  ],
  "key_numbers": [
    {
      "parameter": "...",
      "value": "...",
      "context": "...",
      "source_card_ids": ["..."],
      "source_cell": "[Author et al., 2016](https://pubmed.ncbi.nlm.nih.gov/26738503/)"
    }
  ],
  "differentiators": [],
  "pitfalls": [],
  "controversies": [],
  "gaps_or_internal_only": []
}
```

The exact section list is topic-specific. The map must cover every required ledger block and must explicitly carry:

- Key numbers with planned source cells.
- Differentiators and contrasting axes.
- Failure modes/pitfalls.
- Evidence quality and effect-size notes for trials.
- Mechanism to consequence chains.
- Controversies and uncertainty.
- Verified wikilink targets.
- `model knowledge -- verify` items that must be labelled in prose.

Allowed `provenance_tier` values in the map are `source_grounded`, `model_knowledge_verified`, and `model_knowledge_verify`. `model_knowledge_verified` means the claim began as agent clinical knowledge but now has a confirming source; cite that confirming source in final prose. `model_knowledge_verify` means no confirming source was found; label it in final prose and never attach a textbook/PMID/DOI citation to it.

## Synthesis Rules

- Integrate sources before writing prose. One map claim may cite several source cards.
- Preserve source limitations and controversies; do not average conflicting evidence.
- If a claim lacks a source card but matters, mark it `model_knowledge_verify`.
- If map construction reveals a missing required domain, update `coverage_ledger.json` to `gap` and return to research.
- For high-stakes, numerical, conflicting, gap-filling, or citation-sensitive claims, record that the raw passage or primary source was inspected before finalizing the claim. Do not rely on compressed card text alone for those claims.
- Keep the map compact as JSON. It is a planning artifact, not the report.

## Clinical Density Integration

Compact JSON does not mean vague claims. The map must carry enough clinical content to generate an expert reference report without dropping the details that made the source useful.

For each clinically relevant section, preserve the natural density demanded by the topic:

- Keep management-changing numbers, thresholds, time windows, effect sizes, anatomy levels, named trials/guidelines, and evidence-quality labels in the mapped claims or `key_numbers`.
- Keep mechanism-to-consequence chains intact when the topic depends on physiology, molecular biology, anatomy-risk relationships, ICU deterioration, or operative failure modes.
- Keep differentiators in a clinically discriminating form: feature, closest mimic, consequence of confusing them, and what changes in management.
- Keep failure modes as diagnostic traps or management errors with their specific consequence, not as generic cautions.
- Keep protocol-dependent or model-knowledge material useful but labelled, especially for ICU thresholds, drug choices, device settings, and institution-specific practices.

Reject and revise a synthesis map if it could only support a short operational summary when the topic warrants a dense clinical reference. Return to research when the map lacks the granular physiology, metrics, complications, operative logic, or evidence interpretation naturally expected for the topic.
