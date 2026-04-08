---
name: generate-report
description: Multi-agent research report generator — decomposes a neurosurgical topic into parallel web-research agents, supplements with textbook RAG, and synthesizes a comprehensive reference report. Invoke via /generate-report or when the user explicitly requests a full research report — "generate a report on", "research report on", "comprehensive review of". For general questions about a topic, answer from model knowledge instead.
---

# /generate-report — Multi-Agent Research Report Generator

Decompose a neurosurgical research topic into parallel web-research workstreams, execute them, supplement with textbook RAG for foundational context, and synthesize a single comprehensive reference report.

**Output**: `~/Documents/Obsidian/agentic-neuro/Reports/<topic_slug>.md`
**Philosophy**: Web-primary (current, published evidence) → textbook-supplemental (foundational/historical anchoring) → single consolidated report.

---

## Phase 0: Pre-Flight (Silent)

> Shell prefix: per CLAUDE.md § Shell Prefix. All commands below assume the prefix.

Run pre-flight to get learner context and check for prior reports:
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && ./src/preflight.sh "$QUERY"
```

Read `data/Sessions/learner_context.json`. Note `suggested_depth`, `concepts_unknown[]`, `confusable_pairs[]` — these inform depth calibration for the report. If related prior reports exist in the vault, note them for cross-referencing in Phase 5.

---

## Phase 1: Plan the Research

This is the most intellectually demanding phase. You are an expert research architect — the quality of the final report depends entirely on how well you decompose the topic.

### Step 1.1: Classify the Topic

Determine the **topic archetype** — this guides module selection. Common archetypes (but not an exhaustive list — create new ones when needed):

| Archetype | Example |
|---|---|
| Surgical Procedure / Approach | Pterional craniotomy, endoscopic third ventriculostomy |
| Pathology / Disease Process | Glioblastoma molecular subtypes, moyamoya disease |
| Biomedical Device / Technology | DRG stimulation, laser interstitial thermal therapy |
| Pharmacology / Therapeutics | Bevacizumab in recurrent GBM, nimodipine in SAH |
| Molecular / Genetic Mechanism | IDH mutation in gliomas, EGFR amplification pathways |
| Anatomy / Neuroanatomy | Cavernous sinus microsurgical anatomy |
| Clinical Syndrome / Presentation | Normal pressure hydrocephalus, trigeminal neuralgia |
| Emerging Research / Investigational | CAR-T therapy for GBM, brain-computer interfaces |
| Outcomes / Evidence Synthesis | Outcomes of SRS vs microsurgery for vestibular schwannoma |
| Quality / Systems | Surgical site infection prevention, enhanced recovery protocols |

### Step 1.2: Select Content Modules

From the module pool below, select **5–8 modules** appropriate for this topic. You may rename, combine, split, or create entirely new modules when the pool doesn't fit. The pool is a starting scaffold, not a constraint.

**Module Pool:**

| Module | Select When |
|---|---|
| Epidemiology & Clinical Significance | Almost always — establishes scope and relevance |
| Pathophysiology / Mechanism of Action | Disease, syndrome, drug mechanism, any "how does it work" |
| Molecular & Genetic Basis | Genetics, molecular biology, targeted therapy, biomarkers |
| Anatomy & Surgical Anatomy | Procedures, approaches, anatomical topics |
| Clinical Presentation & Diagnosis | Disease, syndrome, clinical decision-making |
| Classification & Grading Systems | Tumors, injuries, malformations, severity scales |
| Imaging & Diagnostic Workup | When imaging drives clinical decisions |
| Surgical Technique & Approach | Procedures, operative topics |
| Device Overview & Specifications | Biomedical devices, implants, neuromodulation |
| Pharmacology & Dosing | Drug-focused or when medical management is central |
| Comparative Analysis | When multiple options exist (approaches, devices, drugs) |
| Evidence Base & Landmark Trials | Always — what RCTs, meta-analyses, guidelines exist |
| Complications & Management | Procedures, devices, treatments |
| Outcomes & Prognosis | Disease/treatment evaluation, natural history |
| Current Guidelines & Consensus | When society guidelines exist (AANS, CNS, AAN, NCCN) |
| Emerging Research & Future Directions | Always for investigational; selective for established topics |
| Clinical Decision Framework | When the topic informs real clinical decisions |

**Module selection reasoning**: For each selected module, write one sentence explaining why it's included and what it should cover. This reasoning becomes part of the agent prompt, ensuring agents understand the *purpose* of each section — not just the title.

### Step 1.3: Decompose into Agent Workstreams

Split the selected modules across research agents based on topic complexity. Do not artificially cap the agent count — use as many as needed for thorough coverage:
- **Narrow/focused topic** → 2–3 agents
- **Medium topic** → 3–4 agents
- **Broad/comprehensive topic** → 4–6 agents

**Every topic also gets a dedicated Historical Context agent** (see below) — this is in addition to the module-based agents.

Each agent gets:
- A clear **scope** (non-overlapping, but with explicit overlap permissions for shared context like anatomy that two agents both need)
- **3–6 modules** to research and write
- A **target comprehensiveness level**: comprehensive prose, not bullet summaries. Each module section should be 300–800 words of substantive content.

**Agent scope design principles:**
- Group modules that share source domains (e.g., "mechanism + molecular basis + pharmacology" are often from the same papers)
- Separate modules that require different source types (e.g., "device specs" needs manufacturer sites, "landmark trials" needs PubMed)
- Give every agent at least one "anchor module" they can start with immediately (e.g., epidemiology, basic mechanism) to avoid cold-start paralysis
- If the topic involves a device or drug: one agent should focus specifically on the device/drug (specs, FDA status, trials) while another handles the clinical context (indications, patient selection, outcomes)

### Step 1.4: Present the Plan

Format the plan clearly for user review:

```
## Research Plan: [Topic]

**Topic Type:** [archetype]
**Agents:** [N] research agents + 1 synthesis pass
**Estimated scope:** Comprehensive reference report

### Selected Modules
1. [Module name] — [why included, what it covers]
2. [Module name] — [why included, what it covers]
...

### Agent 1: [Descriptive Name]
**Scope:** [1-2 sentence scope]
**Modules:**
- [Module A]
- [Module B]
- [Module C]
**Primary sources:** [PubMed, UpToDate, society guidelines, manufacturer, etc.]

### Agent 2: [Descriptive Name]
**Scope:** [1-2 sentence scope]
**Modules:**
- [Module D]
- [Module E]
**Primary sources:** [...]

[...repeat for each agent...]

### Historical Context Agent (always included)
**Scope:** Historical evolution of the topic — how understanding, techniques, or treatments developed over time. Seminal papers, paradigm shifts, abandoned approaches, and the intellectual lineage leading to current practice.
**Modules:**
- Historical Evolution & Milestones
**Primary sources:** PubMed (historical reviews, anniversary articles), WebSearch for seminal papers and biographical context

### Post-Research
- **Textbook RAG pass:** LanceDB retrieval for foundational/historical context
- **Synthesis:** Merge all agent findings + historical context + textbook context into single report
- **Output:** reports/[topic_slug].md
```

### Step 1.5: Wait for User Approval

**Do NOT proceed until the user confirms the plan.** They may want to:
- Add/remove/rename modules
- Adjust agent scopes
- Change the number of agents
- Add specific questions or angles they want covered
- Specify emphasis areas

---

## Phase 2: Launch Research Agents

Once the user approves:

### Step 2.1: Create Temp Scratch Directory

```bash
mkdir -p /tmp/neuro-report-$(date +%s)
```

Store the temp directory path for cleanup later.

### Step 2.2: Launch All Research Agents in Parallel

Launch each agent using the Agent tool with `run_in_background: true`, `subagent_type: "general-purpose"`, and `model: "sonnet"`.

Each agent prompt MUST include ALL of the following:

**A. Research Context Block:**
```
RESEARCH TOPIC: [full topic]
YOUR SCOPE: [agent's specific scope]
YOUR OUTPUT FILE: [absolute path to temp file, e.g., /tmp/neuro-report-XXXXX/agent-1-[name].md]

You are a research agent investigating [scope] as part of a comprehensive neurosurgical research report on [topic]. Your findings will be merged with other agents' work into a single consolidated report. Write with the depth and precision expected of an academic neurosurgery review article.
```

**B. Module Instructions:**
```
MODULES TO RESEARCH AND WRITE (in order):

## 1. [Module Name]
PURPOSE: [why this module exists and what it should cover — from Step 1.2]
TARGET DEPTH: 300-800 words of substantive prose with inline citations.
SUGGESTED SEARCH ANGLES: [2-3 specific search queries or angles to investigate]

## 2. [Module Name]
...
```

**C. Source Priority and Constraints:**
```
SOURCE PRIORITY (search in this order):
1. PubMed / PubMed Central — landmark trials, systematic reviews, meta-analyses
2. Society guidelines — AANS, CNS, AAN, NCCN, AHA/ASA (search their sites directly)
3. UpToDate — current clinical recommendations (via WebSearch, often accessible in snippet form)
4. Cochrane Library — systematic reviews
5. ClinicalTrials.gov — ongoing trials, recent completions
6. Manufacturer / FDA — device specs, 510(k) clearances, PMA data (only for device/drug topics)
7. NeurosurgeryAtlas.com — surgical technique details (only for procedural topics)
8. Peer-reviewed journal articles — via WebSearch for specific claims

DO NOT USE: Wikipedia, patient-facing sites (WebMD, Mayo patient pages), blog posts, social media, predatory journals, or AI-generated summaries.

CITATION FORMAT: Every factual claim must have an inline citation. Use this format:
- Published literature: [Author et al., Year](URL) or [Author et al., Year, Journal] if no URL
- Guidelines: [Society Abbreviation, Year](URL)
- Device/FDA: [Manufacturer/FDA, Year](URL)
- UpToDate: [UpToDate: "Topic Name", accessed YYYY-MM-DD]

If you cannot find a primary source for a claim, explicitly mark it: *[citation needed — unable to verify]*. Never fabricate citations.

PUBMED MCP TOOLS (use these for structured literature search):
You have access to PubMed MCP tools. Use them as your PRIMARY search method for medical literature:
- mcp__91fa504c-4473-41b3-a98d-e4b135b85490__search_articles — search PubMed with structured queries (use MeSH terms when possible)
- mcp__91fa504c-4473-41b3-a98d-e4b135b85490__get_article_metadata — get full metadata (authors, abstract, DOI, journal) for specific PMIDs
- mcp__91fa504c-4473-41b3-a98d-e4b135b85490__get_full_text_article — retrieve full text from PubMed Central (PMC) when available

SEARCH STRATEGY: Start each module with a PubMed MCP search using MeSH terms, then supplement with WebSearch for guidelines, device specs, or sources not indexed in PubMed. PubMed MCP gives you structured, reliable metadata — prefer it over WebSearch for journal articles.
```

**D. Write Protocol:**
```
CRITICAL WRITE PROTOCOL — READ BEFORE DOING ANYTHING:

The ONLY acceptable pattern is: Search → Write → Search → Write → Search → Write.
NEVER: Search → Search. NO EXCEPTIONS.

After EVERY search or web fetch, IMMEDIATELY write what you learned to your output file.
If you do two searches in a row without writing to your file, you are violating protocol.

Work through your modules IN ORDER. For each module:
1. Do ONE search or web fetch
2. IMMEDIATELY write findings to your file under that module heading
3. Do another search if needed for the same module
4. IMMEDIATELY update your file with additional findings
5. Only move to the next module after the current one has substantive content

If a web fetch returns a 403 or empty result:
- Write what you have so far
- Try ONE alternative URL or search query
- Write again
- If still blocked, note the gap and move on — do not spiral

WHEN FINISHED: Write "STATUS: COMPLETE" as the very last line of your file.
```

**E. Quality Standards:**
```
QUALITY STANDARDS:
- Write in academic prose, not bullet lists. Each module should read like a section of a review article.
- Include specific numbers: sample sizes, effect sizes, p-values, confidence intervals, doses, measurements.
- Name specific trials, authors, and years — not "studies have shown."
- For comparative claims, state the comparison explicitly: "X showed improvement over Y (HR 0.72, 95% CI 0.58-0.89, p=0.003)."
- For devices: include model names, manufacturers, FDA clearance/approval dates, and key specifications.
- For drugs: include mechanism, dose, route, frequency, duration, and key trial data.
- Address controversies explicitly — if experts disagree, say so and explain why.
- When evidence is limited or low-quality, say so. Do not overstate weak evidence.
- Target 300-800 words per module section. Depth over breadth.
```

**F. Learner Context (if relevant):**
If learner_context.json revealed specific gaps or confusable pairs relevant to this agent's scope, include:
```
LEARNER CONTEXT (optional — use to calibrate depth):
- Known gaps: [relevant concepts_unknown]
- Confusable pairs: [relevant confusable_pairs]
- Ensure your modules address these gaps with extra clarity.
```

### Step 2.3: Launch the Historical Context Agent

In addition to the module-based agents, ALWAYS launch a dedicated Historical Context agent in the same parallel batch. This agent receives a specialized prompt:

```
RESEARCH TOPIC: [full topic]
YOUR SCOPE: Historical evolution and intellectual lineage of [topic]
YOUR OUTPUT FILE: /tmp/neuro-report-XXXXX/agent-history.md

You are a medical history research agent. Your job is to trace the historical evolution of [topic] — from earliest descriptions through paradigm shifts to current practice. This is NOT a summary of current evidence (other agents handle that). You are looking for:

1. **Earliest descriptions and seminal publications** — who first described this condition/technique/anatomy? When? What was the original understanding?
2. **Key paradigm shifts** — what changed our understanding? When did the field pivot? What was abandoned and why?
3. **Intellectual lineage** — how did one discovery lead to the next? What was the chain of reasoning?
4. **Abandoned approaches** — what was tried and failed? Why did it fail? (These are often the most instructive)
5. **Eponymous contributions** — any named classifications, techniques, or structures? Who were these people?

Write a single module: "## Historical Evolution & Milestones" with 500-1000 words of chronological narrative prose.

[Include the same Source Priority, PubMed MCP Tools, Write Protocol, and Quality Standards blocks as other agents]

SEARCH STRATEGY FOR HISTORY:
- PubMed: search for "history" OR "historical" OR "evolution" combined with the topic. Look for anniversary reviews, "classics in neurosurgery" articles, and biographical pieces.
- WebSearch: search for "[topic] history neurosurgery", "[topic] first described", "[topic] seminal paper"
- Look for dates, names, institutions, and the narrative arc of discovery.
```

After launching, report to the user:
```
Launched [N] research agents + 1 historical context agent:
- Agent 1 ([name]): /tmp/neuro-report-XXXXX/agent-1-[name].md
- Agent 2 ([name]): /tmp/neuro-report-XXXXX/agent-2-[name].md
- Historical Context: /tmp/neuro-report-XXXXX/agent-history.md
...
Monitoring for completion.
```

### Step 2.4: Fallback — Direct Research Mode

If background agents fail (permission errors, empty output, repeated tool denials), do NOT abandon the report. Fall back to direct research in the main session:

1. Report to the user: `"Background agents encountered [issue]. Falling back to direct research mode — this will be sequential but will still produce a comprehensive report."`
2. For each module, perform the research directly using WebSearch, WebFetch, and PubMed MCP tools
3. Write findings to the temp files as you go (same file structure as agents would produce)
4. Continue to Phase 4 (RAG) and Phase 5 (synthesis) as normal

This fallback ensures the skill always produces a report regardless of agent infrastructure issues.

---

## Phase 3: Monitor Progress

Use `run_in_background: true` — you will be notified when each agent completes. Do NOT poll or sleep.

**When notified of agent completion:**
1. Read the agent's output file
2. Verify it has substantive content (not just headers)
3. Check for "STATUS: COMPLETE" at the end
4. Report brief progress to the user: `"Agent 1 (Clinical Foundations) complete — N words across M modules."`

**If an agent returns with minimal/no content:**
1. Read whatever it produced to understand what went wrong
2. Relaunch with a refined prompt that:
   - Pre-loads any partial findings from the failed agent
   - Provides more specific search queries
   - Starts with: "Write your pre-loaded findings FIRST, then search for more"
3. Report the relaunch to the user

**When ALL agents are complete**, proceed to Phase 4.

---

## Phase 4: Textbook RAG Supplement

This is the foundational context pass. The goal is NOT to repeat what the web agents found — it is to add historical perspective, anatomical foundations, classical teaching, and textbook-level mechanistic depth that complements the modern evidence.

### Step 4.1: Extract Key Concepts

Read all completed agent output files. Identify 2–4 core concepts that would benefit from textbook grounding. Think:
- Anatomical structures referenced in surgical techniques → textbook anatomy details
- Pathophysiological mechanisms mentioned but not deeply explained → textbook mechanistic depth
- Historical context ("this replaced the previous standard of...") → textbook historical perspective
- Foundational principles underlying modern techniques → classical teaching

### Step 4.2: Run RAG Retrieval

For each core concept, run a targeted retrieval:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "$CONCEPT_QUERY" --no-frontier --output /tmp/neuro-report-XXXXX/rag_context.md
```

Use `--no-frontier` since we already have modern literature from the agents. Use `--append` for subsequent queries to accumulate all textbook passages in one file.

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "$CONCEPT_QUERY_2" --no-frontier --append --output /tmp/neuro-report-XXXXX/rag_context.md
```

### Step 4.3: Read and Assess Textbook Context

Read `/tmp/neuro-report-XXXXX/rag_context.md`. Evaluate which passages genuinely add value:
- **Include**: Foundational anatomy/physiology, historical evolution, classical classification systems, mechanistic depth not covered by web agents, established surgical principles
- **Exclude**: Outdated management recommendations superseded by current evidence, redundant restatements of what agents already found, low-relevance tangential passages

Note the valuable passages and their citations for the synthesis agent.

---

## Phase 5: Synthesize into Final Report

This is the most critical phase. You will read all agent outputs and the RAG textbook context, then produce a single, cohesive, comprehensive report.

**Do NOT launch a subagent for synthesis.** The main agent performs synthesis directly to maintain full context awareness and produce a cohesive document.

### Step 5.1: Read All Inputs

Read all agent output files and the RAG context file from the temp directory. Hold the full picture in context.

### Step 5.2: Cross-Reference Discovery

Run cross-reference discovery (per CLAUDE.md § Cross-Reference Discovery). Match filenames against the report topic. Store matches for `## Related in This Vault` and inline wikilinks.

### Step 5.3: Write the Report

Write to `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/<topic_slug>.md` using the Write tool.

**Filename convention**: lowercase, underscores, no dates (the YAML frontmatter has the date). Examples:
- `drg_stimulation_chronic_pain.md`
- `egfr_glioblastoma_targeted_therapy.md`
- `pterional_craniotomy.md`
- `normal_pressure_hydrocephalus.md`

**Report structure:**

```markdown
---
title: "<Full Report Title>"
date: YYYY-MM-DD
domain: "<Domain / Subdomain>"
topic_type: "<archetype from Phase 1>"
key_terms:
  - term1
  - term2
  - term3
clinical_context: "<1-2 sentences: when to reference this report>"
related_reports: []
tags:
  - skill/report
  - domain/<domain>
  - type/reference
  - source/agent
---

# <Report Title>

## Clinical Utility & Quick Reference

> **TL;DR:** <3-5 sentence dense summary of the most important findings, clinical
> implications, and key takeaways. This should be useful on its own for someone
> deciding whether to read the full report.>

### When to Reference This Report
- <Specific clinical scenario 1>
- <Specific clinical scenario 2>
- <Specific clinical scenario 3>

### Key Numbers at a Glance
| Parameter | Value | Context | Source |
|-----------|-------|---------|--------|
| ... | ... | ... | ... |

### Decision Framework
<If applicable: concise if/then logic, decision algorithm, or clinical pathway.
Omit entirely if the topic doesn't lend itself to a decision framework (e.g., pure
molecular biology or anatomy topics).>

---

## [Dynamic Module 1 — Title]

<Comprehensive prose synthesized from agent findings. Weave in textbook context
where it adds foundational depth, historical perspective, or anatomical grounding.
Textbook citations use [BookName, Ch./p.X] format. Web citations use
[Author et al., Year](URL) format.>

## [Dynamic Module 2 — Title]

<Continue with the same integration approach. Each module should read as a
coherent, self-contained section of a review article — not as stitched-together
excerpts from different agents.>

...

## [Dynamic Module N — Title]

...

---

## Synthesis & Integration

### Cross-Cutting Insights
<Themes, patterns, or connections that span multiple modules. What emerges from
looking at the full picture that isn't obvious from any single section?>

### Contradictions & Evolving Consensus
<Where do sources disagree? Where is the field actively shifting? What was
previously accepted but is now questioned? Be specific about what the
disagreement is and why it exists.>

### Confidence Assessment
<What claims in this report are strongly evidence-based (RCTs, meta-analyses,
established guidelines) vs. based on limited evidence (case series, expert
opinion, emerging data)? Be honest about the quality of evidence.>

### Knowledge Gaps & Future Directions
<What questions remain unanswered? What research is ongoing? What would change
clinical practice if proven?>

---

*Generated: YYYY-MM-DD | Sources: N PubMed/journal articles, N web sources, N textbook passages*

---

## Related in This Vault
[Wikilinks to matching Reports/, Operative Guides/, Study Material/, Concepts/ content discovered in Step 5.2. Only include if matches exist — omit this section entirely if no related content is found.]
```

### Synthesis Quality Standards

**Textbook integration rules — weave, don't segregate:**
- Textbook content must be integrated INTO the dynamic modules at the point where it adds value — never in a separate section
- Use textbook material for: anatomical grounding ("The dorsal root ganglion houses pseudounipolar primary afferent cell bodies at each spinal level [Greenberg, Ch. 14]"), historical evolution ("Anterior choroidal artery ligation was attempted in the 1950s for Parkinsonian tremor but abandoned due to hemiparesis and hemianesthesia [Youmans, Ch. 92]"), mechanistic depth, classical classification systems
- When textbook and modern sources address the same topic, lead with the current evidence and use the textbook to provide mechanistic depth or historical context — not the reverse
- Attribute clearly: textbook citations as `[BookName, Ch./p.X]`, modern citations as `[Author et al., Year](URL)`

**Prose quality rules:**
- Write in cohesive academic prose. The report should read like a review article in a neurosurgical journal, not a concatenation of search results.
- Each module must flow internally — transitions between paragraphs, logical progression of ideas
- Cross-reference between modules: "As discussed in [Module X], the anatomical basis for this approach..."
- Do NOT use bullet lists for core content. Tables are acceptable for comparative data, classification systems, and key numbers. Lists are acceptable only for explicit enumerations (e.g., inclusion criteria, step-by-step protocols).
- Preserve all specific numbers, doses, device names, trial names, and measurements from agent outputs
- Resolve contradictions between agents explicitly — if Agent 1 found X and Agent 2 found Y, investigate and present the resolution
- If agents found gaps (areas where evidence is limited), preserve those honestly in the Confidence Assessment

**Clinical Utility section rules:**
- The TL;DR must be genuinely useful — someone should be able to read ONLY the Clinical Utility section and walk away with actionable knowledge
- Key Numbers table: only include numbers that drive clinical decisions (thresholds, doses, critical measurements) — not every statistic from the report
- Decision Framework: only include if the topic genuinely has clinical decision points. A report on molecular pathways doesn't need one. A report on device selection does.
- "When to Reference" should name specific, concrete scenarios — not vague generalities

---

## Phase 6: Cleanup, Index & Log

### Step 6.1: Delete Temp Files

```bash
rm -rf /tmp/neuro-report-XXXXX
```

### Step 6.2: Update Reports Index

Read `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/INDEX.md` (create if it doesn't exist). Add an entry for the new report:

**INDEX.md format:**
```markdown
# Research Reports Index

| Report | Domain | Date | Summary |
|--------|--------|------|---------|
| [[filename\|Report Title]] | Domain | YYYY-MM-DD | One-sentence summary |
| ... | ... | ... | ... |
```

Use Obsidian wikilink format `[[filename|Display Title]]` so reports are linked in the vault graph.

If related prior reports were identified in Phase 0, update the new report's `related_reports` field in its YAML frontmatter, AND add a cross-reference note to the related report's entry in INDEX.md.

### Step 6.3: Log to Knowledge Graph

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py log_study \
  --topics "<comma-separated key topics covered>" \
  --understood "<key concepts covered in depth>" \
  --gaps "" \
  --depth 3
```

### Step 6.4: Concept Extraction (Silent)

Identify 3-8 atomic concepts from the report that are:
- Named clinical entities (syndromes, classifications, procedures, anatomical structures, pathophysiologic mechanisms)
- NOT already in `Concepts/` (check via `ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/"*.md 2>/dev/null`)
- Important enough to be wikilink targets for future content

For each new concept, write to:
`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/<Concept Name>.md`

```markdown
---
aliases: [<common abbreviations or alternate names>]
created: YYYY-MM-DD
extracted_from: "generate-report: <report title>"
tags:
  - type/concept
  - domain/<domain>
  - source/agent
---

**<Concept Name>**: <Core definition, 2-3 sentences.>

**Clinical Relevance**: <1-2 sentences connecting to practice.>

**Key Distinctions**: <Most important differentiating features from confusable entities.>
```

Reports cover more ground than RAG sessions, so extract MORE concepts (3-8 vs 2-5). Focus on entities that will appear across multiple reports or study sessions.

### Step 6.5: Post-Session Hook (Silent)

Run the Universal Post-Session Hook (see shared-system.md) to update Dashboard.md. This ensures the Dashboard reflects the new report's topics and any knowledge graph changes from Step 6.3.

---

## Phase 7: Present

Show the user:
1. The TL;DR and Clinical Utility section from the top of the report
2. The table of contents (module list)
3. A note on source composition (N PubMed articles, N web sources, N textbook passages)
4. Any cross-references to prior reports found
5. The file path: `Obsidian → agentic-neuro/Reports/<topic_slug>.md`

Do NOT dump the entire report into chat. The user will read it from the file.

---

## Key Rules

1. **Never launch agents without user approval of the plan.** The module selection and agent decomposition MUST be reviewed.
2. **Web-primary, textbook-supplemental.** Agents search the web. RAG runs after agents complete. Textbook content is woven into modules, never segregated.
3. **Medical source priority.** PubMed > society guidelines > UpToDate > Cochrane > ClinicalTrials.gov > manufacturer/FDA. No Wikipedia, no patient-facing sites, no blogs.
4. **Every claim needs a citation.** Inline, at the point of the claim. No orphaned facts. No fabricated citations.
5. **Write protocol is non-negotiable.** Every agent gets it verbatim. Search → Write → Search → Write.
6. **Single output file.** Only `Obsidian/agentic-neuro/Reports/<topic_slug>.md` persists. All temp files are deleted.
7. **Comprehensive depth.** Each module should be 300–800 words of substantive prose. The full report will typically be 3,000–6,000 words depending on topic complexity and number of modules.
8. **Honest uncertainty.** If evidence is limited, say so. If sources disagree, present both sides. Never overstate weak evidence. Mark unverifiable claims with *[citation needed]*.
9. **The Clinical Utility section is the most important section.** It's what makes this a reference document rather than a one-read report. Invest effort in making it genuinely useful for quick clinical lookup.
10. **No Anki hooks, no transform subagents, no session files.** This skill operates independently from the RAG-transform pipeline. The only shared infrastructure is the knowledge graph (for logging) and the lance_retriever (for textbook supplementation).
