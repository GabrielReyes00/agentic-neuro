# Grand Rounds

Build a professional, editable neurosurgery PowerPoint for grand rounds, case
conference, or journal club. This file is the thin orchestration authority; load
only the mode-specific modules needed for the current request.

## Mode Router

Supported invocations:

```text
/grand-rounds --mode case [--case-log "<path>"] [--duration <minutes>]
/grand-rounds --mode article --journal-club "Journal Club/<Title>.md" \
  [--duration <minutes>] [--template "<reference.pptx>"] [--focus "<angle>"]
/grand-rounds --mode article --pdf "<article.pdf>" [--duration <minutes>]
```

- **Case mode:** read `.agents/shared/commands/grand-rounds-case.md`.
- **Article mode:** read `.agents/shared/commands/grand-rounds-article.md`.
- **Every deck:** read `.agents/shared/commands/grand-rounds-deck.md` and
  `.agents/shared/commands/grand-rounds-visual-design.md` before authoring or
  editing PowerPoint.
- **Related-vault discovery:** follow
  `.agents/shared/commands/vault-intelligence.md` and use its field-aware context
  only as supplemental crosslink and prior-artifact context.
- **Only after rehearsal is accepted:** read
  `.agents/shared/commands/grand-rounds-rehearsal.md` and the learning modules it
  names.

If mode cannot be inferred, ask only whether this is a case or article
presentation. Do not preload both mode modules.

## Shared Posture

1. **The presentation has a thesis.** Organize slides around why the case or
   article matters, not around the order in which source material was supplied.
2. **Slides serve the audience; notes serve the presenter.** Visible content is
   concise and technically precise for neurosurgeons. Speaker notes give the
   resident the explanation, transition, exact quantitative anchors, and faculty
   defense needed to deliver it.
3. **PowerPoint is a required artifact.** A Markdown outline is not a completed
   presentation.
4. **Visuals carry evidence.** Prefer provided imaging, article figures, exact
   editable tables, and source-backed charts over decorative imagery.
5. **Human presentation economy wins.** Merge or delete slides that merely
   repeat a prior result or could be one label on a parent slide. End every deck
   with a brief evidence-based `Summary` or `Main Takeaways` slide that recaps
   the study population, decisive result, validity boundary, and clinical
   application without introducing new evidence. Use restrained departmental
   typography and color rather than card grids, callout boxes, or dashboard-style
   compositions. Economy means compressing related evidence, not omitting content
   needed to interpret the study population, comparator, longitudinal results,
   validity, or clinical scope.
   For Gabriel's journal-club decks, default to the Baylor minimal academic
   surface defined in `grand-rounds-visual-design.md`: white canvas, one navy
   accent, neutral chart furniture, and open unboxed evidence layouts.
6. **No invented data or images.** Preserve missing information, uncertainty,
   denominators, axes, and article inconsistencies.
7. **Artifact is not mastery.** Deck generation writes no learner-state evidence
   and creates no Anki cards. Evaluated rehearsal may do so.
8. **Protect privacy.** Case materials must be deidentified before any outline,
   manifest, deck, or vault write.

## Output Contract

Final outputs:

```text
/Users/gabrielreyes/Desktop/<Title>.pptx
/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Presentations/Cases/<Title>.md
/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Presentations/Articles/<Title>.md
data/Sessions/grand_rounds_<slug>_manifest.json
```

Use the confirmed title without dates, workflow prefixes, or version suffixes.
For an existing validated Journal Club dossier, its short title is already
confirmed; do not stop for a three-title gate unless the user requests a renamed
talk. For new case presentations, propose three titles after intake.

Default to 15 minutes when duration is absent and no surrounding assignment
implies another length. Record the assumption rather than blocking.

## Shared Phases

1. Route the mode and resolve sources.
2. Retrieve related vault context silently when useful:

   ```bash
   python3 src/vault_retriever.py recall "<presentation topic>" --task presentation-generation --limit 8
   ```

   Treat this as personalized supplemental context, not source evidence or a
   substitute for the case record, Journal Club dossier, or article PDF.
3. Build the mode-specific evidence or case map.
4. Define thesis, audience takeaway, and time budget.
5. Build a slide plan and coverage ledger.
6. Acquire, extract, or create only allowed visual assets.
7. Generate an editable PPTX using the runtime's supported presentation tooling.
8. Render and inspect every slide; repair content and visual failures.
9. Run `src/grand_rounds_guard.py` on the real deck package.
10. Write the presentation note with `src/grand_rounds_writer.py` only after the
   package passes.
11. Offer optional rehearsal once.

## Agent Compatibility

Keep reasoning and output requirements agent-agnostic. Each runtime must use its
supported editable PowerPoint implementation. Codex must use the installed
Presentations skill and its current artifact-tool workflow; never use
`python-pptx` to author slides. Python may inspect OOXML in deterministic guards.

## Completion Standard

Do not claim completion until:

- The final `.pptx` exists and opens as a valid PowerPoint package.
- Every slide was rendered and visually inspected at useful resolution.
- No clipping, unintended overlap, unresolved placeholder, illegible table, or
  unsupported quantitative claim remains.
- Speaker notes are present on every substantive slide.
- Sources and visual assets are traceable.
- The mode-specific content gate passes.
- `grand_rounds_guard.py` reports `ok: true`.
- The presentation note and index were written successfully.

## Failure Boundaries

- **Article without a full PDF:** a preliminary outline may be produced, but not
  a source-complete final deck with article figures.
- **Unusable visual extraction:** use a clearly sourced full figure or editable
  reconstruction from exact values; never approximate silently.
- **PPTX tooling failure:** preserve the plan and manifests, report the blocker,
  and do not label the presentation complete.
- **Guard or render failure:** repair and rerun; do not delegate QA to Gabriel.
