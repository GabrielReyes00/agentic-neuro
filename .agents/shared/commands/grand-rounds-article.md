# Grand Rounds Article Mode

Create a journal-club PowerPoint from a validated `Journal Club/` dossier and its
archived source PDF. The dossier supplies the interpretation and teaching order;
the PDF remains authoritative for article data, figures, tables, and exact wording.

## Source Resolution

Preferred invocation:

```text
/grand-rounds --mode article \
  --journal-club "Journal Club/<Short Article Title>.md"
```

Resolve the note beneath the real vault root. Read the complete dossier, parse its
bottom YAML, and resolve `source_pdf`. Require:

- `skill: journal-club`
- `source_package_status: complete`
- a physically present PDF
- the required Journal Club dossier sections

If only `--pdf` is supplied, run the passive `/journal-club` workflow first and
validate the installed dossier. Do not duplicate article appraisal inside
`grand-rounds`. DOI- or abstract-only inputs support a preliminary outline only.

## Source Authority

Use this hierarchy:

1. Source PDF for data, methods, tables, figures, and quotations.
2. Journal Club dossier for synthesis, critique, educational dependency order,
   practice verdict, and faculty-defense framing.
3. Dossier-linked external references for historical or current context.
4. New research only for a presentation-critical gap, with explicit provenance.

Do not introduce a new clinical conclusion without reconciling it with the
dossier. Preserve every documented discrepancy rather than choosing the most
favorable value.

## Intake Without Rework

Extract from the dossier:

- Citation and article type
- Clinical question and one-sentence thesis
- Clinical foundation and essential concepts
- Study architecture and selection pathway
- Result ledger and denominator-aware outcomes
- Recommended figures and tables
- Authors' conclusion, data-supported conclusion, and overclaim
- Consequence-framed limitations
- Neurosurgical relevance and practice verdict
- Publication-era and current context
- Presentation Core and Faculty Defense
- Source-package limitations

## Interpretation-Critical Evidence Audit

Before choosing slide count or layouts, read the complete dossier and audit the
source PDF against the dimensions below. This is a coverage sufficiency check,
not a request to place a checklist on slides. It operationalizes the trial
reporting priorities in CONSORT, intervention-description priorities in TIDieR,
and structured evidence extraction in the Cochrane Handbook.

1. **Study ecosystem:** screened, eligible, enrolled, randomized, refused,
   observational or registry cohorts, nested studies, companion reports, and the
   distinct inferential role of each cohort.
2. **Eligibility and applicability:** inclusion phenotype, exclusion criteria,
   selection ratio, setting, surgeon or center constraints, and clinically
   important populations not represented.
3. **Intervention and comparator actually delivered:** required protocol,
   permitted tailoring, concomitant therapies, rescue or crossover, treatment
   fidelity, technical variation, and the difference between planned and actual
   care.
4. **Outcome architecture:** primary and secondary outcomes, scale direction,
   clinically important difference when supplied, prespecified measurement time
   points, analysis metric, and denominator at each important time point.
5. **Treatment exposure and follow-up:** early and late adherence, crossover in
   both directions, retention, missingness, timing from enrollment and from
   intervention, and whether exposure changed during follow-up.
6. **Longitudinal result pattern:** onset, peak, persistence, convergence, or
   reversal of benefit across prespecified time points. Do not reduce a repeated-
   measures trial to its terminal time point when trajectory changes clinical
   interpretation.
7. **Benefits, harms, and patient-relevant secondary outcomes:** effect magnitude,
   uncertainty, symptom-specific outcomes, function, work, satisfaction, adverse
   events, reintervention, and rare-event limits.
8. **Validity and clinical boundary:** randomization, masking, analysis population,
   nonadherence, missing-data assumptions, multiplicity, informative treatment
   selection, funding, applicability, and the likely consequence or bias direction.

Write `coverage_audit` into `deck_plan.json` with:

```json
{
  "required_dimensions": {
    "study_ecosystem": ["S03"],
    "eligibility_and_applicability": ["S02", "S03"],
    "intervention_and_comparator": ["S04"],
    "outcome_schedule": ["S05"],
    "treatment_adherence": ["S05", "S06"],
    "longitudinal_results": ["S07", "S08"],
    "benefits_harms_secondary_outcomes": ["S08", "S11"],
    "interpretation_and_bias": ["S09", "S10"]
  },
  "critical_items": [
    {
      "id": "CI-01",
      "summary": "Concurrent observational cohort captured patients declining randomization",
      "salience": "thesis-determining",
      "disposition": "main",
      "slide_ids": ["S03"],
      "source": "Article Figure 1 and companion report",
      "rationale": "Explains selection into the RCT and the causal role of preference"
    }
  ],
  "longitudinal_result_coverage": {
    "prespecified_timepoints": ["6 weeks", "3 months", "6 months", "1 year", "2 years"],
    "shown_timepoints": ["3 months", "1 year", "2 years"],
    "trajectory_required": true,
    "rationale": "Speed and convergence determine the clinical interpretation"
  },
  "companion_evidence": [
    {
      "label": "Concurrent observational cohort",
      "material_to_interpretation": true,
      "source_status": "verified_source",
      "disposition": "main",
      "slide_ids": ["S03", "S09"],
      "citation": "Companion report citation"
    }
  ],
  "coverage_risks": []
}
```

`salience` is `thesis-determining`, `decision-relevant`, `faculty-defense`, or
`administrative`. `disposition` is `main`, `notes`, `backup`, or `omit`.
Thesis-determining and decision-relevant items may not be omitted. They must map
to a main slide unless a specific rationale explains why speaker notes or a
faculty-useful backup slide preserves comprehension. An absent slide is never
justified by a preferred slide count.

When several required items are related, compress them by **interpretive cluster**
rather than deleting them: selection plus companion cohorts; intervention plus
actual comparator components; follow-up schedule plus adherence; or serial
outcomes plus uncertainty. One well-designed slide may satisfy several dimensions.
Do not combine items that require different audience questions or causal labels.

For companion cohorts or reports, distinguish three states: `verified_source`,
`identified_not_retrieved`, and `not_applicable`. A material companion study must
be identified in the main talk. Show its quantitative findings only after the
companion source has been retrieved and verified; otherwise state its existence
and inferential role without borrowing unverified effect estimates.

The dossier title is the default deck title. The `Presentation Core` is the
default attending angle when the user supplies none. Default to 15 minutes.
The article title slide must use the article title only. Visible text is limited
to the exact published title, authors or citation, presenter, institution, and
conference/date metadata when needed. Do not add the agent's thesis, appraisal,
attending angle, alternate subtitle, tagline, takeaway, rhetorical contrast, or
interpretive diagram label anywhere on the title slide. Place interpretation in
notes or a later content slide.

## Coverage Ledger

Create a machine-readable deck plan before PowerPoint. Each slide must contain:

```json
{
  "id": "S07",
  "title": "Patient-level trajectories reveal three distinct outcomes",
  "job": "Show why the cohort mean is insufficient",
  "role": "evidence",
  "layout_family": "figure_first",
  "visual_anchor": "Article Figure 3 patient-level trajectories",
  "visual_coverage": 68,
  "background_tone": "light",
  "visible_content": ["6/7 responders", "3/7 seizure-free", "1/7 no response"],
  "speaker_notes": "Full presenter script and transition.",
  "citations": ["Reyes et al. 2026, Figure 3"],
  "assets": ["figure-3"],
  "source_sections": ["Results That Matter", "Figures and Tables Explained"],
  "timed_seconds": 70,
  "backup": false
}
```

Required coverage across the main talk:

- `Start Here`
- `Clinical Foundation`
- `Study Architecture`
- `Results That Matter`
- `Figures and Tables Explained`
- `Interpretation`
- `Limitations That Actually Matter`
- `Neurosurgical Relevance`
- `Presentation Core`

Faculty Defense may map to notes and backup slides. Source Trace maps to citations
and manifests rather than a visible prose slide.

## Required Background / Introduction Slide (Clinical Context)

Every article deck must orient the neurosurgery audience before selection,
methods, or results. The second main slide, immediately after the article title,
must be titled exactly `Background` or `Introduction`, use role `background`,
and map to `Clinical Foundation` in the deck plan. A phenotype, eligibility, or
study-population slide does not substitute for this opening frame.

Use three to five concise, article-specific anchors that establish:

- The disease or pathology mechanism relevant to the paper.
- The usual natural history or clinical trajectory.
- The standard triage and treatment pathway, including an urgent boundary when
  clinically relevant.
- The unresolved debate, decision, or evidence gap that made the study necessary.
- The paper's clinical question when it is not already explicit from the gap.

For a typical 10-15 minute journal-club presentation, keep this to one slide and
about 45-75 seconds. Use speaker notes for additional intern-level explanation,
definitions, and nuance. Do not turn the background into a mini-review, repeat
the later eligibility slide, or use generic epidemiology that does not help the
audience interpret the article.

The background slide should establish the field in which the paper lives; a
separate later phenotype or eligibility slide should define the enrolled sample
when selection materially affects applicability.

## Article Slide Grammar

Use a duration-adaptive story, not a fixed template. A typical 15-minute deck is
often 10-14 main slides plus only faculty-useful backup slides. This is a pacing
target, not a content cap: first preserve every thesis-determining and decision-
relevant item, then compress related evidence and shorten delivery rather than
silently omitting interpretation-critical content.

1. Minimal title and citation
2. `Background` or `Introduction`: pathology, natural history, usual management,
   and the decision gap
3. Candidate phenotype and selection pathway
4. Study question, architecture, and intervention sequence
5. Cohort and treatment heterogeneity
6. Primary result with denominators
7. Patient-level or time-course result
8. One or two mechanism-generating technical examples when useful
9. Limitations, evidence boundary, and clinical application
10. Summary or Main Takeaways: population, decisive result, validity boundary,
    and clinical implication

Use backup slides only for material likely to answer a specific faculty question:
technical targeting details, exact discrepancy language, additional source
figures, or secondary methods. Do not add a cohort table when the same values are
already shown more clearly in the main result display. Backup slides do not count
toward timed duration.

Do not spend audience time restating every dossier section. Compress teaching into
the minimum prerequisite sequence needed to understand the decisive result.

### Archetype-Aware Narrative

Let the dossier's paper archetype alter the arc:

- An initial-strategy trial should visibly separate assignment, treatment
  received, crossover/rescue, time course, and treatment burden.
- A procedure-comparison trial should foreground technical fidelity, surgeon or
  center variation, benefit, and complications.
- A failure-map or revision series should lead with operative anatomy, use source
  photographs or diagrams as primary evidence, distinguish revision findings from
  primary-procedure failure rates, and close with an `avoid / inspect / correct`
  operative checklist.
- A prognostic cohort should foreground time horizon, discrimination/calibration,
  and the difference between risk prediction and treatment effect.

This is a narrative grammar, not a requirement for extra slides. Preserve the
paper-specific insight that made the article memorable.

For a preference-sensitive initial-strategy trial, use this sequence as the
default reasoning order when the evidence supports it:

1. Background: pathology, natural history, usual triage, and the decision gap.
2. Candidate phenotype and exclusions.
3. Study ecosystem: randomized, observational, registry, or companion cohorts
   and the distinct inferential role of each.
4. Intervention and comparator as actually delivered.
5. Treatment exposure, adherence, crossover, and assessment schedule.
6. Assignment-based and treatment-received estimands.
7. Longitudinal primary outcomes with uncertainty.
8. Patient-relevant secondary outcomes and harms.
9. Assignment versus treatment-received estimates with the correct causal label.
10. Verified longer-term or companion evidence when it materially changes the
    interpretation.
11. Informative crossover, attrition, and the validity boundary.
12. Main Takeaways: population, comparator, trajectory, validity, and clinical
    application.

Compress adjacent beats when one open evidence layout can answer the same
audience question. Do not omit a beat merely to hit a preferred slide count.

### Salience Budget

Before authoring, rank every candidate result as:

- **Thesis-determining** — changes the central interpretation or practice verdict.
- **Decision-relevant** — changes patient selection, counseling, operative risk,
  or applicability.
- **Faculty-defense** — useful for a likely challenge but not required in the
  timed arc.
- **Administrative** — does not deserve presentation time.

Main slides must be dominated by thesis-determining and decision-relevant data.
Faculty-defense data belong in notes or backup. Administrative results are
omitted. For a typical 15-minute article talk, allocate at least two main slides
to the decisive results and no more main-slide space to background than is needed
to interpret them.

At least one result slide must make the paper's central quantitative contrast
understandable within 10 seconds: population or denominator, effect magnitude,
uncertainty, follow-up, and the correct evidentiary label must be visible or
immediately inferable.

Select one `central_visual` before layout. It may be an exact reconstructed chart,
a participant-flow or treatment-trajectory diagram, a source anatomy figure, or a
compact table. It must be the shortest visual path to the thesis and receive the
largest evidence area in the timed deck. Baseline balance, broad cohort summaries,
and administrative flow do not earn main-slide status unless they materially
change applicability or interpretation.

The salience ranking applies to the complete `coverage_audit`, not merely the
results table. Study selection, the actual comparator, serial outcome trajectory,
or a concurrent cohort can be thesis-determining when omitting it would change
how the audience interprets the effect estimate or applies the paper.

### Slide separation test

Before accepting any main slide, write one sentence explaining why its content
requires separate audience attention. Merge or delete the slide when:

- Its content can be one bullet or subheading on the preceding parent slide.
- It restates an interpretation already visible in a result or limitation slide.
- It repeats a prior result without adding synthesis, clinical application, or
  the required end-of-talk recap.
- Its sentences need presenter orientation before the audience can understand
  what the slide is about.

Every article deck requires one final main slide titled `Summary` or
`Main Takeaways`. It is a concise recall surface, not another evidence slide.
Use three to five parallel, evidence-backed points that recap: the studied
population and comparator, the decisive result or trajectory, the strongest
validity limitation, and the clinical application. Do not introduce a new
estimate, citation, interpretation, or recommendation on this slide. A preceding
clinical-application slide may remain separate when it carries a decision pathway;
otherwise integrate application into the summary.

## Dual-Layer Teaching

Visible slides must address neurosurgeons without sounding simplified. Speaker
notes must support a resident who is new to the paper. Every substantive slide's
notes should include:

- The slide's claim in one sentence
- Explanation of unfamiliar concepts when needed
- Exact quantitative anchors and denominators
- What the visual shows and does not show
- Transition to the next slide
- Likely faculty challenge and bounded answer

Avoid copying dossier paragraphs into notes. Write for oral delivery.

Visible vocabulary should sound natural in a resident-to-faculty neurosurgical
conference. Use precise terms such as treatment contamination, traversing root,
informative crossover, residual confounding, noninferiority margin, or competing
risk when they are the correct concepts. Define unfamiliar terms in notes or at
first use; do not substitute vague language that lowers the academic level.

## Article Asset Extraction

Use the dossier's `Data Worth Showing` and `Figures and Tables Explained` sections
to prioritize assets. Build `asset_manifest.json` with:

```json
{
  "asset_id": "figure-3",
  "kind": "article_figure",
  "source_pdf": "<absolute path>",
  "page": 7,
  "source_label": "Figure 3",
  "output_path": "<scratch asset path>",
  "transformation": "crop only",
  "citation": "Reyes et al., Oper Neurosurg, 2026",
  "destination_slides": ["S09"]
}
```

Rules:

- Render or extract from the archived PDF at presentation resolution.
- Preserve axes, legends, panel labels, meaningful annotations, and aspect ratio.
- Cropping may remove surrounding article prose but not figure content.
- Use `contain`, not `cover`, for scientific figures unless a deliberately selected
  panel crop is declared.
- Rebuild tables as editable PowerPoint tables when exact values are available.
- Rebuild charts only from explicit article values or the validated result ledger.
- Never digitize a plotted value silently. Label any unavoidable approximation.
- Put a readable citation on the slide and full provenance in the manifest.
- Avoid decorative stock imagery when a source figure or clear data display exists.
- Crop away publisher captions and surrounding article prose after preserving the
  scientific panels; move explanatory caption text into speaker notes.
- Split tall multi-patient or multi-panel figures into explicitly declared panel
  crops when the complete figure cannot be read at projected size.
- Prefer editable, exact table reconstructions in the deck's visual system. Split
  dense patient-level tables across backup slides rather than shrinking a source
  screenshot.

## Quantitative Integrity

Add `result_checks` to the deck plan. Every number shown on a slide must be checked
against the dossier result ledger or PDF:

```json
{
  "claim": "Final responder rate",
  "expected": "6/7",
  "actual": "6/7",
  "source": "Article Figure 3",
  "pass": true
}
```

Report absence of confidence intervals or standardized outcomes; do not invent
precision. Distinguish seizure reduction from seizure freedom, reported values
from calculations, and temporality from causal attribution.

## Article Quality Gate

Before the shared deck gate, verify:

- Main-slide coverage ledger is complete.
- The interpretation-critical evidence audit is complete, has no unresolved
  `coverage_risks`, and maps every thesis-determining and decision-relevant item.
- Study ecosystem and companion cohorts are visible when they change selection,
  adherence, causal interpretation, or effect magnitude.
- The intervention and comparator are described as actually delivered, including
  material concomitant treatments, tailoring, rescue, and fidelity limitations.
- Serial outcomes show enough prespecified time points to reveal onset,
  persistence, or convergence when trajectory affects counseling.
- The thesis matches the dossier's data-supported conclusion.
- Every decisive result has numerator/denominator or appropriate dispersion.
- Article figures and tables are legible and source-traced.
- The central result is shown at patient level when a cohort mean conceals
  heterogeneity.
- Limitations are consequence-framed, not a reporting-checklist recital.
- Practice impact identifies the candidate, noncandidate, and evidence boundary.
- All article inconsistencies remain visible in notes or backup material.
- Faculty questions are answerable from notes or backup slides.
- No slide calls uncontrolled evidence proof of synergy, superiority, or safety.
- Methods and selection slides teach the study before critiquing it. Do not use a
  large warning banner for a limitation that belongs later in the appraisal arc;
  keep early caveats in notes unless they are necessary to understand the method.
- The second main slide is titled `Background` or `Introduction`, uses role
  `background`, maps to `Clinical Foundation`, and concisely establishes the
  pathology, natural history, usual management pathway, and study-defining gap.
- Every main slide passes the slide separation test and records a specific
  `separation_rationale` in the deck plan.
- No result table duplicates a clearer patient-level chart.
- The last main slide is titled `Summary` or `Main Takeaways`, contains three to
  five evidence-backed recap points, and includes the clinical application or
  patient-selection boundary.
- The article title slide contains no interpretive alternate subtitle.
- The rendered deck passes the shared visual-design contract, including
  typography, evidence scale, layout rhythm, and citation treatment.
- The Baylor reference alignment was documented when that surface is used, and
  the final deletion pass removed redundant interpretive bands or duplicate
  summary scope without removing citations or uncertainty.
- Every chart legend is native or part of an intact source figure, matches the
  estimand shown, and uses the same treatment labels and colors consistently.
- No rendered title, number, hyphenated term, or single word is fragmented by a
  text-box boundary; no watermarked stock or preview asset remains.
- Main-slide result space reflects the salience ranking; no secondary or
  administrative table displaces a thesis-determining result.
- The central quantitative contrast passes the 10-second comprehension test.
- Literature context identifies what the article contributed, contested, or left
  unresolved rather than displaying a chronology without consequence.
- The visible vocabulary is technically precise for a neurosurgical audience,
  with explanation in notes rather than dilution on slides.
- A resident can answer from the deck and notes: Why was this study needed? What
  are the decisive numbers? What is the strongest validity threat and its bias
  direction? Which patient and operative decision does the paper affect today?

## Vault Presentation Note

The final note must include:

```markdown
**Mode**: Article
**Deck**: [<Title>.pptx](/Users/gabrielreyes/Desktop/<Title>.pptx)
**Source Journal Club**: [[Journal Club/<Short Article Title>]]
**Source PDF**: Journal Club/Sources/<Short Article Title>.pdf
**Duration**: <minutes>
**Thesis**: <data-supported presentation thesis>

## Presentation Arc
## Coverage Ledger
## Slide Outline and Speaker Notes
## Study Design and Methods
## Methods Critique
## Clinical Impact
## Citation List
## Asset Manifest
## Anticipated Questions
## Presentation Risks
## What Not To Say
```

Write only after the real PPTX package passes the shared guard.
