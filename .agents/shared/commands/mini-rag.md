# Mini-RAG

This is the compact tier selected by
`.agents/shared/commands/rag-routing.md`. Use the routing contract first when
the appropriate retrieval tier is not already obvious.

Use this contract for small, source-grounded neurosurgical lookups where the
full BGE-M3/cross-encoder pipeline would add latency without adding useful
synthesis.

## Scope

Mini-RAG is appropriate for:

- a named scale, score, classification, grade, staging system, table, or
  compact textbook reference;
- a short paraphrase whose component signature identifies one of those named
  systems;
- several independent factual lookups that can be retrieved together; and
- point-of-need verification after Gabriel has committed to an answer in a
  learning workflow.

Mini-RAG is not sufficient for:

- broad disease management, operative planning, causal synthesis, differential
  diagnosis, or evidence reviews;
- current guideline thresholds, medication doses, reversal, timing, outcomes,
  or disputed standards that require current primary verification; or
- a low-confidence packet, missing source table, or query routed to `full`.

Honor `escalate: true`. Use the full textbook pipeline or current primary
sources as the question requires; never force a compact packet to answer a
larger question.

## Commands

One lookup:

```bash
python3 src/lance_retriever.py mini "<query>" --strategy auto --json
```

Several independent lookups:

```bash
python3 src/lance_retriever.py mini-batch \
  --query "<query 1>" \
  --query "<query 2>" \
  --strategy auto --json
```

For artifact workflows, use `--card-json` and `--output <path>` instead of
`--json`. This emits the same compact source-card fields and stable `Mxx-Cxx`
IDs used by the shared evidence layer; do not manually re-serialize Mini-RAG
passages. Use `--max-takeaways` only when the defining table needs more than
the default eight extractive statements.

The `auto` router is the production default:

1. exact full-corpus SQLite FTS5 for named lookups and recognized component
   signatures;
2. small ONNX semantic retrieval plus rank fusion only when the short
   paraphrase is not confidently resolved lexically; and
3. explicit escalation for complex synthesis or weak evidence.

Do not choose `semantic` by default. It is an experimental/debug strategy and
is less reliable than exact-table FTS on the benchmark corpus.

## Evidence Use

- Prefer the first passage only when it directly answers the lookup; inspect
  the second passage when the first table is split or the packet indicates
  truncation.
- Preserve the supplied citation and `raw_ref`; do not detach a claim from its
  source.
- Treat textbook evidence as classic reference knowledge. Apply the root
  provenance doctrine before using a threshold or conduct-changing claim.
- Keep the answer proportionate: a small lookup should normally produce a
  compact answer, not a disease overview.

## Learning-Workflow Boundary

In `study-review`, never run Mini-RAG before Gabriel answers the active
question. That would violate cognitive friction by leaking the answer. After
commitment, Mini-RAG may verify a missed or partially recalled scale,
classification, threshold, or discriminator before the repair is taught.

## Lifecycle

Check readiness:

```bash
python3 src/lance_retriever.py mini-preflight
```

Rebuild the full-corpus lexical sidecar after the Lance corpus changes:

```bash
python3 src/lance_retriever.py mini-fts-build
```

Rebuild the optional pruned semantic sidecar after corpus/model changes:

```bash
python3 src/lance_retriever.py mini-build
```

The source fingerprints in `data/runtime/mini_rag_fts_manifest.json` and
`data/runtime/mini_rag_manifest.json` must match the active Lance table before
benchmarking or relying on the semantic tier.
