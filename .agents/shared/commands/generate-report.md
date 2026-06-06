# Generate Report

Produce an encyclopedic, citation-dense reference document on a neurosurgical topic — a personalized textbook chapter that captures the current expert understanding from all available sources. The output is reference truth, not a learner-tailored study aid.

The resident reading this report should not need another source to develop deep, comprehensive understanding of the topic. Density is the primary quality metric.

---

## Role and Output

You are an expert research synthesizer. Your output is a single Markdown file at `Reports/<Title Case Title>.md` in the Obsidian vault. The file is encyclopedic in ambition, operational where the topic warrants, and grounded in citations at the point of every claim.

Do not address the learner. Do not mention PGY level or any individual's prior knowledge. Do not skip foundational material because it might already be known. The report is written for the topic, not for a person.

**Reference exemplar.** The gold-standard output for this skill is `Reports/Sphenoid Wing Meningiomas.md` in the vault — read its first 40 lines if you need a structural and tonal anchor before writing. Match or exceed its density, citation specificity, differentiator coverage, and operative detail. For the opening Clinical Utility & Quick Reference block specifically, follow `Reports/Temporal ICH Management.md` as the structural exemplar.

**Final report shape.** The report body is clinical reference prose from the first H2 through `## Mastery Objectives`; workflow scaffolding stays in `data/Sessions/<Title>/` and in the final user summary.
- When RAG was used, place the sanctioned callout immediately above the opening H2: `> [!info] RAG Supplemented`, followed by a one-line blockquote description.
- The vault file starts with `## Clinical Utility & Quick Reference`; the filename is the title, and bottom YAML is the only metadata block.
- Write for the topic itself, without second-person address, learner-state assumptions, PGY-level qualifiers, or assumed-knowledge skips.
- Express evidence as specific cited claims. Generic filler phrases such as "studies suggest" or "research has shown" should be replaced by the source-backed finding.
- Wikilinks come only from the verified Step 2 vault scan.
- PMID and DOI values are copied verbatim from tool output.
- Regenerating an existing report updates the existing Title Case file in place.

---

## Modular Workflow Authority

This file is the public command contract and orchestrator. Detailed post-retrieval instructions live in focused modules. Read the relevant module freshly when reaching each checkpoint:

- `.agents/shared/commands/generate-report-research-plan.md` — query best practices, topic-archetype classification, required/optional/not-applicable report domains, and planned retrieval queries.
- `.agents/shared/commands/generate-report-research.md` — `source_cards.jsonl`, non-RAG source-card normalization, and `coverage_ledger.json`.
- `.agents/shared/commands/generate-report-synthesis-map.md` — compact-but-dense `report_knowledge_map.json` built from source cards and the coverage ledger.
- `.agents/shared/commands/generate-report-finalize.md` — write from the synthesis map, run `report_validator.py --coverage-ledger`, update INDEX, concepts, memory, and final user summary.
- `.agents/shared/commands/concept-extraction.md` — shared concept-card rules for post-write concept extraction.

Do not copy the full `/intraoperative-guide` workflow. Reports need structured coverage control, not mandatory reviewer subagents, operative verdict chains, or attending-question gates. Optional review is appropriate only for unusually large, high-stakes, or controversy-heavy reports.

## Structured Artifact Rule

The final report must be written from structured post-retrieval artifacts, not directly from raw RAG dumps. Raw retrieval output may be consulted for a narrow citation dispute, but ordinary synthesis flows through:

1. `report_research_plan.json`
2. `source_cards.jsonl`
3. `coverage_ledger.json`
4. `report_knowledge_map.json`
5. final report prose

If `coverage_ledger.json` contains any required block with `status: gap`, do not write the final report. Run targeted retrieval or explicitly repair scope until the ledger has no required gap statuses. `report_validator.py --coverage-ledger` enforces this as a final gate.

---

## Pre-Research Setup

### Step 0: Resolve the topic

Derive a Title Case slug from the user's request. If the topic is genuinely ambiguous (e.g., "report on aneurysms" with no localizer or context), ask one clarifying question. Otherwise infer scope and proceed.

If `Reports/<Title>.md` already exists, treat the request as a regeneration: overwrite the file in place, refresh INDEX.md, and update concept cards whose source content changed. Do not create date-stamped variants or `_v2` files.

Create the report session directory at the start of the run:

```bash
cd /Users/gabrielreyes/agentic-neuro && \
mkdir -p "data/Sessions/<Title>"
```

### Step 1: Related-report discovery (silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py summary --lens formal --topic "<topic>" --limit 8 --scaffold-limit 2 --include-curated
```

The sole purpose of memory summary here is to surface existing related memory/report anchors on overlapping subject matter so the new report can reference them via wikilink rather than duplicate their coverage. This is the formal lens: service-origin gaps and site conventions are excluded from report discovery. `--include-curated` lets curated cross-session summaries also surface — useful for noticing if a thematic pattern (e.g., "stroke BP thresholds remain a fault line") suggests the new report should foreground that material. Do not use summary to assess what the learner knows or to compress depth — these reports are not learner-tailored.

### Step 2: Vault scan for cross-citation targets (silent)

```bash
VAULT="/Users/gabrielreyes/Documents/Obsidian/agentic-neuro"
find "$VAULT/Reports" "$VAULT/Operative Guides" "$VAULT/Study Material" "$VAULT/Concepts" -type f -name "*.md" -print 2>/dev/null
```

Identify wikilink targets relevant to this topic. Use them as inline references and citations within the prose, and list them in a final `## Related in This Vault` section.

---

## Quality Contract

The report MUST contain the following content elements. The agent decides depth, ordering, prose form, and section names based on what the topic demands. A vascular pathology, a functional indication, a device, an anatomic concept, a controversy, and a technique each shape the structure differently — let the topic dictate, not a template. The opening block below is the single exception: it is fixed in structure and naming.

- **Opening block** — every report opens with a single H2 `## Clinical Utility & Quick Reference` containing, in this exact order:
    1. A blockquoted TL;DR: `> **TL;DR:** …` (3–6 sentences).
    2. `### When to Reference This Report` — bulleted list of triggering clinical scenarios.
    3. `### Key Numbers at a Glance` — table with header `| Parameter | Value | Context | Source |` (≥10 rows per the floor below).
    4. `### Decision Framework` — numbered, named steps with bolded step labels (`1. **Step Name:** …`). Not a code block; not a flowchart.

    `Reports/Temporal ICH Management.md` is the structural exemplar for this block.
- **TL;DR** — three to six sentences capturing the most important current understanding of the topic (renders as the blockquote in the opening block above).
- **Key Numbers Table** — quantitative anchors a reader should be able to recall: incidence, thresholds, outcome rates, named values, with a citation per row.
- **Differentiator** — explicit contrast with related entities, approaches, or concepts the topic could be confused with or conflated against. Broad framing accommodates pathology differentials, technique comparisons, device alternatives, anatomic neighbors, indication overlaps. Organize by the feature that distinguishes (e.g., "DBS for OCD targets the ventral capsule/ventral striatum, whereas ablative anterior capsulotomy lesions the anterior limb — different mechanism of effect, different side-effect profile, different reversibility").
- **Operative walkthrough** when the topic is procedural — among the most important sections when applicable. Step sequence, named maneuvers and their indications, intraoperative tests of success (electrophysiology, ICG, neuromonitoring expectations), bail-outs, what to do when bleeding obscures landmarks or anatomy is anomalous, closure considerations.
- **Common failure modes and pitfalls** — specific known errors, complications-from-error, sources of misinterpretation. Concrete (e.g., "the most common identification error in AChA clipping is mistaking a lenticulostriate perforator for the AChA itself; ICG can be falsely reassuring if perfusion is preserved through collaterals"), not generic ("be careful with retraction").
- **Evidence quality labels** on every major recommendation — Level I/II/III/IV, or Guideline / RCT / Cohort / Case Series / Expert Consensus. The reader must be able to tell at a glance whether a recommendation is trial-grade or opinion-grade.
- **Effect-size magnitudes** on every cited trial — absolute risk reduction, NNT, mRS shift, hazard ratios, odds ratios. Never "significant" alone.
- **Mechanism → consequence chains** for any molecular, genetic, or pathophysiologic content. No orphan facts. If a mutation, pathway, or physiologic principle is named, its functional and clinical consequence is stated in the same passage.
- **Mastery Objectives** — a final `## Mastery Objectives` section defining what a reader should be able to do with the report's knowledge under clinical, operative, or oral-board pressure. Use testable action verbs; do not address Gabriel directly.
- **Cross-references** — wikilinks to existing vault notes woven through the prose at the point of relevance, plus a final `## Related in This Vault` section listing the most relevant prior reports, guides, and concepts with one line on the relationship.

If a Mandatory Element is genuinely not applicable to a specific topic (e.g., operative walkthrough on a pure pharmacology report, mechanism→consequence chains on a pure operative anatomy report), state the omission briefly in your self-audit reasoning and proceed.

**Quality floors are content-driven, not count-driven.** A report is incomplete when it lacks the clinical density naturally required by its topic, even if it passes structural validation. Do not use arbitrary citation counts, row counts, line counts, or fixed numbers of pitfalls as a substitute for expert coverage.

Use these topic-shaped floors during self-audit:

- A clinical emergency or ICU topic is incomplete without management-changing thresholds, bedside monitoring parameters, escalation triggers, lesion-level physiology, predictable complications, and handoff-ready failure modes.
- A procedural or operative topic is incomplete without approach logic, anatomy-risk relationships, key maneuvers, intraoperative tests of success, bailouts, and complication mechanisms.
- A pathology or differential topic is incomplete without discriminators against close mimics, natural history, imaging patterns, management consequences, and common diagnostic traps.
- A physiology, molecular, or anatomy topic is incomplete without mechanism-to-consequence chains that explain how the fact changes exam interpretation, imaging, treatment, prognosis, or complications.
- A controversy or evidence-review topic is incomplete without evidence strength, population boundaries, effect size when available, and practical interpretation of conflicting sources.
- Any report is incomplete if useful granular source detail was compressed into generic claims, if high-stakes numbers lack source verification, or if clinical physiology and operative bedside detail were replaced by workflow commentary.

The Sphenoid Wing Meningiomas reference exemplar remains the calibration point.

## Research Principles

Follow the structured research and synthesis process defined in the child modules:

1. **Checkpoint 1: Research Plan** — Read `.agents/shared/commands/generate-report-research-plan.md`. Build `data/Sessions/<Title>/report_research_plan.json` before retrieval, classifying the archetype and customizing coverage domains.
2. **Checkpoint 2: Structured Research** — Read `.agents/shared/commands/generate-report-research.md`. Run textbook RAG (`lance_retriever.py compare --card-json`) and PubMed/guideline queries to produce `source_cards.jsonl` and `coverage_ledger.json`. Ensure no required domains are marked as a `gap`.
3. **Checkpoint 3: Synthesis Map** — Read `.agents/shared/commands/generate-report-synthesis-map.md`. Build `data/Sessions/<Title>/report_knowledge_map.json` to plan integrated claims, citations, key numbers, differentiators, pitfalls, and provenance tiers (`source_grounded`, `model_knowledge_verified`, `model_knowledge_verify`).

### Core Research Rules

* **Textbook RAG vs. Literature**: Weigh textbook RAG for anatomy and classic management; use PubMed/PMC for current guidelines, trials, and controversies. Web search is for primary non-published documents (e.g. guidelines, device specs).
* **Citations and Hyperlinks**: Cite all claims at the point of claim. Clickable links are required for journal/trial sources in both the text and the Key Numbers table Source column: wrap author-year labels in markdown links to PubMed/DOI URLs. Textbook references remain plain text. Do not attach PubMed links to textbook labels.
* **Provenance Tiering**: Clearly tier claims. Label unconfirmed model knowledge as `model knowledge — verify` and flag high-stakes specifics with `⚠`. Never attach fabricated citations to verify-tier content.
* **Integrate & Densify**: Synthesize across sources instead of listing them serially. Keep the tone academic, avoiding workflow/meta commentary in final clinical prose.

---

## Self-Audit Before Write

Before final write, read your draft end-to-end and verify:
- **Quality Contract & Floors**: All mandatory elements are present and conform to the Quality Contract rules and content-driven quality floors.
- **Integrity & Specificity**: Prose is dense, specific, and academic. All links and PMIDs/DOIs are hyperlinked. Provenance tiering is cleanly applied, with unverified claims clearly marked.
- **Wikilinks & Mastery Objectives**: Wikilinks resolve to verified targets from the vault scan; Mastery Objectives are testable and action-oriented.

If draft fails any criteria, the coverage ledger contains a required `gap`, or you find the content below the Quality Floor, run additional targeted searches and rewrite the sections before writing the file (Stop-and-research protocol).

---

## Finish

Before final write and verification, read `.agents/shared/commands/generate-report-finalize.md` for detailed execution instructions.

1. **Write & Validate**: Persist to `Reports/<Title Case Title>.md` without H1 and with YAML at the bottom. Run `report_validator.py` with the `--coverage-ledger` flag.
2. **Update Index & Extract Concepts**: Rebuild the index (`src/index_builder.py`) and extract 2–5 new concept cards per `.agents/shared/commands/concept-extraction.md`.
3. **Log to Memory**: Record the report anchor using `study_memory.py log-answer` (with `skill="generate-report"`) and close with `study_memory.py end-session` including a highly specific `--next-strategy`.
4. **Surface**: Present the TL;DR, file path, source distribution, Quality Contract checklist, and crosslinks to the user. Do not print the report body in chat.
