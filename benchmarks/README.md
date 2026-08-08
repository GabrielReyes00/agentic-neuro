# RAG Pipeline Benchmark

For the instruction and workflow harness itself, run:

```bash
source .venv/bin/activate
python3 benchmarks/benchmark_agent_harness.py \
  --repeat 100 \
  --check \
  --output benchmarks/agent_harness_ablation_current.json
```

That ablation compares the former flat-registry startup surface with the typed
per-workflow projection, injects six graph defects to measure validator value,
times full-registry compilation, and verifies behavioral and architecture
coverage. CI enforces correctness and context-budget gates; latency is recorded
but not used as a flaky wall-clock gate.

For study-review specifically, measure both the instruction entry and the
database-derived TutorState on an ephemeral SQLite backup:

```bash
python3 benchmarks/benchmark_study_review.py \
  --repeat 7 --check \
  --output benchmarks/study_review_current.json
```

The source learner database is opened read-only and copied into a temporary
directory before any migration or recall. The benchmark compares routine
`tutor_state_v1` with the rich audit packet, measures exact `cl100k` tokens and
median local latency, and enforces the eight-node/one-hop caps.

When AnkiConnect is available, compare the current startup overlay with the
repository baseline using the same live cards and vector cache:

```bash
python3 benchmarks/benchmark_anki_startup.py \
  --baseline-ref bcb67ec \
  --repeat 5 \
  --output benchmarks/anki_startup_current.json
```

The script is intentionally not a CI gate because it depends on the local Anki
application. It reports `skipped` rather than manufacturing a latency result
when that dependency is unavailable.

For the small scale/score/classification tier, see
[`MINI_RAG_FINDINGS.md`](MINI_RAG_FINDINGS.md) and run
`benchmark_mini_rag.py`. The mini benchmark includes named and paraphrased
lookups, top-passage previews, evidence-density checks, compact serialization,
and four strategy comparisons.

This benchmark measures the local textbook retrieval stack without frontier
network search. It covers eight neurosurgical domains and 40 predefined
clinical anchor groups. The same 58,899-row LanceDB corpus, BGE-M3 embedder, and
MiniLM-L6 cross-encoder are used for both modes.

Run the scalar compatibility baseline:

```bash
source .venv/bin/activate
python3 benchmarks/benchmark_rag_pipeline.py \
  --mode serial \
  --repeat 3 \
  --output /tmp/rag_serial.json
```

Run batched multi-topic retrieval:

```bash
source .venv/bin/activate
python3 benchmarks/benchmark_rag_pipeline.py \
  --mode batch \
  --repeat 3 \
  --output /tmp/rag_batch.json
```

`serial` executes the pre-batch production shape: retrieve, distill, and
quality-augment each query separately. `batch` uses the shared multi-topic
pipeline. Model warmup is measured separately and excluded from retrieval wall
time.

## Accepted Result

Measured on 2026-07-29 against the untouched `4d481e0` implementation, using
three warm repetitions per mode:

| Metric | Scalar baseline | Batched pipeline | Change |
|---|---:|---:|---:|
| Eight-topic median wall time | 79.05 s | 31.32 s | **-60.4%** |
| Wall-time range | 77.93-81.24 s | 29.94-34.10 s | — |
| Median amortized time/topic | 9.88 s | 3.92 s | **-60.4%** |
| Clinical anchor recall | 95.0% | 100.0% | **+5.0 pp** |
| Entity hit rate | 100.0% | 100.0% | unchanged |
| Composite quality score | 0.9645 | 0.9914 | **+2.8%** |
| High-signal sentences | 818 | 1,014 | **+24.0%** |
| Delivered source-card bytes | 111,669 | 108,681 | **-2.7%** |
| Signal per delivered byte | baseline | 1.274x baseline | **+27.4%** |
| Mean pairwise redundancy | 0.0806 | 0.0861 | +0.55 pp |

The accepted configuration keeps the full 55-candidate reranking pool. A
32-candidate experiment was faster but regressed temporal-lobe epilepsy
coverage, so it was rejected. Dynamic INT8 reranking and smaller semantic
entity windows were also tested and rejected when they failed to improve the
quality/latency frontier.

## What the Batch Changes

- Encodes all topic queries in one BGE-M3 pass.
- Runs bounded concurrent dense and multi-field FTS searches.
- Reranks all topic candidate pools in one cross-encoder call.
- Batches semantic heading/entity disambiguation and bounds it to the four
  highest-ranked ambiguous hits per topic; strong text-entity matches use a
  conservative lexical fast path.
- Avoids a second axis cross-encoder pass once the evidence pool is already
  bounded, while emitting explicit axis-coverage gaps for targeted follow-up.
- Uses source-scoped passage identity so source-local child/parent IDs cannot
  collapse passages from different books.
- Emits one versioned batch manifest, compact topic manifests, and stable
  `Txx-Cxx` source-card IDs without repeating query metadata on every card.

## Production CLI

```bash
source .venv/bin/activate
python3 src/lance_retriever.py batch \
  --query "acute subdural hematoma operative indications" \
  --query "vestibular schwannoma approach selection" \
  --card-json \
  --max-passages 6 \
  --output /tmp/source_cards.jsonl
```

`--query-file` accepts a JSON list, `{"queries": [...]}`, JSONL rows with a
`query` field, or one query per line. Exact duplicate queries are evaluated
once and restored to their original positions.

For scale/table lookups routed to Mini-RAG, use the same source-card handoff:

```bash
source .venv/bin/activate
python3 src/lance_retriever.py mini-batch \
  --query "Hunt and Hess scale" \
  --query "SINS classification table" \
  --strategy auto \
  --card-json \
  --output /tmp/mini_source_cards.jsonl
```

Mini cards use stable `Mxx-Cxx` IDs and full batch cards use `Txx-Cxx`. Their
manifests carry `source_type: textbook_rag_mini` and
`source_type: textbook_rag_full`, respectively, without repeating the value on
every card.

## Interpretation Limits

Anchor recall is a deterministic regression signal, not a substitute for
expert review of every passage. The benchmark does not evaluate frontier
literature retrieval, guideline currency, or whether an extracted textbook
claim is current enough for clinical conduct. Those remain separate provenance
and verification gates in the report and operative-guide workflows.
