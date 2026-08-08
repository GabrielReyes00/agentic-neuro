# Journal Club Analysis

Focused analysis contract for `/journal-club`. Use after intake and before writing
the final dossier.

## 1. Inspect The Complete Source Package

Treat PDF text extraction as an index, not as the paper itself.

1. Record file hash, byte size, page count, embedded-text status, and article
   identity.
2. Extract text page by page.
3. Render every page to images and visually inspect the full article, including
   tables, figures, captions, footnotes, equations, and disclosures.
4. Inspect every supplied supplement. Follow article links to protocols,
   registries, statistical analysis plans, appendices, and supplemental tables
   when they materially affect interpretation.
5. Reconcile title, authors, journal, year, DOI, PMID when assigned, article type,
   funding, conflicts, and study dates against authoritative metadata.
6. Mark the package `complete`, `incomplete`, or `preliminary`.

Do not infer a missing table cell, denominator, method, or outcome from nearby
language. Record extraction uncertainties in `source_manifest.json`.

## 2. Build The Article Map Before Prose

Capture:

- Clinical problem, knowledge gap, and authors' hypothesis.
- Study design, setting, enrollment dates, centers, and follow-up.
- Population, inclusion/exclusion criteria, selection pathway, and sample size.
- Intervention or exposure, comparator, procedural variation, and cointerventions.
- Primary, secondary, safety, subgroup, and exploratory outcomes.
- Outcome definitions, adjudication, assessment schedule, and analysis population.
- Sample-size rationale, statistical model, adjustment variables, missing-data
  strategy, multiplicity, sensitivity analyses, and subgroup methods.
- Participant flow, crossover, rescue treatment, withdrawals, and loss to follow-up.
- Funding, conflicts, and authors' stated conclusion.

For case reports, case series, technical notes, and translational studies, replace
inapplicable fields with design-appropriate questions rather than forcing PICO.

## 3. Teach The Foundation Before The Methods

Assume a medically literate intern who has not read the paper and may not know the
paper-specific disease model or literature.

Build the minimum foundation required to understand the study:

- Disease, procedure, or decision under study.
- Relevant anatomy and pathophysiology.
- Standard diagnostic and treatment pathway.
- Why current options fail or remain controversial.
- Outcomes that matter to patients and neurosurgeons.
- Essential classifications, scales, devices, and statistical concepts.

Keep the foundation proportional to the article. It should let the learner enter
the paper, not become a separate encyclopedic report.

### Neurosurgical Audience Calibration

`Intern-accessible` defines dependency order, not a ceiling on vocabulary or
depth. Write for a neurosurgery resident who must present to residents and
faculty:

- Use the precise clinical, anatomical, operative, methodological, and
  statistical term first. Translate it at first use when needed; do not replace
  it with a less precise colloquial substitute.
- Build the causal chain from anatomy/pathophysiology to symptom phenotype,
  diagnostic concordance, treatment selection, operative target, outcome choice,
  and clinical consequence.
- Distinguish what a procedure technically accomplishes from what the study can
  establish about patient benefit.
- State emergency, elective, and noncandidate boundaries when they materially
  differ.
- Include procedure-specific risks, failure modes, and reintervention logic when
  they affect counseling or interpretation.

Before drafting, create a short `resident_foundation_check` in the article map:

```text
clinical syndrome -> relevant anatomy -> pathophysiology -> diagnostic
concordance -> treatment landscape -> operative target -> decision boundary
```

Every applicable link must be taught somewhere in the dossier. A glossary-like
list of definitions does not satisfy this requirement.

Build the foundation in two reading layers:

1. **Rapid orientation** — the syndrome, decisive anatomy, treatment choice, and
   article-specific controversy in roughly one minute of reading.
2. **Resident deep model** — the mechanism, diagnostic concordance, operative or
   procedural target, failure modes, selection boundaries, and counseling logic
   needed to explain the paper to faculty.

The rapid layer must not dilute terminology. The deep layer must not repeat the
rapid layer in longer prose. Prefer a causal chain, decision pathway, anatomy map,
or compact discrimination table over a sequence of background paragraphs.

When the dossier will likely feed a journal-club PowerPoint, also identify the
smallest clinical-context frame the audience needs on slides: pathology or
mechanism, signature symptoms, exam or diagnostic tests, standard treatment
choices, and the article-specific decision gap. This is a scope note for later
presentation design, not permission to expand the dossier into a broad review.

Use precise terminology followed by plain-language interpretation. Explain a
method against the actual paper:

```text
what it is -> why the authors used it -> assumptions -> whether those assumptions
appear satisfied -> how violation would change the conclusion
```

## 4. Reconstruct The Results

Build `result_ledger.json` before narrative synthesis. For every outcome that could
change the presentation thesis, capture:

- Outcome name and prespecified role.
- Analysis population and denominator.
- Event counts or raw group values.
- Effect magnitude and uncertainty.
- Follow-up interval.
- Adjusted versus unadjusted status.
- Exact PDF page, table, figure, or supplement location.
- `reported`, `calculated`, or `external_context` provenance.
- Statistical interpretation.
- Clinical interpretation.

Never report a p-value alone. When justified by the available data, calculate
absolute risk difference, NNT/NNH, or other simple clinically interpretable
quantities; label them as calculations. Do not reverse-engineer unavailable data.

Design-specific checks:

- **Binary outcomes:** numerator, denominator, absolute and relative effect.
- **Continuous outcomes:** baseline, follow-up, between-group difference,
  dispersion, and clinical importance.
- **Time-to-event:** number at risk, censoring, follow-up, hazard ratio,
  proportional-hazards assumptions, and competing risks.
- **Diagnostic:** threshold, sensitivity, specificity, likelihood ratios, and
  reference standard.
- **Meta-analysis:** eligible-study logic, effect model, heterogeneity, dominant
  studies, prediction interval when available, and publication-bias limits.
- **Case series:** individual-patient trajectories, denominator integrity,
  follow-up heterogeneity, outcome ascertainment, and whether averages conceal
  nonresponders.

Also classify the paper's teaching archetype and preserve the corresponding
insight rather than forcing every paper into one generic RCT narrative:

- **Initial-strategy trial:** distinguish assignment strategy from treatment
  received; treat crossover, rescue treatment, time to escalation, and treatment
  burden as clinically meaningful outcomes when appropriate.
- **Procedure-comparison trial:** separate intervention fidelity, technical
  variation, surgeon effects, and patient-reported benefit.
- **Failure-map or revision series:** teach the operative anatomy, denominator
  boundary, recurring technical failure points, and what a primary surgeon should
  avoid creating or a revision surgeon should deliberately inspect.
- **Natural-history or prognostic cohort:** distinguish prediction from treatment
  effect and make time horizon, competing events, and calibration explicit.
- **Diagnostic study:** connect threshold performance to the actual surgical
  decision and consequences of false-positive and false-negative classification.

Record the archetype in the article map and use it to shape `Presentation Core`,
faculty questions, and neurosurgical consequences.

Reconcile the abstract, main text, tables, figures, and supplement. Flag
discrepancies rather than choosing the most favorable value.

## 5. Audit Tables And Figures

For each substantive table or figure, state:

- The question it answers.
- How to read it.
- What it demonstrates.
- What it does not demonstrate.
- Relevant denominators, adjustment, censoring, scales, or subgroup interaction.
- The likely faculty challenge.

Do not devote equal space to administrative tables or decorative figures. Prioritize
visuals that determine interpretation or presentation value.

## 6. Use Design-Aware Methodological Triage

Classify the design silently and inspect the applicable risks. Reporting guidelines
are discovery aids, not the learner-facing organizing principle. Do not calculate a
checklist score or inventory reporting compliance.

Surface a methodological issue only when at least one is true:

1. It can change the direction or magnitude of the result.
2. It weakens attribution of outcome to intervention or exposure.
3. It limits applicability to the patients or practice being discussed.
4. It explains an important discrepancy or uncertainty.
5. It is a likely substantive faculty discussion point.

Reporting omissions matter only when they block interpretation: undefined
endpoints, missing participant flow, unclear missing-data handling, absent
prespecification, inaccessible protocol/supplement, or inability to distinguish
confirmatory from exploratory analysis.

For each surfaced limitation, express:

```text
Problem -> mechanism -> probable bias direction -> threatened conclusion ->
whether the main finding survives
```

### Neurosurgery-Specific Threats

Consider when applicable:

- Confounding by indication and anatomy-based selection.
- Disease-severity, eloquence, surgical-candidacy, and referral-center selection.
- Surgeon/center volume, learning curve, and treatment-era effects.
- Procedural heterogeneity and cointerventions.
- Crossover, rescue therapy, and treatment optimization after baseline.
- Imaging definitions, electrographic definitions, and adjudication.
- Outcome-assessor bias and subjective outcome measurement.
- Death or reoperation as competing events.
- Follow-up duration, differential attrition, and informative censoring.
- Generalizability beyond a specialized multidisciplinary center.

Do not criticize unavoidable features generically. Explain the actual consequence
for this paper.

## 7. Calibrate The Conclusion

Write three separate propositions:

1. **Authors' conclusion** — accurately represented.
2. **Data-supported conclusion** — the strongest claim the design and results can
   defend.
3. **Overclaim** — the tempting claim the study cannot establish.

Then assign a bounded practice verdict:

- Practice-changing now
- Supports an existing practice
- Changes counseling or selection
- Establishes or preserves equipoise
- Hypothesis-generating
- Historically important but superseded
- Not applicable to current practice

Name the population, setting, and evidence boundary. Avoid causal language for
uncontrolled observational evidence.

## 8. Build Publication-Era And Current Context

Keep two clocks separate:

### At Publication

- What was standard practice?
- What landmark evidence preceded the article?
- What gap did the study reasonably attempt to fill?
- Why would faculty have selected it then?

### Current Context

- What later studies replicated, contradicted, refined, or superseded it?
- Did guidelines, devices, techniques, or outcome definitions change?
- Does the original inference still hold?

Prioritize primary studies, formal guidelines, registries, and authoritative
publisher material. Label editorials and reviews as interpretation, not primary
evidence. Do not use a later paper to rewrite the historical rationale.

Build a literature-lineage ledger before prose. For each source that materially
frames the assigned article, record:

```text
source -> design/population -> decisive finding -> limitation -> relationship to
assigned article (preceded, motivated, replicated, contradicted, refined, or
superseded) -> present-day consequence
```

The final synthesis must answer both questions explicitly:

1. What could the field reasonably believe immediately before this paper?
2. What did this paper add, contest, or leave unresolved after later evidence?

Do not call an article landmark, practice-changing, or famous without naming the
specific evidentiary contribution that earned that status.

## 9. Translate To Neurosurgical Consequence

Answer explicitly:

- Which patients resemble the study population?
- Which patients do not?
- What anatomy, pathology, or operative constraint drives selection?
- Does the paper change resection, approach, timing, device use, counseling,
  surveillance, prognosis, or multidisciplinary decision-making?
- What would a neurosurgeon do differently, if anything?
- What should remain uncertain?

The presentation thesis should emerge from this consequence, not from the abstract's
last sentence.

## 10. Rank The Teaching Payload

Before drafting the dossier, rank candidate content as:

- **Thesis-determining** — changes the central interpretation or practice verdict.
- **Decision-relevant** — changes selection, counseling, operative conduct, or
  applicability.
- **Foundation-critical** — required to understand the thesis-determining data.
- **Faculty-defense** — useful for a likely challenge but not necessary for the
  first-pass explanation.
- **Reference-only** — worth preserving but not worth conference time.

Use this ranking twice: first to order the dossier, then to define the later deck
handoff. The dossier may preserve reference depth, but its opening and Presentation
Core must remain dominated by thesis-determining and decision-relevant material.
