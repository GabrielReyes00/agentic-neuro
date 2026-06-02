# Brain Dump

Capture de-identified teaching received on service, connect it to mechanism and practical action, verify the teaching against available sources, and preserve it as a compact artifact for later active review.

This workflow is for exposure capture, not demonstrated mastery. A senior resident correction or lesson is valuable evidence of what Gabriel encountered; it is not evidence of what he can yet retrieve or apply.

Follow `.agents/shared/commands/learning-session-contract.md` only where this contract invokes learner testing. Use `memory-operations.md` and `memory-retrieval.md` for silent learner-context retrieval and artifact-anchor logging, `review-artifacts.md` for the vault destination, and `anki-card-quality.md` for any explicitly requested cards.

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
6. **Do not create concept glossary entries during capture.** Brain dumps deliberately preserve local and experiential provenance; generalizable concepts can be promoted through later verified report or review workflows.

## Workflow

### 1. Intake And Sanitization

Parse the input into one or more related teaching points. A single shift debrief may remain
one artifact when its fragments share the same service encounter and the combined
note stays compact; use clearly numbered teaching-point subsections. Create separate topic
artifacts when the dump spans unrelated clinical domains, or when a fragment needs
report-scale treatment rather than a concise bridge.

Before retrieval or writing, produce an internal sanitized version. Generalize patient context to clinically necessary descriptors, for example:

- `postoperative posterior fossa patient during transport`
- `external ventricular drain with concern for pressure gradient change`

Never preserve identifying labels or a unique patient timeline.

Build a compact extraction map before the teaching synthesis. This flow is the
audit trail from messy input to durable learning value and should remain near
the top of the artifact for future scanning. Use terse markdown lines with typed
arrowheads, not a table:

- `raw fragment --> interpreted question --> verification target --> final teaching point`
- `muscle relaxer gap --> postop pain plan? --> guideline + reviews --> multimodal plan; spasm adjunct`

If the map reveals that a fragment is superficial, low-yield, or merely an
institutional habit, keep it but label the verification target honestly rather
than inflating it into a general clinical rule.

Keep each node short enough to scan in a few seconds. If a node needs a sentence,
the map is doing too much; put the explanation in `## Verified Bridge` instead.

Immediately after the extraction map, add `## Priority Takeaways`: one to three
short bullets ordered by learning value and next-shift consequence. This is the
retention layer. It should answer, within seconds, "what should I remember or
change tomorrow?" Do not bury the most important correction inside the verification
prose.

### 2. Extract The Teaching Edge

For each topic, identify:

- **Teaching trigger**: the de-identified clinical situation or correction.
- **Reported rule**: what the senior appeared to teach.
- **Operational consequence**: what action, order, monitoring step, or escalation changes.
- **Uncertainty**: what could be service-specific, patient-specific, incompletely understood, or in need of confirmation.

### 3. Silent Memory Context

Run topic-scoped retrieval only:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py startup-recall --topic "<topic>" --doc "Brain Dumps/<Topic Title>.md"
```

Read `planning_brief`, `counts`, `omitted`, and `retrieval_guidance` per `memory-retrieval.md`; expand only when high-signal items were omitted. Use this context to choose explanation depth and future review suggestions. Do not state what memory returned.

### 4. Targeted Source Verification

Use focused RAG queries for management-changing claims, mechanisms, thresholds, and anatomy or physiology claims:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "<focused verification query>" --stdout [--no-frontier]
```

Run one focused query per load-bearing claim when necessary; do not execute a report-scale retrieval campaign.

Classify each teaching point:

- **Source-grounded**: directly supported by a retrieved source; cite inline.
- **Service teaching - locally confirm**: plausible workflow, protocol, preference, or handoff practice that may vary institutionally; preserve as reported teaching and mark for local confirmation.
- **Clinical knowledge - verify**: clinically plausible synthesis not supported in retrieved text; flag high-stakes specifics before use in care.
- **Reported teaching corrected by verification**: the remembered teaching appears
  incomplete, overgeneralized, or contradicted by source-grounded material; retain
  the original teaching trigger but clearly state the corrected formulation and the
  question to bring back to the teaching resident or attending.

Never attach a source citation to a different claim than the passage supports.
Every verified clinical bridge in the installed artifact must link to its
supporting external source, such as a DOI, PubMed, or publisher full-text URL.
Internal textbook RAG can support synthesis, but an inaccessible local citation
alone is not sufficient for a verified clinical assertion in the vault artifact.

Keep the bridge compact. For each teaching point, prefer:

- one source-grounded sentence for the mechanism or correction;
- one source-grounded sentence for the clinical/action consequence;
- one optional `Operational mental model` line.

Move long caveats, medication lists, and exceptions into `Clarify Or Verify
Locally` unless they are essential to prevent a dangerous overgeneralization.

Label each cited support item by evidence type:

- `Internal textbook RAG`: retrieved local textbook passage or other private vault/index source.
- `External review`: peer-reviewed review, narrative review, systematic review, or best-evidence review.
- `Guideline/formal guidance`: society guideline, consensus statement, drug label, or institutional policy explicitly provided by Gabriel.
- `Primary study`: RCT, cohort, case-control, diagnostic accuracy study, cadaveric/anatomic study, or other original data.

Medication, postoperative order, threshold, and operative-strategy claims have a
higher source standard. For these claims, actively look for at least one
`Guideline/formal guidance` or `Primary study` source in addition to reviews and
internal textbook RAG. If none is available in a focused search, state that in
`Clarify Or Verify Locally` or `Sources`; do not silently let review articles be
the only support for a high-stakes management claim.

If a reported service lesson is corrected by verification, make that correction
visible in the artifact as `Reported Teaching -> Verified Correction -> Why It Matters`.
Do not leave the correction only as a quiet source-grounded paragraph.

### 5. Deliver The Bridge

Before persisting, show a concise de-identified teaching bridge:

- what the teaching means;
- the mechanism or reasoning chain connecting trigger to action;
- the next-shift operational takeaway;
- what remains local, patient-specific, or verification-worthy.

Do not expose memory state. Do not force calibration or verification questions during capture.

### 6. Draft And Guard The Artifact

Real target:

`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Brain Dumps/<Topic Title>.md`

Draft to:

`data/Sessions/brain_dump_<slug>.md`

For a new topic, the note must contain:

```markdown
## De-identified Teaching Trigger

## Extraction Map

## Priority Takeaways

## Reported Teaching

## Verified Bridge

## Operational Consequence

## Clarify Or Verify Locally

## Mastery Objectives

## Related In This Vault

## Sources

Each source bullet must begin with one of the evidence-type labels, for example:

- `External review: [Title](https://...)`
- `Primary study: [Title](https://...)`
- `Internal textbook RAG: Youmans and Winn, 8th ed., Vol. X, p. Y`

---
tags: [skill/brain-dump, domain/<domain>, type/reference, source/user]
generated: YYYY-MM-DD
skill: brain-dump
provenance: "<short source/service-teaching summary>"
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

The guard enforces structure and rejects common direct identifiers. It is a final safety net, not permission to feed raw identified input into tools.

### 7. Artifact-Anchor Memory Write

Log a sanitized discoverability anchor after a validated real write:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00) && \
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" \
  --topic "<canonical topic>" \
  --concept "brain dump artifact anchor" \
  --question "What service teaching was captured for <topic>?" \
  --answer "<sanitized description of the brain dump artifact>" \
  --correct 2 \
  --doc "Brain Dumps/<Topic Title>.md" \
  --skill "brain-dump" \
  --tested-claim "A de-identified service teaching artifact exists for later review." \
  --learner-claim "Teaching captured; learner performance not assessed." \
  --teaching-intent "synthesis" \
  --coverage-role "synthesis" \
  --answer-mode "after_teaching"

python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "<sanitized artifact-created summary>" \
  --next-strategy "Use study-review on Brain Dumps/<Topic Title>.md to test application of <specific clinical edge>." \
  --json
```

`brain-dump` must behave as an artifact anchor: it creates discoverability/session handoff context, but no assessed claim result, durable learner state, or curation evidence.

### 8. Optional Review Or Anki

At completion, offer either:

- immediate active review from the new note; or
- leaving the artifact for later review.

If Gabriel chooses testing, transition to doc-anchored `/study-review` using `Brain Dumps/<Topic Title>.md`. Only evaluated responses in that review count as learner evidence.

**Dedicated provenance-isolated Anki deck:** any card generated directly from `/brain-dump`, or generated while `/study-review` is anchored to a `Brain Dumps/` note, must route to:

`Neurosurgery::Brain Dumps`

Tag those cards `brain-dump` and include other appropriate tags. This deck intentionally isolates institution- and lived-experience-origin learning from textbook/report-derived topic decks.

Do not automatically card capture content. Create cards only if Gabriel requests them during capture, or if the subsequent assessed review meets the ordinary Anki-generation criteria. Do not encode a `Service teaching - locally confirm` or `Clinical knowledge - verify` high-stakes specific as settled fact.

## Completion

Surface:

- the concise teaching bridge;
- the brain-dump note path after successful install;
- whether any points remain locally confirmable or source-unverified;
- whether memory was recorded as an artifact anchor;
- card count only if cards were explicitly created or produced during active review;
- the option to begin active review now.
