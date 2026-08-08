# Repository Architecture Audit

Date: 2026-08-08  
Branch: `codex/repo-architecture-overhaul`  
Baseline: `bcb67ec`

## Executive judgment

The repository was not conceptually obsolete. Its strongest ideas—one shared
authority, thin adapters, progressive contract loading, provenance-isolated
memory, deterministic teaching policy, and evidence-specific retrieval—match
current agent-system guidance. The weakness was that these ideas were expressed
mostly as prose and conventions. That made the system understandable to a strong
model but difficult to validate, resume, benchmark, or protect from drift. The
subsequent study-review overhaul is documented in
`docs/architecture/Study Review Architecture And Pedagogy.md`.

The recommended architecture is therefore not a many-agent rewrite and not a
framework migration. It is a **hybrid deterministic shell with an agentic
reasoning core**:

- deterministic code owns routing constraints, state transitions, approvals,
  persistence, provenance, and validation;
- the model owns clinical reasoning, synthesis, teaching, and decisions inside
  the permitted node;
- context is projected per workflow and per phase rather than loaded globally;
- durable state is used only where interruption or multi-artifact work makes it
  valuable;
- independent agents or reviewers are used only when independence itself adds
  measurable value.

This audit implemented that target rather than adding a graph library for its
own sake. The current graph compiler covers all 12 canonical workflows and the
`service-log` alias, reduces entry context by a median 68.4%, detects every one
of six injected control-flow defects, and compiles the complete registry in a
1.72 ms median. A framework such as LangGraph would currently add dependency and
operational surface without providing a demonstrated benefit that the local
kernel lacks.

## Scope and evidence

The audit covered:

- 63 Python source modules (35,555 lines);
- 43 deterministic test modules (13,947 lines);
- 53 shared instruction contracts;
- 13 generated runtime specifications representing 12 canonical workflows plus
  one alias;
- 13 Codex skills, 13 Claude commands, 13 Gemini commands, 13 plugin skills,
  and 13 plugin commands generated from one registry;
- five SQLite stores, three Lance/vector stores, live Anki integration, the
  session artifact tree, the Obsidian index, and the textbook corpus;
- learner-memory state transitions, RAG routing and serialization, Anki startup,
  plugin portability, clean-clone dependencies, CI, and fallback behavior.

Conclusions were checked with source-level audits, schema and foreign-key
checks, controlled database copies, fault injection, deterministic behavioral
cases, live Anki A/B profiling, RAG quality/latency benchmarks, exact token
counts using `tiktoken`, and the complete test suite.

## Target architecture

```text
User request
    |
    v
AGENTS.md posture + routing boundary
    |
    v
workflow-registry.json  -- one canonical workflow identity
    |
    +--> generated adapters (Codex / Claude / Gemini / plugin)
    |
    v
typed runtime projection
    |
    v
minimal workflow kernel ----> run manifest for long/artifact workflows
    |
    v
current node + phase contracts only
    |
    +--> clinical reasoning / teaching / synthesis by the model
    +--> deterministic tools for retrieval, persistence, validation, and guards
    |
    v
explicit terminal state + validated artifact or answer

Cross-cutting, provenance-isolated stores:
  learner memory | curriculum inventory | vault intelligence | textbook RAG | Anki

Observability:
  health checks | graph validation | behavioral evals | benchmarks | CI
```

The graph is a control-plane representation, not a graph of autonomous personas.
That distinction matters: predictable work should remain a workflow; genuinely
open-ended reasoning should remain agentic inside a bounded node.

## Workflow-by-workflow assessment

Entry tokens include the selected runtime specification, the small runtime
contract, and entry-node contracts. Later contracts load only after a declared
transition.

| Invocation | Mode / state | Nodes | Entry tokens | Assessment |
|---|---|---:|---:|---|
| `anki-maintenance` | Approval gate / manifest | 6 | 2,044 | Correctly treats live Anki as authority, preserves review history, separates audit from mutation, and requires approval before apply. Explicit card-decision records close the prior ambiguity between “no card” and an unrecorded decision. |
| `consult` | Direct / ephemeral | 6 | 2,522 | Correct for bounded decisions. Evidence and durable capture are branches, not mandatory overhead. The broad Clinical Answer Doctrine remains outside this workflow so “manage X” does not automatically become a terse consult. |
| `generate-report` | Artifact graph / manifest | 6 | 8,254 | The largest entry surface, but still 43.9% below the flat comparator. Its plan → research → synthesis → validation loop is justified by evidence burden. Further splitting should be driven by model evals, not token count alone. |
| `grand-rounds` | Artifact graph / manifest | 8 | 5,352 | Case and article evidence branch before a shared deck/render/validation loop. Optional rehearsal is explicit and cannot create mastery unless evaluated. |
| `inbox-workflow` | Approval gate / ephemeral | 5 | 1,477 | Minimal and correctly asymmetric: reading and drafting may proceed; send/label mutation pauses for approval. This is the cleanest approval graph. |
| `intraoperative-guide` | Artifact graph / manifest | 11 | 5,330 | The most complex justified graph. Knowledge-map review and final independent review are the only isolated contexts. Gap repair and revision loops are explicit; incomplete evidence can pause for approval rather than being hidden. |
| `journal-club` | Artifact graph / manifest | 7 | 2,561 | Dossier creation and optional mastery review are cleanly separated. A slide request routes to `grand-rounds`, avoiding duplicate deck policy. |
| `memory-maintenance` | Approval gate / manifest | 5 | 3,785 | Audit-only is a terminal path; repair requires approval and verification. This preserves the rule that scripts persist evidence while agents interpret it. |
| `refactor-manual-note` | Direct / ephemeral | 6 | 2,714 | In-place rewrite is primary. Answer/expand/verify/distill and visualization are explicit optional branches, not default mode inflation. Existing user prose and attachments remain protected. |
| `service-log` | Alias to shift debrief / manifest | 6 | 2,772 | Correctly shares artifact behavior while adding rotation/site provenance. The service lens now exposes rotation state, rubric progress, scoped review candidates, and generic-domain backlog instead of guessing classifications. |
| `shift-debrief` | Artifact graph / manifest | 6 | 2,775 | Capture is exposure, not mastery. De-identification precedes persistence, portable knowledge is separated from local convention, and review is optional. |
| `study-material` | Artifact graph / manifest | 6 | 2,764 | Generate and drill are distinct branches. Passive generation cannot create learner evidence; the drill loop can. |
| `study-review` | Conversation loop / learner memory | 5 | 2,473 | Typed startup emits a bounded TutorState; one raw answer and all independently graded claims persist atomically; artifact/vault freshness gates, one-hop expansion, pending adjudication, and integrity-gated close preserve depth without loading audit policy at entry. |

No canonical graph is unreachable or cyclic without an explicit loop edge. All
mutating administrative workflows have approval nodes. Only two nodes—the two
independent reviews in the operative guide—use isolated context.

## Skills, commands, and instruction authority

The prior architecture had the right authority hierarchy but incomplete
enforcement. The new generation pipeline makes the registry and shared
contracts executable authority:

1. `AGENTS.md` owns posture, safety, routing, and boundaries.
2. `.agents/shared/workflow-registry.json` owns workflow identity, destination,
   lifecycle, and the execution graph.
3. `.agents/shared/commands/` owns behavior.
4. `.agents/shared/runtime/` contains generated selected-workflow projections.
5. Codex, Claude, Gemini, and plugin surfaces are generated adapters.

The audit removed two stale Codex-only entry points:

- `anki-deck-maintenance` duplicated the canonical `anki-maintenance` workflow;
- `anki-card-quality` exposed a phase module as if it were a standalone
  workflow.

The synchronizer now detects unregistered generated files as drift. The plugin
is self-contained: contracts, runtime specs, root policy, workflow schema,
style configuration, and the reference deck are bundled under the plugin root.
The prior absolute external deck path and `../../` skill escape are gone.

Current active instruction size is 106,000-range `cl100k_base` tokens across all
generated copies, but that aggregate is not loaded into one model turn. The
relevant measure is selected startup context: 1,595–8,368 tokens across the 13
invocations, with a 68.4% median reduction from the flat-registry comparator.

## Store-by-store assessment

| Store | Current state | Role and audit judgment |
|---|---|---|
| `data/study_memory.db` | Schema 8; 78 sessions, 302 exchanges, 295 claim results, 235 claim states, four hash-verified artifact maps; integrity and foreign keys pass | Canonical learner evidence only. Typed turn envelopes, multi-claim dimensions, pending adjudication, learner-stage context, explicit card decisions, conservative retention/transfer, and atomic lifecycle state are additive; historical evidence was preserved during migration. |
| `data/concept_inventory.db` | Schema 1; 2.04 MB; 11 domains, 127 topics, 1,243 concepts, 3,375 edges, 1,000 ACGME links; integrity passes | Curriculum authority, not learner state. Identity-first aggregation now joins learner evidence across envelopes while preserving unresolved/out-of-scope rows. |
| `data/vault_index.db` | Schema 1; 97 current notes and 786 sections; zero stale, missing, unindexed, or parse-error paths | Supplemental Obsidian intelligence. It cannot limit clinical knowledge or become learner state. Freshness is checked against current file hashes before retrieval. |
| `data/anki_vector_cache.db` | Schema 1; 0.92 MB; 257 card vectors, 13 cached query embeddings; integrity passes | Rebuildable semantic cache only. Live Anki remains ground truth. Every cached live row currently has a usable card id, allowing remote note-resolution calls to be skipped. |
| `data/mini_rag_fts.db` | Schema 1; 167.7 MB; 58,899 chunks; integrity passes | Fast lexical index for named scales, tables, classifications, and compact references. |
| `neurosurgery_v4.lance` | Table version 7; 15.8 GB; 58,899-row textbook corpus; 7 manifests | Full textbook retrieval. The adopted corpus now has a stable fingerprint and source-role filtering. Historical ingestion version remains honestly `legacy-unrecorded`; future rebuilds must record the producing pipeline version. |
| `data/mini_rag.lance` | 7.5 MB; one manifest | Semantic companion for Mini-RAG. Lexical remains the default when hybrid retrieval adds latency without quality gain. |
| `data/vault_index.lance` | 786 section vectors; generation matches the SQLite index | Physically isolated vault vectors and the sole active vault-vector store. Combined recall reports generation agreement and discards stale paths rather than presenting them as current. |

The live service tables are intentionally empty because no rotation has been
started in the database. This is not a schema failure. The prior operational
problem was invisibility: 29 pending portable shift candidates remain in the
generic domain. The service lens now reports that backlog and excludes it from
service steering until explicitly classified.

After the separately approved hygiene review on 2026-08-08, `data/Sessions`
contains five files totaling 69,733 logical bytes and no old run manifests.
1,945 obsolete, duplicated, installed, or transient legacy files were removed
only after their producer and canonical replacement were checked. Three unique
learning artifacts and the active Anki queue remain; new artifact workflows use
run-scoped manifests and explicit terminal states.

## Code and dependency assessment

- Runtime paths and schema expectations are centralized instead of repeated in
  modules.
- SQLite stores have explicit health, version, component, quick-check, and
  foreign-key reporting.
- Atomic writes and vault-refresh hooks are shared utilities.
- Retrieval library code no longer owns a duplicate CLI, and top-level import
  cycles are rejected.
- `study_memory.py` remains the largest module at the enforced 7,800-line cap.
  Schema, CLI parsing, service memory, card decisions, and other authorities
  have been extracted. Future functionality should go into focused modules; the
  budget should not be raised casually.
- `retrieval/pipeline.py` is below its 3,400-line budget and cannot import the
  batch orchestrator, preserving dependency direction.
- `pyproject.toml`, locked requirements, clean-clone installation, and Python
  version bounds now make the environment reproducible.

## Learning and teaching intelligence

Two subtle calibration defects were found by executable longitudinal cases:

1. An asserted retention check could previously promote a repaired claim before
   its due time. Retention now requires another session and the scheduled delay;
   early attempts record `retention_not_due`.
2. Repeated transfer success did not require temporal separation. One transfer
   success now produces relational evidence; `transfer_ready` requires at least
   two successful transfer probes across two sessions spanning at least seven
   days, with no active gap.

Response latency remains advisory and cannot independently create mastery. The
same operation-evidence representation is used by startup projection, SQLite
fallback, artifact overlays, and live session-map updates. All nine learner
memory benchmark cases pass, including exact claim traces, cross-topic identity,
cross-domain scope, state transitions, conservative mastery, new-topic
orientation, and bounded startup.

Anki eligibility is now explicit per evaluated exchange. A durable
`anki_card_decisions` row distinguishes enqueue, routine-correct skip,
equivalent-card skip, low-value skip, not-durable skip, and unavailable deferral.
Passive artifact creation still produces no mastery and no cards.

## Retrieval and provenance assessment

RAG now emits a stable corpus fingerprint, table version, model identifiers,
pipeline version, source roles, and manifest hashes. Clinical queries exclude
the two known grant-writing sources; explicit grant queries may still retrieve
them. Both Mini-RAG and full RAG serialize provenance into their source-card
manifests.

Measured current results:

| Path | Quality | Latency | Decision |
|---|---:|---:|---|
| Mini lexical, 16 cases | Anchor recall 0.9563; entity recall 1.0 | 34.11 ms/query warm | Retain as the efficient default. |
| Mini hybrid, same cases | Same anchor and entity recall | 53.97 ms/query warm | Do not force; no quality gain. |
| Mini auto, same cases | Same anchor and entity recall | 36.81 ms/query warm | Retain for paraphrases that need semantic assistance. |
| Full batch, 8 clinical syntheses | Anchor/entity recall 1.0; mean quality 0.9914 | 33.23 s total; 4.15 s/query | Retain batch for independent multi-topic synthesis. |
| Historical scalar comparator | Anchor recall 0.95; quality 0.9645 | 79.05 s total; 9.88 s/query | Retired for multi-query work; scalar remains correct for one synthesis. |

The previously tested 32-candidate full-RAG pool, dynamic INT8 reranking, and
smaller semantic windows were rejected because they moved latency without
preserving the quality frontier. This is the right optimization posture: route
more intelligently before shrinking retrieval blindly.

## Performance and ablation results

| Ablation | Before | After | Result |
|---|---:|---:|---:|
| Workflow entry context | Flat registry + entry contracts | Typed projection + entry-node contracts | 69.8% median reduction; 43.9% minimum |
| Graph defect detection (6 injected defects) | JSON parse: 0/6 | Typed compiler: 6/6 | Keep typed kernel |
| Full registry compilation | N/A | 2.33 ms median, 2.81 ms p95 | Negligible control-plane cost |
| Live Anki connector calls | 7/startup | 2/startup | 71.4% fewer |
| Live Anki connector time | 161.72 ms | 64.04 ms | 60.4% faster |
| Live Anki profile wall time | 175.26 ms | 75.83 ms | 56.7% faster, payload unchanged |
| Learner startup packet | 96,564 bytes initial baseline | 42,820 bytes | 55.7% smaller; all 9 behavior cases pass |

The Anki comparison dynamically loaded the exact baseline implementation from
`bcb67ec` and current code against the same live Anki and vector cache for five
warm repetitions. The harness and memory measurements are stored under
`benchmarks/`.

## Behavioral evaluation and CI

`evals/agent_behavior_cases.json` adds:

- 12 prompt-routing cases covering broad teaching, urgent consults, single
  facts, named scales, study review, artifacts, email approval, read-only audit,
  service provenance, and deck routing;
- 14 complete state-transition scenarios covering all 12 canonical graphs,
  approval/decline branches, repair loops, optional review, and isolated review.

CI validates adapters, typed graphs, instruction lint, code architecture,
behavioral paths, harness ablation thresholds, and the full deterministic test
suite. Model routing is provider-neutral: prompt packets can be emitted and
candidate-model JSONL decisions graded exactly. CI does not claim a live model
score unless a real prediction file is supplied.

## Comparison with current agent-system guidance

The redesign follows current primary guidance without copying framework fashion:

- Anthropic distinguishes fixed workflows from agents and recommends the
  simplest composable architecture that measurably works. It specifically
  identifies routing, prompt chaining, parallelization, orchestrator-workers,
  and evaluator-optimizer as patterns to apply selectively, not layers every
  task needs. The repository now uses fixed graphs for predictable clinical and
  artifact lifecycles while leaving reasoning inside nodes flexible.
  [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- OpenAI distinguishes LLM-directed orchestration from code-directed
  orchestration and recommends mixing them. Code is preferred when speed, cost,
  and predictability matter; managers, handoffs, and parallel workers fit
  genuinely open-ended subtasks. This supports the local kernel plus selective
  independent review rather than a permanent multi-agent hierarchy.
  [Agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/)
- OpenAI also separates local application context from model-visible context
  and supports on-demand tools/retrieval for the latter. This matches the
  repository's explicit conversation, run-scoped, and isolated contexts plus
  progressive contract loading.
  [Context management](https://openai.github.io/openai-agents-python/context/)
- LangGraph emphasizes durable execution, human-in-the-loop, state, nodes, and
  edges for long-running work. The repository now implements the small subset it
  actually needs. A LangGraph migration becomes rational only if cross-process
  resume, streaming, task queues, or dynamic fan-out become real requirements.
  [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- Google's current skill guidance explicitly uses progressive disclosure to
  avoid monolithic system prompts. The measured selected-context reduction
  confirms that the repository's generated phase projections achieve the same
  objective.
  [ADK agents with skills](https://developers.googleblog.com/developers-guide-to-building-adk-agents-with-skills/)
- Anthropic's long-running-agent experiments found that compacted conversation
  alone is insufficient; agents need structured feature state, incremental
  progress, clean handoffs, and real end-to-end tests. Run manifests, explicit
  terminal states, the persistent goal plan, and validation artifacts provide
  that structure here.
  [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

## What should not be redesigned now

1. **Do not replace the local kernel with LangGraph or an Agents SDK yet.** The
   current kernel is small, framework-free, fully tested, and compiles in about
   2.3 milliseconds. Adopt a runtime when a runtime requirement appears, not to
   make the diagrams more fashionable.
2. **Do not convert every workflow into a specialist agent.** Most repository
   work is predictable and safety-sensitive. Agent proliferation would increase
   context handoff, latency, cost, and error compounding. Use workers only for
   independent parallel research or evaluator roles with clear merge criteria.
3. **Do not merge the databases.** Learner evidence, curriculum truth, vault
   recall, textbook evidence, and Anki scheduling have different authorities and
   failure modes. Their separation is semantic safety, not accidental sprawl.
4. **Do not treat the instruction graph as the knowledge graph.** Workflow
   control, curriculum relationships, learner evidence, and vault links are
   separate graphs with different update policies.
5. **Do not infer historical provenance.** `legacy-unrecorded`, unclassified
   shift candidates, and legacy session artifacts should remain explicit until
   rebuilt or reviewed.
6. **Do not delete migration fallbacks from aesthetics alone.** The exact-success
   bridge was removed only after 6,444 persisted nodes proved migration complete.
   The vault-vector fallback was removed only after the isolated store passed
   integrity checks and Gabriel explicitly approved cleanup.

## Conditional next steps

These are triggers, not unfinished implementation:

- Run the provider-neutral behavior suite against each candidate model release;
  change prompts or routing only when case-level results justify it.
- Rebuild the textbook corpus through a versioned ingestion pipeline when source
  additions or embedding changes are needed; that is when
  `legacy-unrecorded` should disappear.
- Start and seed service rotation state when Gabriel supplies the active service
  and site. Do not infer institutional context from old portable notes.
- Continue extracting focused modules from `study_memory.py` when adding new
  capabilities so its line budget remains a real boundary rather than a number
  that grows with every feature.

## Validation commands

```bash
source .venv/bin/activate
python3 src/sync_agent_adapters.py --check
python3 src/workflow_runtime.py validate
python3 src/instruction_audit.py lint
python3 src/code_architecture_audit.py
python3 src/behavioral_eval.py validate
python3 src/system_health.py --json
python3 benchmarks/benchmark_agent_harness.py --repeat 100 --check
python3 benchmarks/benchmark_memory_layer.py --repeat 5
pytest -q
```

Live/local integrations have separate checks:

```bash
python3 benchmarks/benchmark_anki_startup.py --baseline-ref bcb67ec --repeat 5
python3 benchmarks/benchmark_mini_rag.py --strategy all
python3 benchmarks/benchmark_rag_pipeline.py --mode batch
```

## Final conclusion

The repo should be thought of as a small domain-specific agent operating system,
not a collection of prompts and not a society of autonomous agents. Its durable
advantage is the separation of authorities: policy, workflow, evidence,
curriculum, learner state, local knowledge, and external action. The audit makes
those boundaries executable and measurable. The resulting design is more
graph-like where graphs add control, but simpler where model intelligence makes
fixed orchestration unnecessary.
