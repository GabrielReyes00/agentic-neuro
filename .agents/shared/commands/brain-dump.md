# Brain Dump

The brief clinical teacher. Gabriel dumps a few items encountered on service — concepts he needs to read up on, skills he needs to become proficient in, findings he needs to interpret, decisions he needs to understand — and each item comes back as a compact teaching artifact that covers three layers:

1. **Fundamentals** — the minimum mechanism, anatomy, or principle that makes the topic make sense.
2. **Ward application** — how to actually use it at the bedside: exam steps, interpretation, orders, monitoring.
3. **Decision-making role** — how it changes management: thresholds, escalation triggers, what it rules in or out.

Every brain dump is a clinical topic in a clinical context — the wards. The artifact must teach, not merely archive. A reader should finish each teaching point able to do something tomorrow that they could not do today.

This workflow is for exposure capture, not demonstrated mastery. A senior resident correction or a self-identified weakness is valuable evidence of what Gabriel encountered; it is not evidence of what he can yet retrieve or apply.

Follow `.agents/shared/commands/learning-session-contract.md` only where this contract invokes learner testing. Use `memory-operations.md` and `memory-retrieval.md` for silent learner-context retrieval, artifact-anchor logging, atomic review-candidate logging, and optional Socratic conversion. Use `vault-intelligence.md` only as supplemental context for prior related vault notes and provenance-aware local clarifications. Use `review-artifacts.md` for the vault destination and `anki-card-quality.md` for cards generated only after evaluated answers.

## When To Use

- Explicit `/brain-dump`.
- "Capture what I learned on shift", "senior corrected me on service", "ward teaching lesson", or a debrief containing a clinical correction/lesson.
- A list of clinical topics from service that Gabriel needs to read up on, become proficient in, or be able to replicate (e.g., "spinal neuro exam and localizing pathology from the findings", "which AED to start in the ICU and when").
- A messy set of teaching fragments from the ward, ICU, OR, or sign-out that should become a useful retained mental model.

Do not use for:
- A performable bedside procedure or protocolized task needing a step-by-step brief ("how do I place/flush/troubleshoot X"): use `/consult`.
- A complex operative rehearsal: use `/intraoperative-guide`.
- A single isolated fact: answer it directly, no skill needed.
- A knowledge test or weak-spot drill: use `/study-review`.
- A comprehensive literature/reference product: use `/generate-report`.

## Success Criterion

The resident has a compact, de-identified, provenance-honest teaching note that, for each dumped item, teaches the fundamentals, shows how to apply them on the wards, and explains their role in clinical decision-making — sized to the question, not padded to a template.

## Hard Boundaries

1. **De-identify before processing or persistence.** Do not send identifiable patient details into RAG, memory entries, Anki, or the vault. Strip names, MRNs, room/bed identifiers, full dates of birth, contact details, and identifiable timelines. If de-identification would remove the educational meaning, ask for a sanitized restatement before proceeding.
2. **Teach from clinical knowledge; enrich with sources.** Draft the teaching from expert clinical knowledge first, and run RAG as a default helper tool to verify, cite, and sharpen load-bearing claims. RAG acts as additional, curatable knowledge to enrich your response. You are never restricted to RAG-only material and have full freedom to synthesize your own trusted clinical knowledge base with RAG-retrieved data, citing RAG inline whenever you use its content. Provenance must always be labeled honestly (see Step 4).
3. **Capture is not testing.** Do not create `claim_state`, open gaps, repairs, mastery, or curation evidence merely because Gabriel reports a teaching point. `/brain-dump` memory writes use `skill="brain-dump"` as an artifact anchor only.
4. **Memory remains invisible.** Topic-scoped memory may shape depth and later probe options. Never narrate stored gaps, cards, summaries, or inferred learner state to Gabriel.
5. **Do not universalize local practice.** Separate general clinical principles from institution/service conventions and patient-specific decisions.
6. **Size to the decision burden.** A narrow question gets a narrow answer (see Depth Calibration). Never pad a quick rule into pages of background; never compress a genuine skill gap into a definition.
7. **Concept promotion belongs to verified synthesis workflows.** Brain dumps preserve local and experiential provenance during capture; generalizable concepts are promoted later through report, consult, study-material, grand-rounds, or operative-guide workflows that can support a durable concept card.
8. **Atomic candidates are not mastery.** Each canonical teaching point gets a pending review candidate so it can be found later, but it becomes learner-state evidence only after a Socratic answer is evaluated.

## Workflow

### 1. Intake And Sanitization

Parse the input into one or more related teaching points. A single shift debrief may remain one artifact when its fragments share the same service encounter and the combined note stays compact; use clearly named teaching-point subsections. Create separate topic artifacts when the dump spans unrelated clinical domains, or when a fragment needs report-scale treatment rather than a concise teaching note.

Before retrieval or writing, produce an internal sanitized version. Generalize patient context to clinically necessary descriptors, for example:

- `postoperative posterior fossa patient during transport`
- `external ventricular drain with concern for pressure gradient change`

Never preserve identifying labels or a unique patient timeline.

Create a `## Clinical Focus` section at the top of the artifact, containing a direct, academic bulleted list of the clinical topics and questions covered. Keep this section limited to clinical concepts, anatomic regions, management questions, and decision points.

Immediately after the clinical focus list, add `## Priority Takeaways`: one to three short bullets ordered by learning value and next-shift consequence. This is the retention layer. It should answer, within seconds, "what should I remember or change tomorrow?"

### 2. Depth Calibration

Before drafting, classify each teaching point. The classification controls how much artifact it gets:

- **Quick rule** — the gap is a discrete fact, threshold, or drug choice ("what AED do I order in the ICU and when"). Output: a few lines — the rule, when it applies, the one mechanism sentence that makes it stick, and the trap to avoid. No anatomy review, no history of the field.
- **Working understanding** — the gap is a skill or reasoning chain ("perform the spinal neuro exam and localize pathology from the findings"). Output: the full three-layer treatment — fundamentals, ward application, decision-making role — still compact, organized for use rather than coverage.
- **Refer out** — the gap genuinely needs report-scale or operative-guide-scale treatment. Teach the working core here, then recommend the follow-on workflow explicitly in the completion summary. Do not attempt the deep product inside the brain dump.

Anti-pattern (BAD): Gabriel asks which antiepileptic to order in the ICU and receives ten pages covering seizure pathophysiology, EEG classification, and the history of phenytoin.
Pattern (GOOD): four lines — agent of choice and dose context, when prophylaxis is indicated vs. not, the high-yield trap, and a verify flag on the numerics.

### 3. Silent Memory Context

Retrieve the learner's document memory using the document-anchored `startup-recall` command from `memory-operations.md` to initialize context.

Read `planning_brief`, `counts`, `omitted`, and `retrieval_guidance` per `memory-retrieval.md`; expand with `--profile audit` only if the compact brief is ambiguous or safety-critical context is missing. Use this context to choose explanation depth and future review suggestions. Do not state what memory returned.

If the dump names a service/site-specific practice and an active service context is needed, resolve the rotation and use `startup-recall --lens service` from `memory-operations.md` for local memory.

### 4. Teach First, Then Enrich With Sources

**Draft the teaching from expert clinical knowledge.** Decide what each teaching point needs (per its depth class) and outline it before running any retrieval. Retrieval then verifies and enriches the outline — it never writes it.

Query vault intelligence for related prior context when it can improve synthesis or provenance handling:

```bash
python3 src/vault_retriever.py recall "<sanitized teaching topic>" --task service-local --limit 5
```

Use this to find prior local clarifications, operational mental models, and related Brain Dumps/Consults. Do not use vault retrieval to universalize local practice.

Run focused RAG queries for the load-bearing claims of each teaching point — management-changing claims, mechanisms, thresholds, anatomy or physiology claims:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "<focused verification query>" --stdout [--no-frontier]
```

Run one focused query per load-bearing claim when necessary; do not execute a report-scale retrieval campaign.

**Relevance gate — judge every retrieval before using it.** After each query, ask: do these passages address *this specific clinical question*, or are they merely about the surrounding topic? A passage defining what a neurologic exam is does not support teaching how to localize a spinal lesion from exam findings. If retrieval is generic, adjacent, or off-target:

- Discard it. Do not quote, summarize, or cite it to fill space.
- Teach the point from clinical knowledge with honest provenance labels (below).
- Never let weak retrieval shrink, redirect, or pad the teaching.

Anti-pattern (BAD): asked about localizing spinal pathology from the neuro exam, the agent retrieves generic "components of the neurological examination" passages, summarizes them into a description of what a neuro exam is, and ships that as the artifact.
Pattern (GOOD): the agent teaches tract-by-tract localization — which findings lateralize, which level, UMN vs. LMN signs, sensory level mapping — citing retrieved passages only where they genuinely support a claim, and labeling the rest as clinical knowledge.

**Provenance tiering — confident, and honest about what to verify:**

- **Source-grounded** — supported by a retrieved passage that is actually about this condition. Cite it inline, e.g. `(Youmans & Winn, 8th ed., Vol. 5, p. 331)` or `(Yoo et al., 2019)`. Never transfer a related condition's statistic and attach a real citation to it.
- **Clinical knowledge — verify** — standard practice not located in retrieved passages. State it confidently and plainly, but never attach a citation to it, and never invent one. Flag high-stakes specifics — drug/dose/route, physiologic thresholds, correction-rate ceilings, time windows — with `⚠ verify` so the resident double-checks before acting.

If the reported teaching from service was incorrect or incomplete, resolve it directly in the text, e.g., *"Although reported as a preference for posterior correction, approach selection is actually driven by..."*.

**Medication & high-stakes support:** medication, postoperative order, threshold, and operative-strategy claims have a higher source standard. Actively look for at least one `Guideline/formal guidance` or `Primary study` source. When that support is unavailable after a focused search, keep the teaching (with `⚠ verify` flags) and record the limitation in `## Institutional & Local Clarifications`.

### 5. Clinical Teaching Section

The body of the artifact is a `## Clinical Teaching` section with one `### <Teaching Point Title>` subsection per teaching point. Each subsection delivers its depth-calibrated treatment in a professional but direct teaching voice — a senior resident at the workstation, not a textbook chapter.

For **working-understanding** points, your explanation should cover three core cognitive dimensions to ensure high educational value, though you are free to format them using headings, bold prefixes, tables, lists, or structured prose as you see fit:
1. **Fundamentals:** The essential mechanism, anatomy, or principle needed to grasp the topic. Keep it concise.
2. **Ward Application:** The operational bedside practice—how to perform, interpret, order, or monitor.
3. **Decision-Making Role:** How this changes management—physiologic thresholds, escalation triggers, what it rules in/out, or next moves.

Select the layout that makes the clinical logic most digestible and readable at a glance. For **quick-rule** points, compress these elements into a brief, high-yield summary without forcing any scaffold.

### 6. Operational Mental Models

Create an `## Operational Mental Models` section.
- Operational mental models must serve as powerful cognitive hooks, spatial analogies, or biomechanical/anatomical decision trees (e.g., the *Coaxial Cylinder Model* for paraspinal layers, or the *Sagittal Balance Decision Tree*).
- Prefer perspectives or reframes that make the material durable: spatial analogies, biomechanical decision trees, layered anatomy models, escalation thresholds, or causal chains.

### 7. Institutional & Local Clarifications

Create an `## Institutional & Local Clarifications` section. Group all service preferences, local protocols, attending-specific variations, or unresolved clinical uncertainties here as points to verify at the point of care. Record here any high-stakes claim that could not find guideline/primary support after a focused search.

### 8. Draft And Guard The Artifact

Real target:

`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Brain Dumps/<Topic Title>.md`

Draft to:

`data/Sessions/brain_dump_<slug>.md`

For a new topic, the note must contain:

```markdown
## Clinical Focus

## Priority Takeaways

## Clinical Teaching

### <Teaching Point Title>

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

When no retrieval passed the relevance gate and the teaching is entirely clinical knowledge, do not fabricate references. Instead the References section must contain exactly:

- `No source-grounded references; teaching from clinical knowledge. Verify high-stakes specifics at the point of care.`

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

`internal_knowledge_used` must be `true` whenever any teaching content is clinical knowledge rather than source-grounded — which is the common case. Setting it `false` asserts every claim is source-grounded and cited.

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

### 9. Artifact-Anchor Memory Write

Log a sanitized discoverability anchor using `study_memory.py log-answer` (with `skill="brain-dump"`) and close with `study_memory.py end-session` per `memory-operations.md`.

`brain-dump` behaves as an artifact anchor: it creates discoverability/session handoff context, but no assessed claim result, durable learner state, or curation evidence.

### 10. Atomic Review Candidates

After the artifact-anchor write, log one pending review candidate per canonical teaching point using the `brain-dump-candidate-add` command from `memory-operations.md`. Use portable `origin=assessed` for general clinical knowledge and `origin=service` only for site/service-specific conventions or service-origin operational habits (requiring an active rotation).

These candidates power later reviews. They must not create Anki cards or curation evidence during initial capture.

### 11. Optional Socratic Review Or Anki

At completion, offer the option to run an immediate active Socratic lesson. End the response with exactly: `Do you want to complete a quick Socratic lesson on these items?` If Gabriel chooses testing, ask one Socratic question at a time. For each evaluated answer, run `log-answer` with `--brain-dump-candidate-id <id>` (per `memory-operations.md`) so the pending candidate is marked reviewed and linked to the resulting claim state.

**Dedicated provenance-isolated Anki deck:** any card generated directly from `/brain-dump`, or generated while `/study-review` is anchored to a `Brain Dumps/` note, must route to:

`Neurosurgery::Brain Dumps`

Tag those cards `brain-dump` and include other appropriate tags. This deck intentionally isolates institution- and lived-experience-origin learning from textbook/report-derived topic decks.

Do not create cards during initial capture. Create cards only after evaluated Socratic turns meet the ordinary Anki-generation criteria. Portable Brain Dump-derived cards route to `Neurosurgery::Brain Dumps`; site-local service conventions route to `Neurosurgery::Service Learning` (with `service-learning`, `service/<service>`, and `site/<site>` tags) and must not encode local practice as a universal rule.

## Completion

Surface:

- the concise teaching summary per teaching point;
- the brain-dump note path after successful install;
- whether any points remain locally confirmable, `⚠ verify`-flagged, or source-unverified;
- any teaching point classified refer-out, with the recommended follow-on workflow;
- whether memory was recorded as an artifact anchor;
- how many pending atomic review candidates were logged;
- card count only if cards were produced during active Socratic review;
- the Socratic lesson prompt.
