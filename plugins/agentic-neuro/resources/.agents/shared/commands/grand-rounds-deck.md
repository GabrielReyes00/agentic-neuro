# Grand Rounds Deck Artifact

Shared PowerPoint build, source, and package contract for every
`/grand-rounds` mode.

## Required Modules

Before planning slides:

1. Read the selected case or article module.
2. Read `.agents/shared/commands/grand-rounds-visual-design.md` completely.
3. For Codex, read the installed Presentations skill completely, including its
   content-quality rules and the selected layout references.

The visual-design module owns art direction, typography, composition, rhythm,
and rendered-deck critique. This file owns the build package, evidence handling,
and deterministic completion gate.

## Workspace And Output

Use the current runtime's presentation workspace rules. Keep build code,
extracted assets, previews, layout data, and QA ledgers outside the repository
when the runtime requires external scratch. Persist only the compact recovery
manifest under `RUN_DIR`.

Final PowerPoint, stored with its durable vault lineage:

```text
/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Presentations/Decks/Cases/<Title>.pptx
/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Presentations/Decks/Articles/<Title>.pptx
```

Use the `Cases` path for case mode and the `Articles` path for article mode.

For Codex, use `@oai/artifact-tool` from a plain JavaScript ES module. Do not
author with `python-pptx`.

## Source-First Deck Plan

Create `deck_plan.json` before authoring. Its schema is
`grand_rounds_deck_plan_v2` and it is the source of truth for rebuilds. Fix the
plan or build source and regenerate; do not patch the exported PPTX when source
is available.

The plan includes:

- Mode, title, audience, duration, thesis, and source fingerprints.
- `style_profile`: `editorial_academic`, `custom_directed`, or
  `template_faithful`.
- The complete `design_brief` required by the visual-design module.
- `surface_style` and `human_style_constraints` when the Baylor minimal academic
  surface is selected.
- `reference_alignment` when a local human-edited exemplar is available: the
  inspected deck path, adopted patterns, and rejected weaknesses.
- Coverage and quantitative-result checks.
- For article mode, the complete `coverage_audit`: required evidence dimensions,
  critical-item dispositions, longitudinal-result coverage, companion evidence,
  and unresolved coverage risks.
- Ordered slide nodes with the fields below.

Every slide node contains:

- `id`
- `title`
- `job`
- `role`
- `layout_family`
- `visual_anchor`
- `visual_coverage`
- `background_tone`
- `visible_content`
- `speaker_notes`
- `source_sections`
- `citations`
- `assets`
- `timed_seconds`
- `backup`

Article slides also include a specific `separation_rationale`.

`role` describes the narrative job, such as `title`, `background`,
`clinical_context`, `decision`, `method`, `evidence`, `comparison`,
`interpretation`, `close`, or `backup`. `layout_family` describes the reading
path, not the topic. Examples:
`full_bleed`, `editorial_split`, `figure_first`, `chart_first`, `table_stage`,
`open_comparison`, `process_flow`, and `synthesis_field`.

`visual_anchor` names the object that carries the slide: an MRI, operative photo,
article figure, native chart, exact table, trial flow, anatomic schematic,
decision pathway, or deliberately composed typographic opening. `visual_coverage`
is its approximate share of the usable content frame as a percentage. A list of
bullets, a title rule, or decorative chrome is not a visual anchor.

## Slide Economy And Notes

- One slide, one narrative job, one dominant read.
- Do not put dossier or report paragraphs on slides.
- Do not create a slide for content that fits as one clear bullet or label on
  its parent slide.
- Split before shrinking below the readability floors in the visual-design
  module.
- Put exact caveats, transitions, and faculty defense in notes.
- Write notes for oral delivery, generally 45-75 seconds on a substantive slide.
- Every substantive slide requires speaker notes; title and section slides may
  use brief notes.

For an article presentation, the title slide reproduces the article title
exactly. Author, journal, year, presenter, and conference may appear as metadata.
Do not add an interpretive subtitle beneath the article title; put the thesis in
notes or the first content slide.

## Data Displays

- Prefer direct labels to legends when feasible.
- When a legend is needed, keep it native and compact, match its wording to the
  exact estimand and cohort shown, and preserve the same color meaning across
  related slides. Do not paste a cropped legend image into an editable chart.
- Preserve the source scale and use a defensible quantitative baseline.
- For comparable bars, areas, or lengths, use one explicit common scale and make
  mark length proportional to the displayed value. Never draw the complement
  of an event rate as though it were the event rate; a 5% complication or
  reoperation estimate must not appear as a 95%-filled bar.
- When a bar scale would exaggerate a small clinical event rate, use an aligned
  numeric table, dot plot, or lollipop plot with a labeled axis instead.
- Label numerator and denominator, follow-up, units, and whether values are
  reported or calculated.
- Use editable PowerPoint charts and tables only when values are exact.
- Replace default chart furniture with deliberate typography, restrained
  gridlines, direct labels, and the deck palette.
- Do not allow labels that concatenate series, category, and value into long
  strings.
- Make zero-valued or absent outcomes visible with an explicit label or baseline
  marker.
- Do not use a doughnut chart for small clinical denominators when counts are
  more informative.
- When heterogeneity drives interpretation, show individual patients.
- Keep color meaning stable throughout the deck.

## Scientific Figures And Imaging

- Use the highest-resolution source extraction available.
- Crop to the evidence object; remove publisher prose and page furniture while
  preserving panel labels, axes, legends, scale bars, and annotations.
- Use `contain` when cropping would lose scientific information.
- Put interpretation beside the figure, never over its data region.
- Cite every article figure on the same slide.
- A main-slide figure must pass the projection test at the final rendered size.
  If labels or the decisive pattern are not readable, isolate a declared panel,
  rebuild the exact display, move it to backup, or replace it.
- Rebuild exact source tables as editable PowerPoint tables. Split dense tables
  across backup slides before using an unreadable screenshot.

## Citations

Reserve a consistent footer zone before laying out the slide body. Use a compact
10-12 pt citation on evidence-bearing slides unless a supplied template requires
another readable size. The reference-backed Baylor profile uses 7.5-9 pt in its
reserved footer zone when the full-size render remains legible. Show author,
journal, year, and figure or table when applicable. Full references and links
live in the presentation note.
The editorial subtraction pass may remove redundant captions or interpretation
bands, but it may not remove the evidence citation.

## Required Build Package

Create:

```text
deck_plan.json
asset_manifest.json
visual_qa.json
source_notes.txt
<Title>.pptx
```

`asset_manifest.json` records the source, transformation, rights/provenance,
output path, and destination slide for every external or generated asset.
`visual_qa.json` records the latest rendered inspection and completed repair
cycle, not intentions.

## Render And Repair Loop

After every meaningful revision:

1. Export the PPTX.
2. Run the runtime's structural and overflow checks.
3. Render every slide at useful resolution.
4. Inspect the contact sheet for rhythm, silhouette diversity, and narrative
   emphasis.
5. Inspect every slide at full size for typography, figure legibility, spacing,
   cropping, collisions, and source integrity.
6. Perform the editorial subtraction pass: delete repeated titles, captions,
   bottom takeaway bands, and duplicate summary scope while retaining citations,
   uncertainty, denominators, and semantic labels.
7. Verify one-line title and label fit with at least 10% horizontal slack; reject
   split numbers, split single words, stale legend labels, pasted chart legends,
   and watermarked assets even when the overflow checker is silent.
8. Fix the build source, regenerate, and rerender the affected slides.
9. Perform one final full-deck render after the last repair.

The first render is a draft. A delivery candidate requires at least one explicit
find-fix-rerender cycle.

Generate the canonical ledger shape instead of copying a prose schema:

```bash
python3 src/grand_rounds_guard.py visual-qa-template --slide-count <n>
```

Populate every field from the final render. All failure lists—including
`chart_label_failures`, `alignment_failures`,
`misleading_quantitative_encoding_slides`, `color_overuse_slides`,
`filled_container_overuse_slides`, `rounded_container_slides`,
`decorative_line_overuse_slides`, `textbox_fit_failures`, `redundant_slides`,
`semantic_legend_failures`, `watermarked_asset_slides`,
`redundant_interpretive_band_slides`, and
`cross_platform_render_failures`—must be empty before `status: pass`.
`repair_cycle_count` must reflect at least one real repair, and
`meaningful_visual_main_slide_count` must match the plan. Never mark a planned
inspection as completed.

## Deterministic Package Guard

Run:

```bash
python3 src/grand_rounds_guard.py validate \
  --deck "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Presentations/Decks/<Cases-or-Articles>/<Title>.pptx" \
  --plan "<scratch>/deck_plan.json" \
  --assets "<scratch>/asset_manifest.json" \
  --visual-qa "<scratch>/visual_qa.json" \
  [--source-journal-club "/absolute/path/to/Journal Club/<Title>.md"] \
  --json
```

Repair every failure before the vault write.

## Vault Write

Use `src/grand_rounds_writer.py` with `--require-quality-gate` and the source,
duration, package-manifest, slide count, and QA status arguments. When the target
already exists, read it completely, preserve durable rehearsal/user additions in
the regenerated draft, and pass `--overwrite`; never work around the safety gate
with a versioned duplicate. The note is a delivery/rehearsal surface, not a
duplicate report.

## Completion Audit

- Editable PPTX exists and is valid OOXML.
- Main-slide timing fits the requested duration.
- Slide jobs are unique and coverage is complete.
- Speaker notes are embedded.
- Article or case visuals are traceable and legible.
- Quantitative claims pass source checks.
- The visual design matches the approved or inferred design brief.
- At least one fix-and-rerender cycle is recorded.
- Contact-sheet rhythm and full-size slide inspection pass.
- No unintended overlap, clipping, wrapping, placeholder, or illegible evidence
  object remains.
- The package guard passes.
