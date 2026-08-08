# Consult

Resolve a bounded clinical question, performable bedside task, or immediate
decision with an action-first answer shaped to the problem. Consult is not a
generic trigger for every question containing “manage” or “how.” Root Clinical
Answer Doctrine decides the route from scope and urgency.

## Modes

### Answer-only (default)

Use for natural-language bedside questions and immediate decisions. Give the
safe, useful answer now. Do not create a vault note, learner-memory session,
Anki card, or concept card merely because the consult workflow routed the
question here.

### Durable capture

Use when Gabriel explicitly invokes `/consult`, asks to save/capture the answer,
or accepts a post-answer offer to retain it. Durable capture may write a pocket
card and may start an evaluated learning exchange. Artifact generation alone is
not mastery.

Never delay urgent guidance in order to ask which mode the user wants. Answer
first; offer capture afterward when it would be useful.

## Boundaries

- Broad disease-management teaching remains ordinary clinical Q&A under the
  root doctrine.
- A request to build durable proficiency from a service lesson belongs to
  Shift Debrief.
- Complex operative rehearsal belongs to Intraoperative Guide.
- De-identify patient material before retrieval, memory, Anki, or persistence.
- State when the safe answer depends on local policy, attending preference,
  patient-specific physiology, or unavailable data.

## Answer Shape

Choose the smallest shape that resolves the problem. Do not force every answer
into all sections.

### Procedure or bedside task

1. Immediate setup and safety checks
2. Ordered steps with landmarks or equipment
3. Expected endpoint or confirmation
4. Failure modes and troubleshooting
5. Stop/escalation criteria

### Decision or indication

1. Operational bottom line
2. Variables that change the branch
3. Thresholds, contraindications, or failure criteria
4. Alternatives and escalation
5. Patient-specific or local uncertainties

### Immediate management problem

1. Next safe priorities
2. Stabilization and monitoring
3. Diagnostic framing
4. Definitive and fallback paths
5. Reassessment trigger

Teach the causal bridge behind the recommendation: mechanism or anatomy →
observed behavior → management consequence. Surface the few errors a junior
resident is most likely to make and how to recognize them next time.

Ask a verification question only when the answer cannot be safely applied
without missing information. Otherwise provide the answer and list the specific
facts that must be confirmed. Do not make the user pass a quiz before receiving
time-sensitive guidance.

## Evidence

Load `.agents/shared/commands/rag-routing.md` only when textbook retrieval would
materially improve the answer. Named scales and compact references use Mini-RAG;
one synthesis uses scalar full RAG; several independent syntheses use one batch.

Current primary guidelines, society statements, or primary literature are
required for evolving conduct-changing thresholds, doses, timing, reversal,
devices, and controversies. Distinguish:

- guideline or standard;
- widely accepted practice;
- institution- or attending-dependent practice;
- genuine controversy.

Discard generic or adjacent retrieval. Never attach a citation to a claim the
source does not support. If a high-stakes specific remains unverified, mark it
`⚠ verify` and say what source or local policy must be checked.

Use vault recall under `.agents/shared/commands/vault-intelligence.md` only when
prior personal context may improve the answer:

```bash
python3 src/vault_retriever.py recall "<bounded question>" --task consult --limit 5
```

Vault context is supplemental and never overrides formal evidence silently.

## Durable Pocket Card

When durable capture is active, write or merge:

`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Consults/<Topic Title>.md`

Read an existing note completely before revising it. Preserve user-authored
material and merge the new rule into the canonical section it belongs to.
Append a dated encounter subsection only when the encounter adds genuinely new
context or a local clarification; do not accumulate duplicate answers.

The note uses native top frontmatter and no H1:

```yaml
---
artifact_type: consult
status: current
domain: neurocritical-care
summary: One-line operational description.
aliases: []
tags: [type/consult, domain/neurocritical-care]
provenance: Brief description of source mix.
internal_knowledge_used: true
---
```

Use canonical sections when applicable:

```markdown
## Operational Bottom Line
## Decision Or Procedure
## Failure Modes And Escalation
## Local Or Patient-Specific Clarifications
## Mastery Objectives
## Related In This Vault
## References
```

Do not create empty headings or fabricate a wikilink to satisfy structure.
Regenerate `Consults/INDEX.md` through `src/index_builder.py Consults` after a
successful write.

## Learning, Memory, And Anki

Answer-only mode performs no learner-memory or Anki writes.

In durable mode, begin a topic-scoped learner session only if Gabriel accepts an
interactive verification or teaching exchange. Log assessed answers through
`memory-operations.md`; use the same session timestamp through `end-session`.

Create Anki cards only from evaluated misses, unstable thresholds, corrected
dangerous rules, or durable transfer-worthy discriminators. Follow
`anki-session-workflow.md` and `anki-card-quality.md`. Never generate a passive
quota of cards from the pocket card itself.

Run concept extraction after a durable write only when the artifact introduces
a genuinely novel, reusable concept. Zero new concept cards is a valid result.

## Completion

For answer-only mode, finish with the reusable bottom line and the most
important verification or escalation cues.

For durable mode, additionally report the installed/updated note path, any
remaining verify flags, and counts from evaluated memory/Anki work if such work
actually occurred. Never represent artifact creation as learner mastery.
