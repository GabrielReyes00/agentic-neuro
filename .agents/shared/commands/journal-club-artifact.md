# Journal Club Artifact And Mastery

Final artifact, validation, and optional learning contract for `/journal-club`.

## Artifact Destination

Write only through `src/journal_club_guard.py`:

```text
/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Journal Club/<Short Article Title>.md
/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Journal Club/Sources/<Short Article Title>.pdf
```

Use a Title Case article title without author names, dates, skill prefixes, or
version suffixes. Do not use an H1. Put YAML only at the bottom.

## Required Dossier Structure

### `## Start Here`

Include these bold labels:

- `**Clinical Question:**`
- `**One-Sentence Thesis:**`
- `**Practice Verdict:**`
- `**Thirty-Second Explanation:**`

Also provide the complete citation, why the article matters, article type, and the
few decisive quantitative anchors. This section must stand alone as a rapid pre-
conference read without overstating the evidence.

### `## Clinical Foundation`

Open with a compact `### Rapid Orientation` that teaches the syndrome, decisive
anatomy, treatment choice, and paper-specific controversy in approximately one
minute of reading. Follow with a `### Resident Deep Model` organized by the causal
or decision chain the paper requires. Assume no paper-specific prior knowledge
while preserving precise neurosurgical vocabulary.

For clinically and surgically oriented papers, the section must connect the
syndrome to the relevant anatomy, diagnostic concordance, operative or procedural
target, selection boundary, and counseling consequence. Do not stop at generic
disease background. Preserve academic terminology; translations should clarify
terms without replacing them.

Use article-appropriate subheadings rather than a fixed mini-textbook template.
For a revision or technical paper, include what the primary surgeon should avoid
creating and what the revision surgeon should inspect. For a strategy trial,
include the clinical trajectory and escalation decision that make crossover or
rescue treatment meaningful. Avoid repeating `Start Here` in expanded prose.

### `## Essential Concepts for This Paper`

Explain only the scales, devices, classifications, methods, and effect measures
needed to understand this article. Use at least two complete translation triplets
when the paper contains unfamiliar technical concepts:

```markdown
**Technical concept:** ...
**Plain-language meaning:** ...
**Why it matters here:** ...
```

### `## Why This Study Exists`

Explain the pre-study evidence, unresolved question, authors' hypothesis, and why
the article was worth publishing or assigning.

### `## Study Architecture`

Describe design, setting, dates, population, selection, intervention/exposure,
comparator, outcomes, follow-up, analysis, funding, and conflicts. Explain what
each design choice permits or prevents the authors from concluding.

### `## Results That Matter`

Use a Markdown table with these columns:

```text
Finding | Reported Result | Interpretation | Source
```

Every decisive result must carry a source locator and a denominator when
applicable. Follow the table with focused prose explaining clinical versus
statistical meaning.

### `## Figures and Tables Explained`

Explain each substantive visual's purpose, interpretation, limitations, and likely
faculty question. Explicitly state when the source package contains no substantive
figure or when an inaccessible supplement limits inspection.

For every presentation-worthy visual, add its proposed presentation job: decisive
result, anatomy/mechanism, selection, limitation, or backup. State whether it
should be shown intact, rebuilt from exact values, split into declared panels, or
omitted because it will not project legibly. Operative photographs and anatomy
diagrams must identify the structure, orientation, technical lesson, and failure
mode rather than serving as illustration alone.

### `## Interpretation`

Separate:

- Authors' conclusion
- Data-supported conclusion
- Overclaim to avoid

### `## Limitations That Actually Matter`

Include only interpretation-changing issues. For each major limitation, use:

```markdown
### <Specific limitation>

**Problem:** ...
**Why it matters:** ...
**Threatened conclusion:** ...
**Does the main finding survive?** ...
```

Do not reproduce reporting checklists or generic complaints about sample size,
retrospective design, or lack of randomization without explaining consequence.

### `## Neurosurgical Relevance`

State patient fit, non-fit, operative/anatomic implications, counseling consequence,
practice consequence, and what should remain uncertain.

### `## Historical and Current Context`

Use separate `### At Publication` and `### Current Context` subsections. Cite the
external literature at the point of claim.

Make the literature lineage explicit rather than listing later papers. Name what
each decisive predecessor or successor contributed, contested, refined, or
superseded, and end with the assigned article's durable contribution and present
evidentiary boundary.

End this section with three explicit sentences: `Before this paper...`, `This
paper added or contested...`, and `Today...`. These are synthesis claims, not a
chronological bibliography.

### `## Presentation Core`

Use these bold labels:

- `**Central Thesis:**` — a defendable central thesis.
- `**Clinical Context Slide:**` — the 3-5 background elements a neurosurgery
  audience needs before the paper, such as pathology mechanism, symptoms,
  diagnostic maneuvers/tests, treatment options, and the specific decision gap.
- `**Data Worth Showing:**` — the data worth presenting.
- `**Central Visual:**` — the single evidence object that should receive the
  strongest visual emphasis, plus why it is the shortest path to the thesis.
- `**Discussion Priorities:**` — the issues worth spending conference time on.
- `**Spoken Arc:**` — a logical verbal sequence.
- `**What Not To Say:**` — unsupported or overstated claims to avoid.

### `## Faculty Defense`

Use article-specific `### Question:` subsections followed by concise answer
outlines. Cover thesis, decisive numbers, study design, important limitations,
clinical applicability, and the practice verdict. Avoid trivia.

### `## Mastery Objectives`

Use testable action verbs. Objectives should cover explanation, reconstruction of
design, quantitative interpretation, critique, neurosurgical application, and
faculty defense.

### `## Source Trace`

Explain the provenance syntax and list source-package limitations. Use these forms
at the point of claim:

```text
[Article PDF p. 6, Table 2]
[Article Figure 1]
[Article Supplement p. 3]
[Calculated from Article Table 2]
[External context: Author Year]
```

Do not attach an article locator to a claim that comes only from external context.

### `## References`

Include the assigned article first, followed by directly used external sources.
Use linked DOI, PubMed, PMC, guideline, registry, or publisher pages. Do not include
sources that support no claim in the dossier.

## Bottom YAML

Required fields:

```yaml
aliases: []
article_title: "<full article title>"
authors: "<author list or compact citation authors>"
journal: "<journal>"
year: 2026
doi: "<DOI or empty string>"
source_pdf: "Journal Club/Sources/<Short Article Title>.pdf"
source_package_status: complete
domain: functional
summary: "<one-line article-specific summary>"
generated: 2026-06-22
skill: journal-club
tags: [skill/journal-club, type/article, domain/functional, source/article]
```

`source_package_status` must be `complete`, `incomplete`, or `preliminary`.
Complete means the full article was locally inspected; it does not imply that every
protocol or supplement exists.

## Quality Gate

Before installation, verify:

1. Article identity and source-package status are accurate.
2. The full available PDF was inspected textually and visually.
3. The foundation precedes complex methods and results.
4. Technical terminology is preserved and translated where needed.
5. Every decisive result includes denominator, magnitude, uncertainty when
   available, and an exact locator.
6. Reported and calculated values are distinguishable.
7. Abstract, body, tables, figures, and supplements were reconciled.
8. Statistical significance is not substituted for clinical meaning.
9. Limitations are consequence-framed and do not drift into checklist audit.
10. Authors' conclusion, defensible conclusion, and overclaim are distinct.
11. Publication-era and current contexts are separated.
12. Practice verdict names the applicable population and evidentiary boundary.
13. Faculty questions are article-specific and answerable from the dossier.
14. References support claims actually made.
15. No learner mastery is inferred from artifact generation.
16. The resident foundation links syndrome, anatomy, pathophysiology, diagnostic
    concordance, treatment selection, operative target, and decision consequence
    wherever applicable.
17. Technical vocabulary is precise enough for a neurosurgical audience and is
    translated rather than diluted.
18. The literature lineage states what preceded, motivated, replicated,
    contradicted, refined, or superseded the article.
19. The dossier explains the article's specific durable contribution rather than
    relying on labels such as landmark or practice-changing.
20. A final adversarial read asks: could a resident use this dossier to explain
    the clinical problem, defend the methods and numbers, localize the operative
    consequence, and answer why the paper matters to neurosurgeons today? Repair
    every unsupported or missing link before installation.
21. `Clinical Foundation` has a genuinely faster orientation layer and a deeper
    resident model; neither merely repeats `Start Here` or the other.
22. The paper's teaching archetype is preserved: strategy trials foreground
    treatment trajectory, failure-map series foreground operative failure points,
    and other designs use their corresponding decision logic.
23. Figures and tables are prioritized by presentation job and projection value,
    including operative/anatomic teaching when it is central.
24. The dossier's opening and Presentation Core prioritize thesis-determining and
    decision-relevant content even when the reference body is comprehensive.

Then run the guard. A structural pass does not excuse weak reasoning; read the
installed dossier end to end and repair content failures before completion.

## Optional Mastery Modes

Artifact generation ends before learner-memory startup. If Gabriel opts in, set one
`SESSION_TS` and run:

```bash
python3 src/study_memory.py startup-recall \
  --profile doc \
  --topic "<article topic>" \
  --doc "Journal Club/<Short Article Title>.md" \
  --session "$SESSION_TS"
```

Read the full dossier; Mastery Objectives are a coverage checksum, not a substitute
for the body.

### Guided Mastery

Build the paper in dependency order:

1. Clinical problem and treatment landscape
2. Why the paper was needed
3. Study architecture
4. Decisive results
5. Interpretation-changing limitations
6. Neurosurgical consequence

Ask one question at a time and stop. Start with a clinical decision or conceptual
thesis, not statistical vocabulary. After each answer, grade briefly, teach the
next needed layer, and ask a deeper follow-up.

### Faculty Defense

Use compressed, adversarial but fair questioning. Require the learner to state:

- The thesis without notes
- Decisive numbers with denominators
- Why the design can or cannot support the claim
- The strongest limitation and its direction
- The applicable patient population
- Whether and how practice should change

### Combined Preparation

Run Guided Mastery to stable conceptual understanding, then Faculty Defense with
reduced scaffolding. Do not start adversarial defense before the foundational model
is coherent.

For every assessed answer, follow `memory-operations.md` with
`--skill "journal-club"` and the document path. Create Anki cards only from
evaluated misses, partial answers, unstable quantitative anchors, and durable
high-yield discriminators. Finish with `end-session`, queue review/check/flush, and
the shared curation rules.
