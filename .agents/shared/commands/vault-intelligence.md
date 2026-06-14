# Vault Intelligence

Shared contract for using the Obsidian vault as a field-aware personalized context layer.

The vault is high-signal, user-specific context. It is not the full neurosurgery curriculum and not a ceiling on what the agent can teach. Agents combine:

1. learner memory from `study_memory.py`;
2. vault intelligence from `src/vault_retriever.py`;
3. native clinical knowledge and tutoring judgment;
4. textbook, guideline, PubMed, or other formal verification when accuracy or completeness requires it.

Absence from the vault means only "not yet captured in Gabriel's notes." It never means the concept is unimportant, unknown, or outside the teaching scope.

## Storage Boundary

- `data/study_memory.db` remains the learner-state database: exchanges, claim results, claim state, review candidates, curated summaries, graph signals, and service memory.
- `data/vault_index.db` is the compiled Obsidian section index: note metadata, headings, section text, section hashes, wikilinks, references, provenance tier, and field type.
- LanceDB table `vault_notes` is a dedicated vault vector table. It stores embedded section payloads from the vault and stays separate from the textbook table `neurosurgery_v4`.

Do not copy full vault content into learner memory. Link learner-state needs to vault sections at runtime.

## Sync And Recall Tools

Guard-installed artifacts refresh the SQLite section index automatically when they write to the real Obsidian vault. Run sync manually before a retrieval-dependent workflow if the index may be stale:

```bash
python3 src/vault_retriever.py sync --pretty
```

Semantic vector sync loads the embedding stack and is therefore deliberate rather than part of every artifact write. Run it after batches of vault edits, before vector-dependent audits, or when the `recall` packet reports stale, missing, or failed LanceDB context:

```bash
python3 src/vault_retriever.py sync-lance --table vault_notes
```

Use combined vault recall for workflows that intentionally need vault context. This is the normal vault entry point. It emits compact minified JSON by default, runs field-aware SQLite retrieval and LanceDB semantic retrieval, deduplicates section hits, and groups the result by field type for agent planning:

```bash
python3 src/vault_retriever.py recall "<query>" --task "<task>" --limit 8
```

Use exact section retrieval when the note and field are known:

```bash
python3 src/vault_retriever.py get --note "Concepts/ENRICH Trial.md" --section-type evidence_card --pretty
```

The lower-level SQLite and Lance search subcommands are inspection tools for audits and debugging. Teaching workflows should start with `recall` so the agent receives one compact packet with lexical, field-aware, and semantic evidence already merged.

Parse JSON silently. Read `retrieval_status`:

- `complete`: SQLite and LanceDB both executed; use the merged packet normally.
- `partial`: at least one retriever produced usable context; use the available `merged_hits`, respect the warning, and run `sync-lance` only when the missing vector context would materially improve the task.
- `failed`: do not pretend the vault returned context. Use native clinical knowledge and formal sources, then troubleshoot the index if the workflow depends on vault memory.

Surface only concise retrieval failure, stale-index warning, or clinically relevant provenance limitations.

## Field Policy

Prefer exact field retrieval before broad note retrieval.

| Field | Use |
|---|---|
| `quick_reference` | Fast orientation, pre-round refresh, concise answer framing |
| `clinical_focus` | Brain-dump topic inventory and scope recognition |
| `priority_takeaways` | Next-shift consequence and short retention hooks |
| `clinical_use` | Why the concept changes management, diagnosis, prognosis, or operative conduct |
| `clinical_synthesis` | Integrated explanatory content from reports, consults, and brain dumps |
| `durable_mental_model` | Repair after misses, retention hooks, analogies, and mechanism reframing |
| `operational_mental_model` | Service/operative practical models and decision trees |
| `critical_discriminators` | High-friction distractors, oral-board contrasts, confusable entities |
| `execution_check` | Readiness prompts, action questions, next-shift application |
| `evidence_card` | Trial/guideline metrics, inclusion criteria, effect measures, evidence boundaries |
| `surgical_coordinates` | Operative anatomy, corridors, danger structures, spatial rehearsal |
| `consequence_matrix` | Classifications, staging, grading, and management consequences |
| `bedside_decision_rule` | Consult decisions, ICU thresholds, escalation, ward algorithms |
| `imaging_read` | Radiographic signs, sequence selection, and interpretation traps |
| `mastery_objectives` | Coverage planning and session-completeness checksum |
| `local_clarifications` | Institution, service, site, attending, or local workflow constraints |
| `references` | Provenance, source links, and high-stakes verification support |
| `related` | Crosslinks and adjacent review suggestions |

## Task Routing

Use these task names with `--task`:

- `doc-review`: Retrieve mastery objectives, discriminators, mental models, execution checks, quick references, synthesis, and related links around a requested document. The requested document remains primary.
- `weak-spot-review`: Retrieve discriminators, mental models, execution checks, evidence cards, bedside rules, and clinical-use fields for learner-memory targets.
- `concept-repair`: Retrieve the durable mental model, discriminators, execution check, and clinical use for a missed or unstable concept.
- `consult`: Retrieve quick reference, bedside rule, evidence card, clinical use, and references for a bedside procedure or protocolized task.
- `service-local`: Retrieve local clarifications, priority takeaways, clinical synthesis, operational mental models, and mastery objectives from service-aware notes. Keep these separate from formal knowledge.
- `operative-rehearsal`: Retrieve surgical coordinates, discriminators, execution checks, operational mental models, and clinical-use fields.
- `imaging`: Retrieve imaging reads, discriminators, clinical-use fields, and quick references.
- `trial-evidence`: Retrieve evidence cards, quick references, discriminators, and references.
- `report-generation`: Retrieve quick references, synthesis, evidence cards, related links, and references to avoid duplicating prior vault work.

## Teaching Use

Vault retrieval should make teaching more personalized, not narrower:

- Use `critical_discriminators` to build distractors and contrastive follow-ups.
- Use `durable_mental_model` after a miss or shallow answer to repair memory with Gabriel's existing cognitive hook.
- Use `execution_check` to turn knowledge into an action-oriented oral-board or next-shift prompt.
- Use `evidence_card` to anchor trials, guidelines, and thresholds.
- Use `local_clarifications` only when the user asks about a service/site/local practice or when preserving provenance in a Brain Dump review.
- Use `references` when the answer contains high-stakes numbers, drug/dose details, operative strategy claims, or evolving evidence.

During `study-review`, vault recall is not a startup step. The requested document plus SQLite `startup-recall` plus Anki overlay form the startup context. Use vault recall only at point of need: after Gabriel misses, gives a partially correct answer, shows a recurring false rule, needs a different explanatory frame, asks for local/service context, or asks to compare against an adjacent note. Then run:

```bash
python3 src/vault_retriever.py recall "<missed concept or corrected rule>" --task concept-repair --limit 5
```

Use the result to choose one targeted repair: a discriminator, mental model, execution check, or evidence anchor. Then ask a near-transfer retest. Do not turn a miss into a broad vault-note lecture unless the user asks for a full reveal.

Do not withhold useful teaching because it is absent from the vault. Native knowledge is expected and valuable. For high-stakes clinical details, verify with formal sources when vault support is thin, local, stale, or absent.

## Provenance

Each retrieved section carries `provenance_tier` and `source_role`.

- `source_linked`: section has explicit source links and may support source-grounded teaching after semantic review.
- `curated_vault_context`: useful personalized context, but not independently verified by the retriever.
- `mixed_internal_knowledge` or `verify_before_clinical_use`: use for framing, then verify high-stakes specifics.
- `experiential_service_context` and `local_or_institutional`: local practice context only; do not promote to universal standard without verification.

When the vault conflicts with formal retrieval or native knowledge, resolve the conflict explicitly and preserve provenance. Do not silently let local or experiential notes override formal evidence.
