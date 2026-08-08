# Grand Rounds Case Mode

Build a deidentified, educational neurosurgical case presentation. This module
preserves the established case workflow while the article workflow is sourced from
Journal Club dossiers.

## Intake

Accept one generous dump rather than a form:

```text
HPI, examination, imaging descriptions or paths, differential, decision point,
alternatives, operative plan, intraoperative findings, postoperative course,
complications, outcome, why the case was selected, and available visuals.
```

Parse silently. Scrub names, MRNs, DOBs, exact dates, room numbers, contacts, and
unnecessary identifiers before any workflow artifact. Use relative timing.

## Enrichment

Use field-aware vault recall and focused textbook RAG only when it improves the
teaching thesis, anatomy, management alternatives, evidence, or anticipated
faculty questions. The supplied case remains primary. Never invent missing case
facts. When textbook retrieval is useful, load
`.agents/shared/commands/rag-routing.md` and use its smallest sufficient tier.

## Title And Gap Probe

Use a supplied title. Otherwise infer one concise, professional, PHI-free title
and proceed; offer alternatives only when naming is genuinely ambiguous. Ask one
grouped gap probe for missing must-haves. A second probe is allowed only after
meaningful new material; never exceed two.

## Required Case Content

- Why the case is educational
- Presentation and focused examination
- Imaging/workup sequence
- Differential and decisive fork
- Alternatives considered
- Operative/anatomic or management consequence
- Intervention and intraoperative findings
- Postoperative course, outcome, and complications
- Teaching points
- Anticipated faculty questions
- What the presenter should not overclaim

## Case Slide Grammar

Adapt to duration:

1. Opening hook and reason selected
2. Presentation and focused examination
3. Imaging/workup sequence
4. Differential and decision point
5. Alternatives and rationale
6. Operative anatomy or intervention
7. Outcome and complications
8. Teaching points and transfer
9. Anticipated questions or backup slides

Use supplied clinical imaging when available. Do not retrieve or generate patient
imaging. When an image is absent, use an explicit placeholder and asset manifest
entry rather than fabricating it.

## Case Quality Gate

- No PHI or exact identifiers.
- The decision point and alternatives are explicit.
- Imaging descriptions match supplied images.
- Operative claims are supported by the case record.
- Outcomes and complications are not omitted.
- Missing must-haves appear as presentation risks and anticipated questions.
- No slide overstates generalizability from one case.

Then follow `grand-rounds-deck.md`, validate with `grand_rounds_guard.py`, and
write the note through `grand_rounds_writer.py`.
