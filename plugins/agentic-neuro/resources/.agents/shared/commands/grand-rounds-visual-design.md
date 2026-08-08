# Grand Rounds Visual Design

Art-direction contract for every Grand Rounds deck. Build an academic talk, not
a report arranged on slides. Evidence controls hierarchy; decoration never
competes with imaging, figures, tables, or clinical decisions.

## Choose One Route

1. **Template faithful:** a supplied institutional/reference deck controls its
   grammar.
2. **Custom directed:** explicit user direction controls the system.
3. **Editorial academic:** use the default system below.

Do not blend unrelated systems. A reference supplies a grammar, not slides to
copy. Journal-club decks default to the `baylor_minimal_academic` style in
`.agents/shared/presentation-styles.json`. Resolve its `reference_deck` relative
to the directory containing that JSON file. When the declared reference deck
exists, render and inspect it, then record `reference_alignment`: path, adopted
patterns, and weaknesses rejected. If unavailable, state that and use the
registry's patterns without pretending it was inspected.

## Required Design Brief

Resolve `design_brief` in `deck_plan.json` before slide planning. It contains:

- route, audience, communication job, and one topic-specific art-direction
  sentence;
- page system, palette and rationale, display/body fonts, sentence case title
  style, content-bearing motif, and background strategy;
- at least three allowed layout families and explicit forbidden moves such as
  repeated title underlines and bullet walls;
- `surface_style`, its registry-backed `human_style_constraints`, and
  `reference_alignment` when Baylor Minimal Academic is selected.

The motif must carry content—for example consistent image crops/caption rails,
direct evidence annotation, or repeated operative-orientation labels. A stripe,
logo, title rule, or page-edge bar alone is not a motif.

## Baylor Minimal Academic Surface

The exact palette (`#1F4E79` navy), font floors, reference path, and constraint
values live only in `presentation-styles.json`. Copy them into the design brief;
do not maintain a second prose schema here.

- White canvas; dark ink; one navy accent; neutral chart furniture; one signal
  color only when the data require it.
- Open, unboxed evidence layouts. No rounded cards, pills, tinted panels,
  conclusion banners, or generic filled containers. The registry's
  `filled_content_containers_max_per_slide` is enforced.
- Use color for data and essential warnings, not decorative hierarchy.
- Charts use navy plus neutral gray, with a native compact legend only when
  direct labels are insufficient. Tables stay predominantly white.
- Stable page furniture is limited to the declared short title rule and footer
  rule. Whitespace, alignment, and typography do the rest.
- Reference-derived typography is approximately 34-38 pt for long article
  titles, 28-30 pt for content titles, 17-20 pt for panel headings, 13.5-16 pt
  for body labels, and 7.5-9 pt for citations—floors, not targets.

## Composition

Use a 16:9 canvas, one underlying grid, at least 0.5-inch side margins, and a
reserved citation footer. Vary the silhouette only when the narrative job
changes.

| Narrative role | Preferred composition |
| --- | --- |
| Title | Quiet typography or source-backed image; metadata only |
| Clinical context | Dominant imaging/anatomy plus a short orientation rail |
| Decision | Visible pathway, threshold, tension, or open comparison |
| Methods | Editable schema, patient flow, or essential process |
| Evidence | Figure/chart/table first, occupying most of the frame |
| Interpretation | Annotated evidence plus one consequence |
| Summary | Three to five aligned evidence-backed rows; no new evidence |
| Backup | Utility-first, readable, and explicitly labeled |

Every substantive main slide needs a meaningful visual or evidence anchor.
Imaging, scientific figures, native charts, exact tables, flows, anatomy, and
decision pathways qualify; bullets and decorative chrome do not. Evidence
anchors should usually occupy 55-75% of the usable frame. If the decisive object
is unreadable at that scale, isolate a panel, split the slide, rebuild exact
values, or move it to backup.

Do not use one `layout_family` on more than half of substantive main slides or
on three consecutive substantive slides. Make the opening, evidence core,
interpretation, and close visibly distinct. Give the decisive result the
strongest visual dominance.

## Typography And Copy

- Use no more than two reliable font families. Outside a supplied template,
  default floors are 50 pt deck title, 35 pt slide title, 24 pt subhead, 18 pt
  body, and 10 pt citations; registry-backed styles may define their own floors.
- Titles are concise academic labels, usually two to eight words. Preserve an
  article's exact published title on the title slide. No thesis, tagline,
  interpretive subtitle, slogan, rhetorical question, or clever opposition.
- Visible text is a precise title, evidence label, essential qualifier, or one
  short supported interpretation. Put explanation, transition, and faculty
  defense in speaker notes.
- Avoid paragraphs, colored sentence fragments, fabricated quotations, and
  promotional or conversational language.
- Keep one-line titles, numbers, and labels at least 10% inside their fit limit.
  Split the slide before shrinking. A technically non-overflowing box still
  fails if it fragments a word or numeric token.

## Quantitative And Scientific Integrity

- Preserve uncertainty, denominators, time points, axes, panel labels, scale
  bars, zero outcomes, and cohort/estimand identity.
- Keep quantitative marks proportional on a common declared scale. Never show
  a complement as though it were the event rate.
- Use exact editable charts/tables when values are known. Crop source figures to
  the evidence object without removing scientific context.
- Legends must match the estimand and cohort; rebuild them natively rather than
  pasting a cropped legend.
- Cite evidence on the same slide. Generated imagery must never resemble
  patient, operative, radiographic, pathologic, or study data.

## Editorial Subtraction Pass

After the first complete render, delete anything that repeats the title, visible
evidence, or summary: redundant takeaway bands, footer-adjacent commentary,
duplicate clinical-scope statements, and low-information captions. Never delete
citations, uncertainty, denominators, scale direction, or semantic labels for
cleanliness.

## Fresh-Eyes Visual Critique

Inspect the contact sheet as a skeptical faculty audience member:

- Is the thesis legible from sequence and emphasis?
- Are opening, evidence core, interpretation, and close distinct?
- Does the most important evidence dominate?
- Does any slide resemble a report page, dashboard, AI card grid, or repeated
  template?

Then inspect every slide full size for title wrapping, hierarchy, contrast,
baseline/alignment, figure scale/crop, soft rasterization, covered labels,
collisions, citations, semantic color, stale legends, pasted legends,
watermarks, decorative chrome, and cross-platform render drift.

Repair the weakest main slide, weakest anchor, most repetitive layout, and least
natural title, then rerender the full deck. Geometry checks without this
find-fix-rerender cycle do not constitute completion.
