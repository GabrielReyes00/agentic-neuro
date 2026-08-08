# Intraoperative Guide Research

At the research checkpoint, convert the procedure-specific Coverage Matrix into
compact source cards and a coverage ledger. Do not write guide prose here. Follow
`.agents/shared/commands/rag-routing.md` for every textbook query.

## Retrieval Plan

Map every unresolved Coverage Matrix block to a focused query, or to a shared
query whose answer directly supports each named block. Internal expert knowledge
may cover a block only with a one-line, conduct-specific justification. Broad
mega-queries may not conceal unresolved decision axes; query counts themselves
are not a quality target.

Split named tables/classifications from synthesis questions and preserve Coverage
Matrix order. Run compact lookups together:

```bash
python3 src/lance_retriever.py mini-batch \
  --query-file "$RUN_DIR/textbook_mini_queries.json" \
  --strategy auto --card-json \
  --output "$RUN_DIR/source_cards_textbook_mini.jsonl"
```

Move Mini-RAG escalations into the full list. For multiple independent synthesis
questions, use one in-process batch:

```bash
python3 src/lance_retriever.py batch \
  --query-file "$RUN_DIR/textbook_full_queries.json" \
  --card-json \
  --output "$RUN_DIR/source_cards_textbook_full.jsonl" \
  --max-passages 6 --max-takeaways 4
```

Do not launch concurrent `compare` processes. Scalar `compare --stdout
--no-frontier` is reserved for one narrow gap or passage-level audit.

Retrieve verified current primary literature when outcomes, devices, guidance,
timing, implants, monitoring, comparative strategy, or complication estimates
could change conduct. Complexity alone does not require token current evidence;
the actual decision burden does.

## Source Cards

Normalize textbook and current-literature cards into:

`$RUN_DIR/source_cards.jsonl`

Each compact card needs a stable ID, citation/locator, conduct-changing
takeaways, relevant numbers or effects, and a raw-source pointer:

```json
{
  "card_id": "T03-C02",
  "citation": "Youmans ... p. 851",
  "page_start": 851,
  "takeaways": ["..."],
  "numbers_thresholds_effects": ["..."],
  "raw_ref": {"source_key": "...", "chunk_index": 12}
}
```

An optional one-sentence `agent_synthesis` may connect an extract to operative
conduct. Do not turn cards into prose briefs or repeat coverage metadata on every
row. Raw retrieval files are audit-only and enter later context only for a named
citation dispute.

## Coverage Ledger

Maintain `$RUN_DIR/coverage_ledger.json` as the workflow data bus:

```json
{
  "procedure_title": "<Title>",
  "complexity": "simple|intermediate|complex",
  "coverage_blocks": {
    "<decomposition block id>": {
      "status": "covered|internal_only|weak|unresolved",
      "source_card_ids": ["T03-C02"],
      "map_block_id": "<knowledge-map block>",
      "guide_section": "<planned section>",
      "review_status": "pending|approved|gap",
      "notes": "<short conduct-relevant note>"
    }
  },
  "raw_rag_policy": "audit_only"
}
```

The Coverage Matrix is the master list. At this checkpoint every applicable
block must be source-covered, explicitly internal-only, or carried as a named
gap for repair. Simple cases still need sequence, anatomy-risk, endpoint, and
complication/bailout coverage; other blocks are procedure-dependent. Update this
same ledger during map review, expert review, and repair rather than creating
parallel coverage lists.

## Optional Human View

`research_brief.md` is optional and noncanonical. If a runtime needs it, keep it
to source mix, important limitations, and unresolved questions; do not restate
the cards. Later phases consume `source_cards.jsonl`, `coverage_ledger.json`, and
`verdicts/research.json`.

## Research Verdict

Write `$RUN_DIR/verdicts/research.json`:

```json
{
  "checkpoint": "research",
  "procedure_title": "<Title>",
  "complexity": "simple|intermediate|complex",
  "queries_by_coverage_block": {
    "<block id>": ["<query id>"]
  },
  "internal_only_justifications": {
    "<block id>": "<why internal knowledge is sufficient>"
  },
  "coverage_gate_met": true,
  "current_evidence_required": true,
  "current_evidence_source_present": true,
  "retrieval_limitations": "<short note>",
  "source_cards_path": "$RUN_DIR/source_cards.jsonl",
  "coverage_ledger_path": "$RUN_DIR/coverage_ledger.json",
  "research_brief_path": null,
  "raw_retrieval_files_not_used_as_downstream_context": true,
  "timestamp": "<ISO-8601>"
}
```

Set `current_evidence_required` from the actual decision burden. When true,
`current_evidence_source_present` is a hard gate. `coverage_gate_met` is true
only when no required block remains `weak` or `unresolved`.

If research is delegated, return only these structured artifact paths, the exact
queries run, limitations, and verdict—never full retrieval dumps.
