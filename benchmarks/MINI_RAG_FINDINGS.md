# Mini-RAG Strategy Findings

Measured 2026-07-30 against the 58,899-chunk `neurosurgery_v4` corpus. The
benchmark contains 16 small learning lookups: eight named systems and eight
paraphrases, with qualitative expectations and 76 deterministic answer
anchors. Each strategy receives at most two passages and 4,200 characters per
case.

## Accepted Architecture

`auto` uses a cost ladder:

1. full-corpus SQLite FTS5 for exact names and recognized component signatures;
2. the 384-dimensional BGE-small ONNX sidecar only for an unresolved short
   paraphrase;
3. weighted lexical/semantic fusion that preserves strong exact-table rank; and
4. explicit escalation for complex synthesis or low-confidence evidence.

The lexical sidecar contains every source chunk. The semantic sidecar is only a
1,499-chunk table/classification subset. Query packets preserve citations,
source-local raw references, truncation status, and the router decision.

Artifact workflows use `mini-batch --card-json` rather than re-serializing
passages in the agent. It emits stable `Mxx-Cxx` IDs and a manifest-level
`textbook_rag_mini` source type; full batch uses `Txx-Cxx` and
`textbook_rag_full`. Query and source-type metadata are not repeated on every
card.

## Strategy Comparison

Five warm repetitions, after each strategy's measured first batch:

| Strategy | Warm 16-topic median | Median/topic | Entity recall | Anchor recall | Top-passage anchor recall | Outcome |
|---|---:|---:|---:|---:|---:|---|
| SQLite lexical | 0.420 s | 26.3 ms | 100% | 95.63% | 91.25% | Fastest accurate primitive |
| Semantic only | 0.371 s | 23.2 ms | 75.0% | 65.22% | 52.14% | Rejected: nearby overviews displaced tables |
| Hybrid every query | 0.774 s | 48.4 ms | 100% | 95.63% | 90.31% | Rejected: no recall gain, slower |
| `auto` router | 0.491 s | 30.7 ms | 100% | 95.63% | 91.25% | Accepted: same quality plus safe fallback |

The final production `auto` verification in a fresh process measured a
2.33-second first 16-topic batch and a 0.478-second warm median over nine
repetitions (29.9 ms/topic). The cold batch includes loading the 64 MB ONNX
model because three unnamed cases required semantic fallback. A purely lexical
first batch measured 0.445 seconds.

The existing full production RAG benchmark remains the control for queries that
need synthesis: 31.32 seconds for eight batched topics (3.92 seconds/topic),
with 100% clinical anchor recall. The workloads differ, so this is a routing
comparison rather than a same-query quality claim; for eligible small lookups,
the accepted mini tier is about 130 times faster per topic. Full RAG remains the
correct tier for broad clinical synthesis.

## Iteration Against the Initial Mini Design

Before the SQLite sidecar, `auto` used LanceDB FTS for all 16 cases:

| Metric | Lance FTS mini | Accepted SQLite mini | Change |
|---|---:|---:|---:|
| Fresh first batch | 6.73 s | 2.33 s | **-65.4%** |
| Warm 16-topic median | 1.295 s | 0.478 s | **-63.1%** |
| Median/topic | 80.9 ms | 29.9 ms | **-63.1%** |
| Anchor recall | 94.37% | 95.63% | **+1.26 pp** |
| Top-passage anchor recall | 89.69% | 91.25% | **+1.56 pp** |
| Duplicate-unit ratio | 2.60% | 2.03% | **-0.57 pp** |

The sidecar takes 5.8 seconds to build and occupies 160 MB. The optional
semantic sidecar occupies 7.2 MB; its cached ONNX model occupies 64 MB. Its
one-time build took 171.7 seconds. This cost is justified only as a bounded
fallback, not as the primary exact-lookup engine.

## What the Passages Actually Look Like

These are descriptive summaries of the accepted top passages, not merely
anchor counts:

- **Hunt-Hess** — `Essential Neurosurgery`, p.139: one compact table gives all
  five grades, from asymptomatic/minimal headache through deep coma and
  decerebrate rigidity. Adjacent exact duplicate cells are removed during
  serialization.
- **SINS paraphrase** — `Youmans and Winn`, p.512: the unnamed component query
  expands to SINS and retrieves the actual table with location, mechanical
  pain, bone lesion, alignment, collapse, posterolateral involvement, and the
  0-18 range.
- **Koos paraphrase** — `Greenberg`, p.776: the general low-value filter
  initially mistook flattened table cells for navigation. The final
  table-aware exception retrieves grades I-IV from intracanalicular tumor to
  brainstem/cranial-nerve displacement.
- **House-Brackmann paraphrase** — `Greenberg`, p.771: lexical retrieval alone
  preferred a vestibular-schwannoma outcome passage; bounded semantic fallback
  brought the grading table into the packet, including normal function through
  complete paralysis.
- **Simpson paraphrase** — `Youmans and Winn`, p.498: the component signature
  resolves to Simpson and retrieves the five-grade resection framework,
  including dural attachment, involved bone, subtotal removal, and
  decompression/biopsy.

These examples drove the ranking changes. A result that merely named the right
scale but placed a generic discussion above the defining table was counted as a
qualitative defect and repaired.

## Rejected Experiments

- **Semantic-only routing:** fast after model load, but the pruned embedding
  corpus favored conceptually adjacent discussions for SINS, Simpson, Knosp,
  and Koos. It lost 30.41 percentage points of anchor recall versus the
  accepted router.
- **Hybrid on every lookup:** matched overall recall but doubled warm latency
  and slightly reduced top-passage recall.
- **Concurrent lexical and ONNX phases:** CPU contention erased the theoretical
  overlap on this machine, so the simpler sequential cost ladder was retained.
- **Smaller full-RAG rerank pool, INT8 reranking, and narrower semantic entity
  windows:** tested in the full-pipeline work; rejected when they regressed the
  quality/latency frontier.

## Reproduce

```bash
source .venv/bin/activate
python3 src/lance_retriever.py mini-preflight
python3 benchmarks/benchmark_mini_rag.py \
  --strategies lexical,semantic,hybrid,auto \
  --repeat 5 \
  --output /tmp/mini_rag_strategy_comparison.json
```

The benchmark evaluates textbook retrieval, not clinical currency. Current
guidelines, conduct-changing thresholds, drug dosing, reversal, timing, and
controversies still require current primary-source verification.
