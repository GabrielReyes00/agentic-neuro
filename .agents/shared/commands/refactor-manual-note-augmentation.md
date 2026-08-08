# Refactor Manual Note Augmentation

Load this module only when `answer`, `expand`, `verify`, or `distill` is active.
The source note remains the primary authored artifact. The completed note should
read as one coherent body of knowledge, not a transcript of what the learner
wrote and what an agent later supplied.

## Invocation

Treat the following as equivalent mode requests:

- `answer` or `--answer`
- `expand` or `--expand`
- `verify` or `--verify`
- `distill` or `--distill`

The modes may be combined in one run. Interpret an optional `audience`, `depth`,
or `focus` whether supplied as natural language or as `key=value`.
`depth=focused` is the default; use comprehensive expansion only when explicitly
requested. If no audience is supplied, calibrate the note for a neurosurgery
resident progressing toward board-ready and senior-resident reasoning. State
that inference in the completion report rather than stopping for confirmation
unless a different audience would materially change safety or scope.

Audience controls vocabulary, assumed prerequisites, explanatory depth, and
application. It never changes the underlying facts or evidence standard.

## Question Marker Grammar

An answerable author question has the exact form `[? question text]`. Detect it
before reorganizing the note. The marker may occur inline or on its own line,
must have balanced brackets, and may not contain another marker.

Do not interpret ordinary bracketed content as an author question. In
particular, ignore `[[wikilinks]]`, `![[embeds]]`, `[link labels](URLs)`,
citations, task boxes such as `[ ]` or `[x]`, and bracketed editorial text that
does not begin with `?`.

With `answer` active, resolve every unambiguous `[? ...]` marker in the full
note. With `answer` inactive, preserve all markers verbatim. Never infer hidden
questions merely because a sentence is incomplete or uncertain. If `answer`
finds no markers, perform the base refactor and report zero questions; do not
invent questions to justify the mode.

## Answer Workflow

For each marker:

1. Read the surrounding paragraph, section, note title, and relevant figures so
   the answer addresses the intended entity and level.
2. Classify the need as a compact fact, spatial relationship, mechanism,
   comparison, or conduct-changing clinical question.
3. Use the smallest sufficient retrieval route in `rag-routing.md`. Verify
   current management, thresholds, timing, outcomes, or controversy with
   current primary guidance; local notes and textbook retrieval are not enough
   for those claims.
4. Answer the question directly, then add only the mechanism, discriminator,
   management consequence, or memory cue that materially improves
   understanding.
5. Remove the marker and rewrite the surrounding prose so the answer, its
   context, and its consequence read as a natural part of the section. Merge
   with existing coverage instead of repeating it. Open an ordinary subject
   heading only when the answer introduces a genuinely new subtopic.

Do not preserve the question, the reason it was asked, or an answer-specific
container merely to expose provenance. Do not label content as `AI`,
`Clarification`, `Question`, `Answer`, or `Why it matters`. Cite supporting
evidence in the same normal scholarly style used elsewhere in the note.

If context cannot disambiguate the entity or the evidence is insufficient, do
not guess or invent connective prose. Preserve the original `[? ...]` marker in
place and report the exact ambiguity as unresolved.

## Expansion Workflow

Expansion is selective gap repair, not permission to produce a generic
encyclopedia entry.

1. Infer the note's durable purpose and outline what it already teaches.
2. Build a private coverage map appropriate to the topic. Consider only useful
   axes: anatomy or physiology, governing mechanism, spatial relationships,
   classification, discriminators, natural history, diagnostic interpretation,
   management consequence, complications, edge cases, and transfer to a new
   context.
3. Rank missing material by learning impact, relevance to the target audience,
   safety, and nonredundancy. Add the smallest set that changes understanding or
   future performance. Do not pad every axis.
4. Retrieve each independent gap with the smallest sufficient route in
   `rag-routing.md`; batch independent synthesis questions. Use current primary
   sources for conduct-changing clinical claims.
5. Integrate additions into the most specific existing sections. Open a new
   heading only for a genuinely new subject. Preserve the note's narrative and
   visual order; do not append a detached "AI expansion" dump.
6. Match the medium to the concept. Prefer prose for explanation, a comparison
   or spatial table for repeated fields, Mermaid for a genuine mechanism or
   decision branch, and a warning callout for a dangerous exception. Do not add
   a visual merely to decorate the note.

`focus` narrows eligible gaps but does not authorize unrelated breadth.
`depth=focused` favors a few consequential additions. A comprehensive request
may widen coverage, but must still deduplicate and preserve the source note's
identity rather than silently converting it into a different artifact type.

## Verification Workflow

`verify` authorizes factual correction. It does not authorize unrelated
expansion.

1. Inventory the note's factual claims and prioritize anatomy or spatial
   relationships, definitions and classifications, quantitative values,
   diagnostic discriminators, operative hazards, management thresholds, timing,
   reversal, outcomes, and disputed practice.
2. For a short or moderate note, check every externally verifiable claim. For a
   long note, verify all conduct-changing and high-consequence claims, then a
   representative set of stable background claims; report the actual coverage
   rather than claiming an exhaustive audit.
3. Use the smallest sufficient route in `rag-routing.md`. Stable anatomy and
   established frameworks may use textbook evidence. Current thresholds,
   timing, outcomes, guidelines, and controversies require current primary
   sources or authoritative guidance.
4. Reconcile entity, population, context, units, laterality, and time point
   before accepting support. A nearby or generally related source does not
   verify the claim.
5. Correct inaccurate or overbroad statements directly in the durable prose.
   Preserve the learner's intended subject and explanation, not an erroneous
   sentence for historical traceability. State material corrections in the
   completion report rather than adding correction boxes to the note.
6. Express guideline, common-practice, local-practice, and controversy status
   naturally where the distinction changes interpretation or conduct.

If a claim cannot be verified, retain its uncertainty or qualify it explicitly.
Never convert missing evidence into confident prose.

## Distillation Workflow

`distill` changes information architecture, not the evidence base. Do not
research new facts solely to make a summary sound complete.

1. Identify the note's governing mental model, essential relationships,
   discriminators, consequences, and dangerous exceptions.
2. Remove redundant statements and compress verbose phrasing while preserving
   unique detail, uncertainty, citations, and attachments.
3. Create or refine one compact `## Rapid Review` section immediately after the
   frontmatter when the note is substantial enough to benefit. It should let the
   learner reconstruct the topic in roughly one minute using a concise synthesis
   plus only the highest-yield bullets, sequence, or comparison.
4. Do not make `Rapid Review` a duplicate table of contents or repeat every body
   heading. If an existing opening summary already performs this job, improve it
   in place rather than adding another section.
5. Keep full explanations in their subject sections. Distillation must create a
   layered reading path, not replace the durable note with a cheat sheet.

## Authorship, Correction, And Evidence

- Use stable textbook references or linked primary sources near supported
  claims; consolidate a short `## Sources` section only when that is clearer.
  Citations support the unified note and should not label which sentences came
  from the learner versus retrieval.
- Preserve existing citations and reuse an existing references section instead
  of creating a parallel one. Never fabricate a page, DOI, PMID, title, URL, or
  evidentiary strength.
- Treat vault recall as supplemental context and crosslink discovery, not proof
  of a factual claim. Absence from the vault never narrows the expansion.
- If reliable evidence conflicts with the draft, correct the durable prose and
  cite the corrected relationship. Do not add a warning, correction log, or
  separate block solely to distinguish old wording from new wording.
- Mark genuine uncertainty, local practice, and controversy explicitly. Do not
  upgrade attending preference or local convention into a universal rule.
- Deduplicate `answer` and `expand` work. When both modes are active, resolve
  marked questions first, then omit expansion material already covered by an
  answer.
- When several modes are active, apply them in this order: answer, expand,
  verify, then distill. Each later pass operates on the integrated result.

Before saving, compare the augmented note to the original and confirm that all
author-authored points, uncertainties, embeds, and question intent remain
represented; every new claim has adequate support; and the additions are
calibrated to the requested audience and scope.
