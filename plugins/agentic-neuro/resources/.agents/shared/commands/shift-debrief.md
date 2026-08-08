# Shift Debrief

Turn de-identified service teaching, a senior correction, or a self-identified
ward gap into a compact clinical note that changes what Gabriel can recognize or
do on the next shift. Capture is exposure, not demonstrated mastery.

Use this workflow for `/shift-debrief`, “capture what I learned,” ward/ICU/OR
teaching fragments, and the artifact half of `/service-log`. Use Consult for an
immediate bounded task, Intraoperative Guide for full operative rehearsal,
Study Review for testing, and Generate Report for comprehensive reference work.

Follow the shared learning modules only if active testing begins. Memory,
retrieval, artifact, and Anki mechanics remain owned by
`memory-operations.md`, `memory-retrieval.md`, `vault-intelligence.md`,
`review-artifacts.md`, and `anki-card-quality.md`.

## Hard Boundaries

- De-identify before retrieval or persistence. Remove names, MRNs, rooms/beds,
  dates of birth, contact details, and unique timelines. If sanitization destroys
  the teaching value, request a sanitized restatement.
- Separate portable knowledge from institution, service, and attending-specific
  practice. Never universalize a local convention.
- Initial capture creates no mastery, gap, repair, curation, or Anki evidence.
- Scale depth to decision burden; do not pad a quick rule into a chapter or
  compress a real reasoning gap into a definition.
- Artifact-only smoke tests skip every learner-memory, concept, and Anki write.

## 1. Intake And Depth

Split unrelated domains into separate notes. Related fragments from one service
context may share a note when the result remains coherent. Internally sanitize
patient context before any tool call.

Classify each teaching point:

- **Quick rule:** rule, applicability, one mechanism sentence, and main trap.
- **Working understanding:** fundamentals → ward application → decision-making
  consequence.
- **Refer out:** teach the immediate working core, then recommend the matching
  deeper workflow.

## 2. Prior Context And Evidence

For ordinary generation, use topic-scoped `startup-recall` from
`memory-operations.md`; do not pretend an uninstalled draft is a document. When
the lesson is site/service-specific, resolve the active rotation and use
`startup-recall --lens service`. Learner context silently calibrates teaching
depth and never removes necessary content.

Recall related vault context only when it can add a prior local clarification,
durable mental model, or useful crosslink:

```bash
python3 src/vault_retriever.py recall "<sanitized topic>" --task service-local --limit 5
```

Outline the clinical teaching first. Then load
`.agents/shared/commands/rag-routing.md` only for load-bearing claims where
retrieval materially improves accuracy or provenance. Use Mini-RAG for named
references; use scalar or batched full RAG for true synthesis. Current primary
guidance is required for evolving conduct-changing doses, timing, thresholds,
devices, or controversies.

Discard generic or adjacent passages. Label content honestly:

- **Source-grounded:** cite the source that supports the actual claim.
- **Clinical knowledge — verify:** uncited synthesis; mark high-stakes specifics
  `⚠ verify` until checked.
- **Local convention:** place in Institutional & Local Clarifications with site
  or service provenance and a point-of-care confirmation cue.

If focused verification finds no suitable support, retain only the safe working
principle, mark the limitation, and do not invent a citation.

## 3. Artifact

Draft to `$RUN_DIR/draft.md`; install to:

`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Shift Debriefs/<Topic Title>.md`

Use native frontmatter and no H1:

```yaml
---
artifact_type: shift-debrief
status: current
domain: neurocritical-care
summary: One-line description of the retained teaching.
aliases: []
tags: [skill/shift-debrief, domain/neurocritical-care, type/reference, source/user]
generated: YYYY-MM-DD
skill: shift-debrief
provenance: Sanitized service-teaching context.
internal_knowledge_used: true
---
```

Required body:

```markdown
## Clinical Focus
## Priority Takeaways
## Clinical Teaching
### <Teaching Point>
## Operational Mental Models
## Institutional & Local Clarifications
## Mastery Objectives
## Related In This Vault
## References
```

Clinical Focus is a concise topic list. Priority Takeaways contains one to three
next-shift consequences. Clinical Teaching uses the depth selected above.
Operational Mental Models contains only a genuinely useful causal, spatial, or
decision model. Mastery Objectives are future assessment targets, not mastery
claims. Do not fabricate crosslinks or references. When no source passed the
relevance gate, state that the teaching uses clinical knowledge and identify
what high-stakes claims still need verification.

If the target exists, read it completely and merge new teaching into the
canonical sections. Add a dated encounter subsection only when the encounter
adds meaningful new context; do not accumulate duplicate summaries.

Install and validate through the guard:

```bash
python3 src/shift_debrief_guard.py install --draft "$RUN_DIR/draft.md" --title "<Topic Title>"
python3 src/shift_debrief_guard.py validate "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Shift Debriefs/<Topic Title>.md"
```

Parse guard output silently. A pass confirms structure and basic identifier
screening; it does not make raw patient input safe.

## 4. Memory And Optional Review

Unless artifact-only smoke-test mode is active:

1. Log one sanitized artifact anchor with `skill="shift-debrief"`, then close the
   capture session through `end-session`. The anchor is discoverability context,
   not an assessed claim.
2. Run `shift-debrief-candidate-add` once per canonical teaching point. General
   portable teaching uses `--origin assessed`; local practice uses
   `--origin service`, the active rotation, and `--convention` when applicable.
   Candidates remain pending and do not alter mastery.
3. Offer an immediate Socratic review in natural language. Do not require a
   canned closing sentence.

If Gabriel accepts, ask one question at a time. Each evaluated answer uses
`log-answer --shift-debrief-candidate-id <id>`. Only eligible evaluated answers
may create Anki cards. Portable cards use `Neurosurgery::Shift Debriefs` and tag
`shift-debrief`; local convention cards use `Neurosurgery::Service Learning`
with service/site tags and wording that preserves the local boundary.

Novel concept extraction is optional after validation and follows
`concept-extraction.md`; zero promotions is valid. Never promote a merely local
convention into a universal concept.

## Completion

Report the concise teaching result, installed path, verify/local limitations,
refer-out recommendations, artifact-anchor status, pending-candidate count, and
cards only if evaluated review actually produced them. Offer Socratic review
without implying the artifact established mastery.
