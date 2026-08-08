# RAG Routing

This is the canonical agent-agnostic contract for textbook retrieval. Load it
before choosing a `lance_retriever.py` path; workflow files should add only
their own coverage, artifact, or teaching constraints.

## Choose the Smallest Sufficient Tier

| Need | Route |
|---|---|
| Named scale, score, classification, staging system, defining table, or compact textbook fact | Mini-RAG |
| Several independent compact lookups | One `mini-batch` |
| One question requiring broad context, causal synthesis, or multiple evidence axes | One scalar `compare` |
| Two or more independent synthesis/research questions | One in-process `batch` |
| Current conduct-changing threshold, dose, reversal, timing, outcome, guideline, or controversy | Current primary sources; textbook retrieval is supplemental |

Load `.agents/shared/commands/mini-rag.md` for the Mini-RAG route. Honor its
`escalate: true` result; never stretch a compact packet into synthesis.
Artifact workflows use Mini-RAG's `--card-json` serializer so compact and full
retrieval share one source-card handoff.

## Full-RAG Invocation

One synthesis query:

```bash
python3 src/lance_retriever.py compare "<focused query>" --stdout --no-frontier
```

Several independent synthesis queries:

```bash
python3 src/lance_retriever.py batch \
  --query-file "<ordered queries.json>" \
  --card-json \
  --output "<source cards.jsonl>"
```

Use coherent, entity-explicit queries with one decision or coverage target per
query. Never combine several topics into a mega-query. Do not launch parallel
`compare` processes: for 2-32 independent textbook queries, `batch` shares
encoding, search, reranking, distillation, and compact serialization in one
process. Use scalar `compare` for a single query, a targeted gap repair, or a
raw-passage audit.

Full `batch` is local-textbook retrieval. Obtain current literature separately
and normalize it into the workflow's source-card layer when needed.

## Evidence and Serialization

- Judge entity and claim relevance before use; discard adjacent or generic
  hits.
- Preserve citations and `raw_ref` values. A source card supports only the
  entity, population, intervention, number, and limitation actually present.
- Preserve the source-card manifest `provenance`: corpus fingerprint, table
  version, ingestion version, retrieval-pipeline version, and model identities.
  `legacy-unrecorded` is an honest historical ingestion boundary, not permission
  to invent the missing version.
- Respect each card's `source_role`. `research_methodology` books are excluded
  from clinical queries and may support only explicit grant/research-method
  questions; anatomic, operative, historical, and educational sources remain
  bounded to the role actually represented by the passage.
- Prefer compact JSON/JSONL packets and stable topic/card IDs. Pass source cards
  forward, not raw RAG dumps; retain raw passages only for audit or a narrow
  dispute.
- Inspect the raw passage or primary source for management-changing numerics,
  ambiguity, truncation, conflict, or wording-sensitive claims.
- Deduplicate identical queries and preserve plan order so coverage mappings
  remain deterministic.
- Retrieval supplies evidence; the agent performs synthesis. Never let weak
  retrieval narrow the answer or invite fabricated support.

## Operational Checks

Run `python3 src/lance_retriever.py mini-preflight` before Mini-RAG benchmarks
or after corpus changes. Rebuild the Mini-RAG sidecars as directed by
`mini-rag.md`. Full-RAG model/corpus checks remain part of the retrieval CLI.

The accepted algorithms and reproducible measurements live in
`benchmarks/README.md` and `benchmarks/MINI_RAG_FINDINGS.md`.
