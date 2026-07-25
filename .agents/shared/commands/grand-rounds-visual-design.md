# Grand Rounds Visual Design

Editorial art-direction and composition contract for every `/grand-rounds`
PowerPoint. Use this module after resolving the case or article mode and before
writing `deck_plan.json`.

## Standard

Build a real academic talk, not a report placed onto slides. The deck should
read as intentionally art-directed at thumbnail scale and remain clinically
precise at full size. Evidence controls the visual hierarchy; decoration never
competes with imaging, figures, charts, tables, or the clinical decision.

## Choose One Visual Route

1. **Template faithful:** a supplied institutional or reference deck controls
   typography, palette, spacing, page furniture, and layout grammar.
2. **Custom directed:** explicit user visual direction controls the system.
3. **Editorial academic:** when no stronger direction exists, create the default
   system below.

Do not combine unrelated template or layout systems. A reference deck supplies
a grammar, not a set of slides to imitate mechanically.

For Gabriel's journal-club decks, use the `baylor_minimal_academic` surface
style by default unless he supplies a specific template or asks for another art
direction. This profile is derived from his prior Baylor/VA journal-club decks;
it preserves their restrained human-made visual grammar while retaining the
stronger evidence displays, source tracing, and content coverage required here.

### Human-edited journal-club exemplar

When present, inspect Gabriel's finalized local reference before planning a new
journal-club deck:

```text
/Users/gabrielreyes/Documents/Residency/Journal Clubs/SPORT Lumbar Disk Herniation Trial.pptx
```

Treat it as a visual and editorial exemplar, not a content template or a waiver
of the current quality gates. Render every slide, then record `reference_alignment`
in the design brief with the inspected path, the patterns adopted, and the
weaknesses explicitly rejected. Adopt the stable grammar: quiet white title
slide, wide left-aligned content frame, short navy title rule, thin footer rule,
navy-plus-gray evidence palette, open unboxed layouts, large quantitative marks,
compact academic labels, and a numbered recap slide. Do not copy article-specific
content, watermarked assets, missing citations, pasted chart legends, stale legend
labels, text fragmentation, overlap, or awkward wrapping. The required Background
or Introduction slide remains mandatory even when an older reference deck lacks it.

## Baylor Minimal Academic Surface

This is a constraint system, not a fixed slide template.

- Use a white canvas on the title, content, interpretation, summary, and backup
  slides. Do not create a dark title or closing slide by default.
- Use dark ink, muted gray, light-gray rules/gridlines, and one institutional
  navy accent. A single additional signal color is allowed only when the data
  require a true comparison, harm, or exclusion distinction.
- Use the finalized reference palette unless a supplied template overrides it:
  ink `#111827`, navy `#1F4E79`, neutral gray `#4B5563`, rule/gridline gray
  `#E5E7EB`, and signal red `#B71C3A`.
- Color belongs to data marks, selected table headers, essential direct labels,
  and rare warnings. Do not use color to manufacture hierarchy that typography,
  alignment, or whitespace can provide.
- Place content directly on the canvas. Do not use rounded cards, pills, badges,
  tinted section panels, colored conclusion banners, or repeated filled callout
  containers.
- A short navy title rule and a thin neutral footer rule are permitted as stable
  page furniture. Do not add other decorative rails, separators, brackets, or
  connector lines unless they clarify actual data or study structure.
- Default charts to navy plus neutral gray on a white plot area with restrained
  gray gridlines. Use another hue only when two clinically distinct categories
  cannot be distinguished clearly by label, line style, marker, or position.
- Keep tables predominantly white. A navy header is acceptable; use cell or row
  highlighting only for one evidence-critical comparison and never as a rainbow
  significance code.
- Prefer open columns, direct labels, full-size figures, and unframed images.
  Filled rectangles may represent quantitative bars or table cells, but may not
  act as generic content containers.
- Preserve generous whitespace, left alignment, and a consistent footer. The
  slide should still look coherent when all accent fills are mentally removed.

When prior decks are used as a reference set rather than a literal template,
inspect every slide and document both the stable recurring grammar and the
reference weaknesses that must not be copied. Store the following in the design
brief:

```json
{
  "surface_style": "baylor_minimal_academic",
  "human_style_constraints": {
    "white_backgrounds_only": true,
    "primary_accent_count_max": 1,
    "signal_color_count_max": 1,
    "filled_content_containers_max_per_slide": 0,
    "rounded_content_containers": "none",
    "recurring_page_furniture": ["short navy title rule", "neutral footer rule"],
    "chart_palette": "navy plus neutral gray",
    "color_use": "data and essential warnings only",
    "interpretive_band_policy": "only when it adds a nonredundant clinical or validity consequence",
    "chart_legend_policy": "native compact legend with labels matched to the estimand",
    "summary_duplication": "none"
  }
}
```

Use the following reference-derived compositions as a small library, selected by
narrative job rather than repeated mechanically:

| Narrative job | Preferred composition |
| --- | --- |
| Clinical phenotype | One large unframed image plus three to five numbered criteria |
| Study ecosystem | Sparse participant flow with exact totals and cohort roles |
| Delivered strategies | Open split comparison; steps on one side and proportional treatment-use marks on the other |
| Treatment exposure | Dominant longitudinal chart plus a narrow rail for only the decisive time-point contrasts |
| Estimands | Minimal branching diagram separating assignment from treatment-received analysis |
| Serial outcomes | Three aligned small multiples with stable scales, labels, and uncertainty |
| Matched estimates | Equal open columns with one large estimate, interval, and evidentiary label per column |
| Informative crossover | Mirrored comparison showing the prognostic differences in each crossover direction |
| Harms | Aligned event counts and common-scale bars or dots; no inverse-filled rates |
| Summary | Three to five numbered horizontal rows; no extra strapline repeating those rows |
| Backup | Utility-first open columns with explicit `Backup ·` labeling and readable citations |

## Required Design Brief

Resolve this before slide planning and store it under `design_brief` in
`deck_plan.json`:

```json
{
  "route": "editorial_academic",
  "audience": "Neurosurgery faculty and residents",
  "communication_job": "By the end, the audience should ... because ...",
  "art_direction": "One concrete sentence tied to the case or article",
  "page_system": "One coherent grid and reading path",
  "palette": {
    "canvas": "#FFFFFF",
    "ink": "#111827",
    "primary": "#1F4E79",
    "secondary": "#4B5563",
    "rule": "#E5E7EB",
    "signal": "#B71C3A"
  },
  "palette_rationale": "Why these colors fit the topic and evidence",
  "display_font": "Arial",
  "body_font": "Arial",
  "title_style": "sentence_case",
  "motif": "One repeated content-bearing treatment",
  "background_strategy": "white_only",
  "layout_families": ["full_bleed", "editorial_split", "figure_first"],
  "forbidden_moves": ["repeated title underlines", "bullet walls"],
  "reference_alignment": {
    "reference_deck": "/Users/gabrielreyes/Documents/Residency/Journal Clubs/SPORT Lumbar Disk Herniation Trial.pptx",
    "status": "inspected",
    "adopted_patterns": ["white canvas", "open evidence layouts", "navy plus gray charts"],
    "rejected_weaknesses": ["watermarked assets", "text fragmentation", "pasted legends", "missing citations"]
  }
}
```

Make `art_direction` specific enough that it could not describe an unrelated
talk. Define the motif as a content-bearing treatment such as image crops with a
consistent caption rail, direct annotations, or repeated operative-orientation
labels. A colored stripe, title underline, page-edge bar, or logo repeated on
every slide is not a motif.

## Editorial Academic Default

### Page system

- Use a 16:9 canvas and a consistent content frame with at least 0.5 inch side
  margins.
- Use one underlying grid, but vary the silhouette by slide role.
- Reserve footer space before placing the body.
- Use a dark or image-led title slide when it suits the art direction. Keep
  content, interpretation, summary, and backup slides on one consistent light
  field by default. A dark closing slide requires explicit user direction or a
  source-backed visual reason; do not add one merely to create a bookend.
- Avoid a full-width header rule or banner on every slide. Repetition should
  come from alignment, typography, crop treatment, and caption behavior.

### Typography

- Use at most two type families: one display face and one body face. For reliable
  cross-platform rendering, default to Cambria with Arial or to Arial alone.
- Use at least 50 pt for the deck title, 35 pt for slide titles, 24 pt for
  subheads, 18 pt for normal body copy, and 10 pt for citations.
- For the reference-backed `baylor_minimal_academic` profile, use one sans-serif
  family and the finalized SPORT scale instead of the generic no-template scale:
  34-38 pt for a long published article title, 28-30 pt for content-slide titles,
  17-20 pt for panel or row headings, 13.5-16 pt for body labels, and 7.5-9 pt for
  compact citations. These are floors only when the full-size render remains
  legible; enlarge sparse slides rather than treating the smallest value as a
  target.
- Use sentence case for authored titles and headings. Preserve published article
  titles, proper nouns, acronyms, and required institutional capitalization.
- Use concise academic titles, usually two to eight words and preferably a noun
  phrase. Titles identify the topic, result class, or analytic frame; they do not
  need to function as complete explanatory sentences. Move descriptive detail
  into the evidence labels or speaker notes.
- A title intended as one line must remain one line. Shorten or change the
  composition before shrinking it.
- Use bold for hierarchy, not for entire paragraphs. Avoid decorative italics,
  all-caps section labels, and arbitrary font-size drift.

### Palette

- Choose colors from the topic, source figures, imaging, or institutional
  context; do not default automatically to generic blue.
- Give one color 60-70% of the non-neutral visual weight. Use one supporting
  tone and one signal color only when it carries meaning.
- Keep semantic color stable: the same treatment, cohort, risk, or outcome keeps
  the same color throughout.
- Prefer white or true dark backgrounds. Do not default to cream or beige.
- Meet readable contrast for text, labels, legends, and citations.
- For `baylor_minimal_academic`, the navy accent should carry nearly all
  non-neutral emphasis; do not assign a different hue to every cohort, result,
  limitation, or takeaway.

## Composition Grammar

Choose layouts by narrative role rather than cycling through templates.

| Role | Preferred Composition | Failure To Avoid |
| --- | --- | --- |
| Title | Minimal typography with a dark, image-led, or quiet light field | Abstract subtitle, dense metadata, decorative underline |
| Clinical Context | Dominant imaging/anatomy with a short orientation rail | Two columns of prose |
| Decision | One visible tension, pathway, threshold, or side-by-side tradeoff | Equal boxes containing paragraphs |
| Methods | Trial schema, patient flow, or editable process with only essential labels | Five-row label-and-description list |
| Evidence | Figure-, chart-, or table-first composition occupying most of the frame | Thumbnail figure beside a large text block |
| Comparison | Open columns or a directly labeled quantitative contrast | Card grid or colored KPI tiles |
| Interpretation | Annotated evidence plus one consequence statement | Four generic limitations listed at equal weight |
| Summary | Three to five aligned evidence-backed recap points including the clinical boundary | New evidence, prose paragraphs, or a decorative “Thank You” |
| Backup | Utilitarian high-density evidence with preserved readability | Main-deck visual flourish that obscures detail |

Every substantive main slide needs a meaningful visual or evidence anchor. Native
charts, exact tables, scientific figures, imaging, operative photographs,
anatomic schematics, patient flows, and decision pathways qualify. Decorative
lines, icons, stock art, bullets, or a colored box do not.

Aim for the dominant object to occupy roughly 55-75% of the usable frame on
evidence slides. Use the remaining space for the claim, direct labels, and one
interpretive consequence. If the object cannot be legible at that scale, isolate
a panel, split the slide, or move it to backup.

## Narrative Rhythm

- Design the opening, evidence core, interpretation, and close as distinct beats.
- Alternate silhouettes when the argument changes: image, pathway, figure,
  chart, table, synthesis. Do not alternate merely for novelty.
- Do not use the same `layout_family` on more than half of substantive main
  slides or on three consecutive substantive slides.
- Avoid several consecutive slides with identical white background, title
  position, underline, and two-column body. Clean repetition is still monotony.
- Give the decisive result the strongest visual dominance in the deck.
- Keep the final slide visually resolved and clinically actionable.

## Copy And Density

- Visible copy serves the audience; notes serve the presenter.
- Replace paragraphs with direct labels, a comparison, an annotation, or a
  speaker-note explanation.
- Use no more than one short explanatory block beside the dominant object.
- Standard bullets are acceptable for brief lists, but a bullet wall is a design
  failure.
- Center only short labels and numbers inside deliberately equal columns. Keep
  explanatory body text left aligned. Verify equal column widths, shared
  baselines, and optical centering at full size; a mathematically centered text
  box is not sufficient when the visible text still appears displaced.
- Give one-line titles, large estimates, legends, and short labels at least 10%
  horizontal fit slack in the rendered deck. A text box that technically fits
  but splits a number, hyphenated term, or single word across lines has failed.
- Match legends to the actual estimand and cohort on that slide. Reuse legend
  geometry and typography across related charts, but rebuild the labels natively;
  never paste a cropped legend image into an editable chart slide.
- Do not fill whitespace with decorative icons or extra claims. Empty space must
  clarify the reading path.

### Editorial subtraction pass

After the first complete render, perform a deletion pass before adding anything.
Remove any footer-adjacent takeaway band, small comment, caption, or second
interpretive sentence that repeats the title, restates visible evidence, or says
nothing clinically consequential. On a Summary or Main Takeaways slide, keep the
population, comparator, result, validity boundary, and application inside the
three to five recap rows; do not repeat clinical scope in a separate bottom band.
Do not remove evidence citations, denominators, uncertainty, scale direction, or
semantic labels for cleanliness.

## Academic Slide Copy

Visible language must read as scientific presentation copy, not advertising,
consulting commentary, or a transcript. Treat every word as one of four useful
objects: a precise slide title, an evidence label, an essential qualifier, or a
short data-supported interpretation. Move explanation, transitions, nuance, and
faculty defense to speaker notes.

### Titles

- Prefer a concise neutral academic title such as `Study Population`,
  `Treatment Crossover`, `Primary Outcomes`, `Operative Harms`, or
  `Interpretation Boundaries`. Use a short data-supported message title only
  when it remains compact.
- Default to two to eight words for authored content-slide titles. Avoid full
  sentences, semicolon constructions, and titles that contain both the result
  and its explanation. Preserve the exact published article title on the title
  slide.
- Do not use slogans, aphorisms, commands to the audience, clever wordplay,
  rhetorical questions, personification, or conversational interjections.
- Avoid formulaic opposition such as `not X, but Y`, `X stayed; Y did not`,
  `choose X, not Y`, or a large `≠` symbol. When a scientific distinction is
  necessary, label both constructs directly, for example `randomized assignment
  effect` and `adjusted treatment-received association`.
- Do not add a title solely to create drama. A factual title such as `At 2 years,
  surgical exposure was 60% versus 45%` is preferable to an embellished claim.

### Body copy and annotations

- Use short noun phrases, exact values, direct chart labels, and compact complete
  statements. Keep enough context that a label is interpretable without the
  presenter, but do not duplicate the spoken explanation.
- Limit each slide to one short interpretive sentence beyond the title and
  evidence labels. Omit it when the figure, table, or pathway already makes the
  point.
- An annotation must identify a value, comparison, mechanism, bias direction,
  applicability boundary, or clinical consequence. Delete annotations that only
  repeat the title, comment on the design, or fill whitespace.
- Write limitations in standard scientific language: name the threat, the
  affected estimand, and the consequence. Avoid miniature verdicts such as
  `the groups converged`, `certainty shrinks`, or `the tradeoff is real` when the
  exact quantitative or methodological statement can be shown instead.
- Use parallel fragments only for genuine lists or matched comparisons. Do not
  break a narrative sentence into multiple colored fragments for visual effect.
- Do not place fabricated quotation marks around counseling language. If exact
  suggested language is useful, identify it as `Suggested counseling language`
  in notes or as one restrained complete sentence on the clinical-application
  slide.

### Article title slide

Show only the exact published title, authors or citation, presenter, institution,
and conference/date metadata when needed. Do not add a thesis, tagline,
takeaway, interpretive subtitle, or evidence annotation. A non-semantic visual
treatment may support the composition but must not introduce a claim.

### Copy QA

Read the slide without notes and ask:

- Does every visible phrase identify evidence, analysis, applicability, or a
  clinically relevant conclusion?
- Could the title appear in a departmental academic talk without sounding
  promotional, theatrical, or conversational?
- Does any small caption merely restate the title or narrate what the audience
  can already see?
- Is any `not X, Y` construction standing in for a more precise scientific
  distinction?
- Would deleting a phrase leave the evidence and meaning unchanged? If yes,
  delete it.

## Academic Visual Integrity

- Use source figures and patient imaging as evidence, not wallpaper.
- Never place generated imagery where it could be mistaken for clinical,
  operative, radiographic, pathologic, or study data.
- Keep charts and tables editable when values are exact.
- Use direct labels and annotations that explain the decisive pattern without
  covering the evidence.
- Preserve uncertainty, denominators, time points, axes, panel labels, scale
  bars, and clinically important zero outcomes.
- Show a compact same-slide source; keep complete citations in the presentation
  note.

## Fresh-Eyes Visual Critique

Inspect the render as a skeptical faculty audience member, not as the author.
The contact sheet must answer:

- Is the thesis visible in the sequence and visual emphasis?
- Does the deck have a recognizable visual identity without decorative chrome?
- Are opening, evidence, and close visually distinct?
- Is one layout repeated too often?
- Does the most important evidence dominate?
- Does any slide look like a report page, web dashboard, or AI card grid?

At full size, check:

- Title wrapping, font hierarchy, contrast, and baseline consistency.
- Figure scale, cropping, soft rasterization, and covered labels.
- Text overflow, collisions, narrow columns, and uneven spacing.
- Chart labels, table density, citations, and stable semantic color.
- Word or numeric-token fragmentation, stale legend labels, pasted chart legends,
  and watermarks from stock or publisher-preview assets.
- Bullet walls, generic stock elements, title underlines, accent stripes, and
  other decorative filler.
- Count colored filled containers, non-data colors, rounded rectangles, and
  decorative rules. Any slide that depends on several of these to look
  organized has failed the Baylor minimal surface even if it is geometrically
  clean.

Repair the weakest main slide, the weakest visual anchor, the most repetitive
layout, and the least natural title. Then rerender. Passing geometry without
this critique is not a finished deck.
