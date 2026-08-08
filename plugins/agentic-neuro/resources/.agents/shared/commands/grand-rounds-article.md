# Grand Rounds Article Mode

Create a journal-club PowerPoint from a validated `Journal Club/` dossier and
its archived PDF. The dossier owns interpretation and teaching order; the PDF
owns exact methods, data, figures, tables, and wording.

## Source Resolution

Preferred input is `--journal-club "Journal Club/<Title>.md"`. Read the complete
note, resolve its frontmatter `source_pdf`, and require `skill: journal-club`,
`source_package_status: complete`, a present PDF, and the required dossier
sections. If only a PDF is supplied, complete and validate passive Journal Club
analysis first. DOI- or abstract-only inputs support a preliminary outline, not
a source-complete deck.

Authority order:

1. PDF for article facts and visuals.
2. Dossier for synthesis, critique, context, practice boundary, and defense.
3. Dossier-linked sources for historical/current context.
4. New research only for a presentation-critical gap, with explicit provenance.

Preserve discrepancies. Reconcile any new conclusion with the dossier rather
than silently replacing its interpretation.

## Interpretation-Critical Coverage Audit

Before choosing slide count, audit the full dossier and PDF. Record the result in
`deck_plan.json.coverage_audit`; this is a planning ledger, not a visible
checklist.

Required dimensions:

- `study_ecosystem`: screened/enrolled/randomized/refusal/observational/registry
  cohorts and each inferential role;
- `eligibility_and_applicability`: phenotype, exclusions, selection ratio,
  setting, center/surgeon constraints, and missing populations;
- `intervention_and_comparator`: protocol, permitted tailoring, concomitant
  care, rescue/crossover, fidelity, and actual delivered care;
- `outcome_schedule`: outcomes, direction, important difference when supplied,
  measurement times, analysis metric, and denominators;
- `treatment_adherence`: exposure, crossover both ways, retention, missingness,
  and timing;
- `longitudinal_results`: onset, peak, persistence, convergence, or reversal;
- `benefits_harms_secondary_outcomes`: magnitude, uncertainty, function,
  satisfaction, adverse events, reintervention, and rare-event limits;
- `interpretation_and_bias`: randomization/masking, analysis population,
  nonadherence, missing data, multiplicity, selection, funding, applicability,
  and likely bias direction.

For each critical item record a stable ID, summary, source, salience,
disposition, slide IDs, and rationale. Salience is `thesis-determining`,
`decision-relevant`, `faculty-defense`, or `administrative`; disposition is
`main`, `notes`, `backup`, or `omit`. Never omit thesis-determining or
decision-relevant evidence. Compress related items by interpretive cluster, not
by deleting a dimension.

Record prespecified versus displayed time points and whether trajectory is
interpretively necessary. For material companion evidence, record
`verified_source`, `identified_not_retrieved`, or `not_applicable`. Identify a
material companion report in the main talk, but show its numbers only after
retrieval and verification. `coverage_risks` must be empty at finalization.

The plan also maps these dossier sections across the main talk: Start Here,
Clinical Foundation, Study Architecture, Results That Matter, Figures and Tables
Explained, Interpretation, Limitations That Actually Matter, Neurosurgical
Relevance, and Presentation Core. Faculty Defense may live in notes/backup;
Source Trace lives in citations/manifests.

## Narrative And Slide Economy

Use the dossier title and attending angle by default. Default to 15 minutes. The
title slide contains only the exact published title, authors/citation, presenter,
institution, and optional conference/date—no thesis, tagline, alternate
subtitle, takeaway, or interpretive graphic label.

The second main slide is exactly `Background` or `Introduction`, role
`background`, mapped to Clinical Foundation. In three to five article-specific
anchors, establish relevant pathology/mechanism, natural history, usual
management/urgent boundary, and the evidence gap. Keep deeper intern teaching in
speaker notes; phenotype/eligibility may receive a later slide when selection
matters.

A typical 15-minute arc is 10–14 main slides, but content determines count:

1. exact article title;
2. background and clinical gap;
3. candidate phenotype and selection ecosystem;
4. study architecture and delivered strategies;
5. adherence, crossover, and outcome schedule;
6. decisive result with denominators and uncertainty;
7. trajectory or patient-level heterogeneity;
8. other decision-relevant benefits, harms, or mechanism examples;
9. validity boundary and clinical application;
10. `Summary` or `Main Takeaways`.

Adapt the arc to archetype: initial-strategy trials separate assignment from
treatment received; procedure comparisons foreground fidelity and variation;
failure maps lead with operative anatomy and end with avoid/inspect/correct;
prognostic cohorts distinguish prediction from treatment effect.

Rank candidate content before authoring. Thesis-determining and
decision-relevant evidence owns main-slide space; faculty-defense evidence goes
to notes/backup; administrative content is omitted. Select one `central_visual`
as the shortest path to the thesis. At least one result slide must communicate
population/denominator, effect, uncertainty, follow-up, and evidentiary label
within roughly ten seconds.

### Slide Separation Test

Every article slide records `separation_rationale`. Merge/delete it when it could
be one label on its parent, repeats an interpretation, or needs spoken setup just
to reveal its subject. Backup slides answer plausible faculty questions and do
not hide required comprehension.

Every article deck ends with one main `Summary` or `Main Takeaways` slide: three
to five parallel, evidence-backed points covering population/comparator,
decisive result or trajectory, strongest validity boundary, and clinical
application. It introduces no new estimate or recommendation.

## Slides, Notes, And Assets

Each `grand_rounds_deck_plan_v2` slide follows the shared deck schema and, in
article mode, adds `separation_rationale`. Visible language remains faculty-level
and concise. Each substantive slide's speaker notes include the claim, necessary
concept explanation, exact anchors/denominators, what the visual does not show,
transition, and likely faculty challenge. Write for oral delivery rather than
copying dossier prose.

Prioritize assets from Data Worth Showing and Figures and Tables Explained.
`asset_manifest.json` records stable ID, kind, absolute source PDF, page/source
label, output path, transformation, citation, and destination slides.

- Extract/render at presentation resolution; preserve axes, legends, panels,
  annotations, and aspect ratio.
- Crop publisher prose, not scientific content. Declare panel crops.
- Use `contain` when a crop would lose evidence.
- Rebuild exact tables/charts as editable objects; never silently digitize a
  plotted value.
- Put dense or secondary detail in readable backup slides.
- Cite the asset on-slide and preserve full provenance in the manifest.

Add one `result_checks` entry for every displayed number: claim, expected value,
actual value, source, and pass. Report unavailable intervals or outcomes rather
than inventing precision. Preserve distinctions such as response versus freedom,
reported versus calculated, and association versus causation.

## Article Gate

Before the shared deck guard, require:

- complete coverage mapping with no unresolved risks;
- actual delivered comparator/intervention, adherence, and selection ecosystem;
- enough time points to show clinically important trajectory;
- thesis agreement with the dossier's data-supported conclusion;
- denominators/dispersion and passed result checks for decisive data;
- legible source-traced figures/tables and patient-level display when averages
  conceal meaningful heterogeneity;
- consequence-framed limitations, candidate/noncandidate boundary, and bounded
  practice impact;
- preserved discrepancies and no claim of proof from uncontrolled evidence;
- Background/Introduction second, every slide separated for a distinct job, and
  Summary/Main Takeaways last;
- technically precise visible vocabulary with explanation in notes;
- full compliance with the shared visual-design and deck contracts.

## Vault Presentation Note

After the real package passes, write the presentation note with mode, deck link,
source dossier/PDF, duration, thesis, and only useful sections from: Presentation
Arc, Coverage Ledger, Slide Outline and Speaker Notes, Study Design and Methods,
Methods Critique, Clinical Impact, Citation List, Asset Manifest, Anticipated
Questions, Presentation Risks, and What Not To Say. Do not duplicate the dossier.
