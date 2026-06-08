# Brain Dump

Capture de-identified teaching received on service, connect it to mechanism and practical action, verify the teaching against available sources, and preserve it as a compact artifact for later active review.

This workflow is for exposure capture, not demonstrated mastery. A senior resident correction or lesson is valuable evidence of what Gabriel encountered; it is not evidence of what he can yet retrieve or apply.

Follow `.agents/shared/commands/learning-session-contract.md` only where this contract invokes learner testing. Use `memory-operations.md` and `memory-retrieval.md` for silent learner-context retrieval, artifact-anchor logging, atomic review-candidate logging, and optional Socratic conversion. Use `vault-intelligence.md` only as supplemental context for prior related vault notes and provenance-aware local clarifications. Use `review-artifacts.md` for the vault destination and `anki-card-quality.md` for cards generated only after evaluated answers.

## When To Use

- Explicit `/brain-dump`.
- "Capture what I learned on shift", "senior corrected me on service", "ward teaching lesson", or a debrief containing a clinical correction/lesson.
- A messy set of teaching fragments from the ward, ICU, OR, or sign-out that should become a useful retained mental model.

Do not use for:
- A direct management question needing an immediate answer or pocket card: use `/consult`.
- A knowledge test or weak-spot drill: use `/study-review`.
- A comprehensive literature/reference product: use `/generate-report`.

## Success Criterion

The resident has a compact, de-identified, provenance-honest brain dump note that states what the reported teaching means, why it changes action, what is verified versus locally contingent, and how to test it later.

## Hard Boundaries

1. **De-identify before processing or persistence.** Do not send identifiable patient details into RAG, memory entries, Anki, or the vault. Strip names, MRNs, room/bed identifiers, full dates of birth, contact details, and identifiable timelines. If de-identification would remove the educational meaning, ask for a sanitized restatement before proceeding.
2. **Capture is not testing.** Do not create `claim_state`, open gaps, repairs, mastery, or curation evidence merely because Gabriel reports a teaching point. `/brain-dump` memory writes use `skill="brain-dump"` as an artifact anchor only.
3. **Memory remains invisible.** Topic-scoped memory may shape depth and later probe options. Never narrate stored gaps, cards, summaries, or inferred learner state to Gabriel.
4. **Do not universalize local practice.** Separate general clinical principles from institution/service conventions and patient-specific decisions.
5. **Keep the artifact compact.** This is neither a report nor a consult pocket card. Capture the educational edge, not a comprehensive chapter.
6. **Concept promotion belongs to verified synthesis workflows.** Brain dumps preserve local and experiential provenance during capture; generalizable concepts are promoted later through report, consult, study-material, grand-rounds, or operative-guide workflows that can support a durable concept card.
7. **Atomic candidates are not mastery.** Each canonical teaching point gets a pending review candidate so it can be found later, but it becomes learner-state evidence only after a Socratic answer is evaluated.

## Workflow

### 1. Intake And Sanitization

Parse the input into one or more related teaching points. A single shift debrief may remain one artifact when its fragments share the same service encounter and the combined note stays compact; use clearly numbered teaching-point subsections. Create separate topic artifacts when the dump spans unrelated clinical domains, or when a fragment needs report-scale treatment rather than a concise bridge.

Before retrieval or writing, produce an internal sanitized version. Generalize patient context to clinically necessary descriptors, for example:

- `postoperative posterior fossa patient during transport`
- `external ventricular drain with concern for pressure gradient change`

Never preserve identifying labels or a unique patient timeline.

Create a `## Clinical Focus` section at the top of the artifact, containing a direct, academic bulleted list of the clinical topics and questions covered. Keep this section limited to clinical concepts, anatomic regions, management questions, and decision points.

Immediately after the clinical focus list, add `## Priority Takeaways`: one to three short bullets ordered by learning value and next-shift consequence. This is the retention layer. It should answer, within seconds, "what should I remember or change tomorrow?"

### 2. Extract and Synthesize the Teaching Edge

For each topic, identify:
- **Teaching trigger**: the de-identified clinical situation or correction.
- **Reported rule**: what the senior appeared to teach.
- **Operational consequence**: what action, order, monitoring step, or escalation changes.
- **Uncertainty**: what could be service-specific, patient-specific, incompletely understood, or in need of confirmation.

Synthesize these elements along with verified source material into a unified `## Clinical & Anatomical Synthesis` section.

### 3. Silent Memory Context

Retrieve the learner's document memory using the document-anchored `startup-recall` command from `memory-operations.md` to initialize context.

Read `planning_brief`, `counts`, `omitted`, and `retrieval_guidance` per `memory-retrieval.md`; expand with `--profile audit` only if the compact brief is ambiguous or safety-critical context is missing. Use this context to choose explanation depth and future review suggestions. Do not state what memory returned.

If the dump names a service/site-specific practice and an active service context is needed, resolve the rotation and use `startup-recall --lens service` from `memory-operations.md` for local memory.

### 4. Targeted Source Verification and Academic Synthesis

Before or alongside formal verification, query vault intelligence for related prior context when it can improve synthesis or provenance handling:

```bash
python3 src/vault_retriever.py recall "<sanitized teaching topic>" --task service-local --limit 5
```

Use this to find prior local clarifications, operational mental models, and related Brain Dumps/Consults. Do not use vault retrieval to universalize local practice; formal claims still require focused source verification.

Use focused RAG queries for management-changing claims, mechanisms, thresholds, and anatomy or physiology claims:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "<focused verification query>" --stdout [--no-frontier]
```

Run one focused query per load-bearing claim when necessary; do not execute a report-scale retrieval campaign.

Draft the clinical synthesis in a professional, peer-reviewed textbook voice:
- **Academic Inline Citations**: Cite claims inline using standard formats, e.g., `(Yoo et al., 2019)` or `(Youmans & Winn, 8th ed., Vol. 5, p. 331)`.
- **Integrated Resolution**: Seamlessly integrate reported clinical teaching and verified literature in a single narrative. If the remembered teaching was incorrect or incomplete, resolve it directly in the text, e.g., *"Although reported as a preference for posterior correction, approach selection is actually driven by..."*.
- **Medication & High-Stakes Support**: Medication, postoperative order, threshold, and operative-strategy claims have a higher source standard. Actively look for at least one `Guideline/formal guidance` or `Primary study` source in the references. When that support is unavailable after a focused search, record the limitation in `## Institutional & Local Clarifications`.

### 5. Advanced Operational Mental Models

Create a `## Operational Mental Models` section.
- Operational mental models must serve as powerful cognitive hooks, spatial analogies, or biomechanical/anatomical decision trees (e.g., the *Coaxial Cylinder Model* for paraspinal layers, or the *Sagittal Balance Decision Tree*).
- Prefer perspectives or reframes that make the material durable: spatial analogies, biomechanical decision trees, layered anatomy models, escalation thresholds, or causal chains.

### 6. Institutional & Local Clarifications

Create an `## Institutional & Local Clarifications` section. Group all service preferences, local protocols, attending-specific variations, or unresolved clinical uncertainties here as points to verify at the point of care.

### 7. Draft And Guard The Artifact

Real target:

`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Brain Dumps/<Topic Title>.md`

Draft to:

`data/Sessions/brain_dump_<slug>.md`

For a new topic, the note must contain:

```markdown
## Clinical Focus

## Priority Takeaways

## Clinical & Anatomical Synthesis

## Operational Mental Models

## Institutional & Local Clarifications

## Mastery Objectives

## Related In This Vault

## References
```

Each reference bullet must begin with its evidence-type label and include hyperlinked details, for example:

- `Guideline/formal guidance: PROSPECT Working Group. [Summary recommendations: Complex spine surgery](https://...). 2020.`
- `External review: Yoo JS, et al. [Multimodal analgesia after spine surgery](https://...). *J Spine Surg*. 2019.`
- `Internal textbook RAG: Youmans and Winn, 8th ed., Vol. X, p. Y`

The note must end with bottom YAML:

```markdown
---
tags: [skill/brain-dump, domain/<domain>, type/reference, source/user]
generated: YYYY-MM-DD
skill: brain-dump
provenance: "<short clinical topic focus>"
internal_knowledge_used: true|false
---
```

If `Brain Dumps/<Topic Title>.md` already exists, read it and produce a complete revised draft that preserves prior body content while adding:

`## Brain Dump - YYYY-MM-DD`

The encounter section must retain the same de-identification and provenance distinctions. Update mastery objectives and bottom YAML only when necessary.

### Artifact-Only Smoke Test

When Gabriel explicitly requests a live artifact smoke test without memory writes:

- complete sanitization, verification, drafting, guard installation, and installed-file validation;
- do not run silent learner-memory retrieval, `log-answer`, `end-session`, concept extraction, or any Anki queue operation;
- state in the completion report that the vault artifact was written but memory and Anki were intentionally untouched.

This mode tests the artifact product and safety gate without asserting learner state
or leaving memory bookkeeping side effects.

Before installing any real artifact:

```bash
python3 src/brain_dump_guard.py install \
  --draft "data/Sessions/brain_dump_<slug>.md" \
  --title "<Topic Title>"

python3 src/brain_dump_guard.py validate \
  "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Brain Dumps/<Topic Title>.md"
```

Parse guard JSON silently. Surface only pass/fail, installed path, and actionable safety/structure errors. The guard enforces structure and rejects common direct identifiers. It is a final safety net, not permission to feed raw identified input into tools.

### 7. Artifact-Anchor Memory Write

Log a sanitized discoverability anchor using `study_memory.py log-answer` (with `skill="brain-dump"`) and close with `study_memory.py end-session` per `memory-operations.md`.

`brain-dump` behaves as an artifact anchor: it creates discoverability/session handoff context, but no assessed claim result, durable learner state, or curation evidence.

### 8. Atomic Review Candidates

After the artifact-anchor write, log one pending review candidate per canonical teaching point using the `brain-dump-candidate-add` command from `memory-operations.md`. Use portable `origin=assessed` for general clinical knowledge and `origin=service` only for site/service-specific conventions or service-origin operational habits (requiring an active rotation).

These candidates power later reviews. They must not create Anki cards or curation evidence during initial capture.

### 9. Optional Socratic Review Or Anki

At completion, offer the option to run an immediate active Socratic lesson. End the response with exactly: `Do you want to complete a quick Socratic lesson on these items?` If Gabriel chooses testing, ask one Socratic question at a time. For each evaluated answer, run `log-answer` with `--brain-dump-candidate-id <id>` (per `memory-operations.md`) so the pending candidate is marked reviewed and linked to the resulting claim state.

**Dedicated provenance-isolated Anki deck:** any card generated directly from `/brain-dump`, or generated while `/study-review` is anchored to a `Brain Dumps/` note, must route to:

`Neurosurgery::Brain Dumps`

Tag those cards `brain-dump` and include other appropriate tags. This deck intentionally isolates institution- and lived-experience-origin learning from textbook/report-derived topic decks.

Do not create cards during initial capture. Create cards only after evaluated Socratic turns meet the ordinary Anki-generation criteria. Portable Brain Dump-derived cards route to `Neurosurgery::Brain Dumps`; site-local service conventions route to `Neurosurgery::Service Learning` (with `service-learning`, `service/<service>`, and `site/<site>` tags) and must not encode local practice as a universal rule.

## Completion

Surface:

- the concise teaching bridge;
- the brain-dump note path after successful install;
- whether any points remain locally confirmable or source-unverified;
- whether memory was recorded as an artifact anchor;
- how many pending atomic review candidates were logged;
- card count only if cards were produced during active Socratic review;
- the Socratic lesson prompt.
