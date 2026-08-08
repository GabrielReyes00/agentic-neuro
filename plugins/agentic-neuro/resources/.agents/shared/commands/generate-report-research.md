# Generate Report Research

Use this module after `report_research_plan.json` is complete.

Follow `.agents/shared/commands/rag-routing.md` for every textbook query.

## Purpose

Produce structured source cards and a coverage ledger for report synthesis. Do not pass raw RAG dumps forward as the normal handoff, but do not treat source cards as a substitute for source inspection when precision matters.

Canonical outputs:

```text
$RUN_DIR/source_cards.jsonl
$RUN_DIR/coverage_ledger.json
```

A markdown research brief is optional for debugging, but `source_cards.jsonl` and `coverage_ledger.json` are canonical.

## Source-Card Compression and Raw-Source Audit

`--card-json` creates extractive, lossy source cards from the selected RAG hits. Cards are the default compression layer so the agent does not ingest every raw passage, but the agent remains responsible for source validity and synthesis quality.

### Clinical Density Preservation

Compression removes redundancy and irrelevant passage bulk; it must not strip management-changing clinical detail. Source cards should preserve the facts needed to write a dense reference report, especially when the topic is clinical, ICU-facing, operative, physiologic, or evidence-heavy.

When a selected passage contains any of the following, preserve it in the card with enough context to remain clinically usable:

- Specific percentages, risks, rates, effect sizes, odds ratios, denominators, time windows, dose ranges, thresholds, or outcome definitions.
- Anatomy levels and relationships that change localization, approach selection, complication risk, ICU monitoring, or emergency triage.
- Pathophysiologic mechanisms with their consequence chain intact, such as lesion level to sympathetic loss to bradycardia, or tract injury to exam finding to management consequence.
- Bedside monitoring parameters, escalation triggers, failure modes, contraindications, and protocol-dependent caveats.
- Named trials, guidelines, grading systems, classifications, or controversies with the source's population and evidence quality.

Do not reduce a rich passage to a generic takeaway when the source provides granular clinical content. A weak card says "bradycardia is common after cervical SCI." A useful card says "AIS A/B cervical SCI can produce severe bradycardia from interrupted T1-T4 sympathetic tone; the source reports HR <45 in 71% and atropine/temporary pacing in 29% over the first 14 days, with ICU monitoring implications." Exact quoted prose is unnecessary, but exact numbers, thresholds, and source boundaries must survive.

Inspect the raw RAG passage or primary source before relying on a card when any of these apply:

- The claim is high-stakes for management, operative conduct, ICU orders, prognosis, or safety.
- The claim is numerical: dose, threshold, timing window, incidence, effect size, risk, rate, NNT, OR/HR/RR, or outcome percentage.
- The source cards conflict or describe different patient populations, injury patterns, grading systems, or interventions.
- The coverage ledger has a `gap` or `internal_only` block that depends on the claim.
- The card is ambiguous, generic, truncated, or lacks enough context to support exact wording.
- The report will cite a specific trial, guideline, or recommendation.
- The source-card limitation suggests selection bias, low evidence quality, or indirect applicability.

Use the card's `raw_ref` (`child_id`, `source_key`, `chunk_index`) or rerun a narrow `compare --stdout` query to inspect the relevant passage. For PubMed/guideline/device cards, open or retrieve the primary source details before writing exact claims. After inspection, update the source card or `report_knowledge_map.json` with the resolved interpretation and limitations.

Never cite a card merely because it contains a convenient sentence. The cited source must support the exact claim, entity, population, intervention, and number used in the report.

## Textbook RAG Cards

Split planned textbook queries by the research plan's `textbook_mini` versus
`textbook_full` targets. Write each non-empty ordered list to:

```text
$RUN_DIR/textbook_mini_queries.json
$RUN_DIR/textbook_full_queries.json
```

Run every compact table/scale/classification lookup in one fast source-card
batch:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py mini-batch \
  --query-file "$RUN_DIR/textbook_mini_queries.json" \
  --strategy auto \
  --card-json \
  --output "$RUN_DIR/source_cards_textbook_mini.jsonl"
```

Honor any Mini-RAG escalation by moving that query to the full list. For two or
more full queries, run one in-process batch:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py batch \
  --query-file "$RUN_DIR/textbook_full_queries.json" \
  --card-json \
  --output "$RUN_DIR/source_cards_textbook_full.jsonl"
```

For one full query, a targeted gap, or raw-passage audit, use scalar `compare`
with `--card-json --card-output ... --no-frontier`, or with
`--stdout --no-frontier`. Full batch is local-textbook only; retrieve current
evidence through the literature plan.

Join stable Mini-RAG `Mxx` and full-RAG `Txx` topic IDs back to plan domains,
then merge both textbook files and non-RAG cards into `source_cards.jsonl`.
Preserve card IDs and raw references without repeating query metadata on every
card.

## Non-RAG Source Cards

Reports often depend on PubMed, guidelines, trials, and device specifications. Represent non-RAG sources in the same source-card layer:

```json
{
  "card_id": "PMID26738503-CARD-01",
  "source_type": "pubmed",
  "coverage_blocks": ["outcomes_evidence", "key_numbers"],
  "citation": "Author et al., 2016",
  "pmid": "26738503",
  "doi": null,
  "takeaways": [
    "Specific effect size or management-changing finding."
  ],
  "limitations": "Cohort study; selection bias.",
  "provenance_tier": "source_grounded"
}
```

Allowed `source_type` values: `textbook_rag_mini`, `textbook_rag_full`,
`pubmed`, `guideline`, `trial_registry`, `device_spec`, `web_primary`,
`model_knowledge_verify`.

Do not fabricate PMIDs, DOIs, source titles, or page numbers. If a useful internal-knowledge point is not source-located, create a `model_knowledge_verify` card with high-stakes specifics marked for verification.

## Coverage Ledger

Write:

```json
{
  "report_title": "<Title>",
  "topic": "<canonical topic>",
  "blocks": {
    "epidemiology_natural_history": {
      "required": true,
      "status": "covered",
      "source_card_ids": ["Q1-CARD-01"],
      "notes": "Incidence and natural history rates found.",
      "gaps": []
    },
    "operative_or_procedural_considerations": {
      "required": false,
      "status": "not_applicable",
      "source_card_ids": [],
      "notes": "Pure pharmacology topic.",
      "gaps": []
    }
  }
}
```

Allowed statuses:

- `covered`: source-grounded coverage adequate for synthesis.
- `internal_only`: content required and available only from model knowledge; must be labelled in the report.
- `not_applicable`: domain genuinely does not apply.
- `gap`: required content is still missing or too weak.

Before synthesis, every required block must be `covered` or `internal_only`. Any `gap` status triggers more retrieval or explicit scope repair. The final validator will fail if the ledger still contains a gap-like status in a required block.

## Source-Card Quality

Cards are extraction artifacts, not prose. Keep takeaways concise and source-specific, but never clinically anemic. Each card should answer: what did this source contribute, which report domain does it support, what granular clinical detail should survive into the report, and what limitation must survive into synthesis?

Source cards can lose context through sentence extraction. Preserve uncertainty, population boundaries, and whether the finding came from textbook teaching, primary data, guideline consensus, or model knowledge. When compression would erase a necessary caveat, add the caveat to the card or force raw-source audit during synthesis.
