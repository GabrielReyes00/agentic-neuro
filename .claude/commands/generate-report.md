---
name: generate-report
description: Multi-agent research report generator — decomposes a neurosurgical topic into parallel web-research agents, supplements with textbook RAG, and synthesizes a comprehensive reference report. Invoke via /generate-report or when the user explicitly requests a full research report — "generate a report on", "research report on", "comprehensive review of". For general questions about a topic, answer from model knowledge instead.
---

# /generate-report — Multi-Agent Research Report Generator

Decompose a topic into parallel web-research workstreams, supplement with textbook RAG, synthesize a comprehensive reference report.

**Output**: `~/Documents/Obsidian/agentic-neuro/Reports/<Human Readable Title>.md`

---

## Phase 0: Pre-Flight (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && ./src/preflight.sh "$QUERY"
```

Read `data/Sessions/learner_context.json`. Note `suggested_depth`, `concepts_unknown[]`, `confusable_pairs[]` for depth calibration. Note prior reports for cross-referencing.

---

## Phase 1: Plan the Research

### 1.1 Classify Topic Archetype

Surgical Procedure | Pathology | Device/Technology | Pharmacology | Molecular/Genetic | Anatomy | Clinical Syndrome | Emerging Research | Outcomes/Evidence | Quality/Systems

### 1.2 Select 5-8 Content Modules

From the module pool (create/rename/combine as needed):

Epidemiology | Pathophysiology/MOA | Molecular/Genetic Basis | Anatomy/Surgical Anatomy | Clinical Presentation/Diagnosis | Classification/Grading | Imaging/Workup | Surgical Technique | Device Overview | Pharmacology/Dosing | Comparative Analysis | Evidence Base/Landmark Trials | Complications | Outcomes/Prognosis | Guidelines/Consensus | Emerging Research | Clinical Decision Framework

For each selected module, write one sentence explaining why included and what to cover.

### 1.3 Decompose into Agent Workstreams

Split modules across agents by complexity: narrow → 2-3, medium → 3-4, broad → 4-6. Plus a dedicated **Historical Context agent** (always included).

Design principles: group modules sharing source domains; separate modules needing different source types; give each agent an anchor module; if device/drug topic, separate device agent from clinical context agent.

### 1.4 Present Plan for User Approval

Show: archetype, agents + modules, scope per agent, primary sources. After the plan, ask:

> **Textbook RAG supplement**: Include LanceDB textbook retrieval after web agents? Most useful for anatomy-heavy or mechanistic topics. (yes/no)

**Do NOT proceed until user confirms.** They may modify modules, agents, scopes, or RAG opt-in.

---

## Phase 2: Launch Research Agents

### 2.1 Create Temp Directory

```bash
mkdir -p /tmp/neuro-report-$(date +%s)
```

### 2.2 Launch All Agents in Parallel

Launch each with `run_in_background: true`, `subagent_type: "general-purpose"`, `model: "sonnet"`.

**Each agent prompt MUST include ALL of these blocks:**

**A. Context:**
```
RESEARCH TOPIC: [topic]
YOUR SCOPE: [scope]
YOUR OUTPUT FILE: /tmp/neuro-report-XXXXX/agent-N-[name].md
You are a research agent for a comprehensive neurosurgical report. Write with academic review article depth.
```

**B. Module Instructions:**
For each module: title, purpose (from 1.2), target 300-800 words, 2-3 suggested search angles.

**C. Source Priority & Citations:**
```
SOURCE PRIORITY: PubMed/PMC > society guidelines (AANS, CNS, AAN, NCCN) > UpToDate > Cochrane > ClinicalTrials.gov > manufacturer/FDA > NeurosurgeryAtlas.com > peer-reviewed journals.
DO NOT USE: Wikipedia, patient-facing sites, blogs, AI summaries.

CITATION FORMAT: [Author et al., Year](URL) or [Society, Year](URL) or [UpToDate: "Topic", accessed YYYY-MM-DD]. Mark unverifiable claims: *[citation needed]*.

PUBMED MCP TOOLS: Use as PRIMARY search method:
- mcp__91fa504c-4473-41b3-a98d-e4b135b85490__search_articles
- mcp__91fa504c-4473-41b3-a98d-e4b135b85490__get_article_metadata
- mcp__91fa504c-4473-41b3-a98d-e4b135b85490__get_full_text_article
Start each module with PubMed MCP (MeSH terms), supplement with WebSearch.

CITATION INTEGRITY: Copy PMIDs VERBATIM from MCP responses. NEVER construct pubmed URLs from memory. If no PMID via MCP, use WebSearch URL. If no URL, write *[citation needed]*.

CITATION REGISTRY (required at end of output, before STATUS: COMPLETE):
## CITATION REGISTRY
PMID:12345678 | [Author et al., Year] | Title
URL:https://... | [Author et al., Year] | Title
```

**D. Write Protocol:**
```
The ONLY acceptable pattern: Search → Write → Search → Write. NEVER two searches without writing.
Work modules IN ORDER. For each: search, write findings, search more if needed, write again.
If 403/empty: write what you have, try ONE alternative, write again, move on.
WHEN FINISHED: Write "STATUS: COMPLETE" as the last line.
```

**E. Quality Standards:**
```
Academic prose, not bullet lists. 300-800 words per module. Include specific numbers (sample sizes, effect sizes, p-values, doses). Name specific trials/authors/years. State comparisons explicitly. Address controversies. Acknowledge limited evidence honestly.
```

**F. Learner Context** (if relevant gaps/confusable pairs exist for agent's scope).

### 2.3 Historical Context Agent

Always launched alongside module agents. Specialized prompt for tracing historical evolution: earliest descriptions, paradigm shifts, intellectual lineage, abandoned approaches, eponymous contributions. Target 500-1000 words.

### 2.4 Fallback — Direct Research

If agents fail: report issue, fall back to direct sequential research in main session. Same file structure. Continue to Phase 4+5 normally.

---

## Phase 3: Monitor Progress

Agents run in background — notified on completion. For each: read output, verify substance, check "STATUS: COMPLETE". Report brief progress. Relaunch with refined prompt if minimal content.

---

## Phase 4: Textbook RAG Supplement

> **Skip if `rag_opted_in` is false.**

1. Read all agent outputs. Identify 2-4 concepts needing textbook grounding (anatomy, mechanisms, historical context, classical teaching).
2. For each: `python3 src/lance_retriever.py compare "$CONCEPT" --no-frontier --output /tmp/neuro-report-XXXXX/rag_context.md` (use `--append` for subsequent).
3. Evaluate which passages add genuine value vs. redundant/outdated.

---

## Phase 5: Synthesize Final Report

**Main agent synthesizes directly** (no subagent) for full context awareness.

### 5.1 Read All Inputs

### 5.1.5 Citation Audit (MANDATORY)

1. Extract CITATION REGISTRY from every agent output.
2. For each PMID: call `get_article_metadata`. Verify author+year match → VERIFIED. Mismatch → replace with `*[citation needed — PMID mismatch]*`. Not found → replace similarly.
3. URL-only entries: accept as-is.
4. Build Verified Citation Map. Report audit result.
5. Agents without CITATION REGISTRY → all their PubMed citations are unverified.

### 5.2 Cross-Reference Discovery (per CLAUDE.md §7a)

### 5.3 Write the Report

Path: `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/<Human Readable Title>.md`
Filename: Title Case, spaces, no dates. No H1 — filename is the title.

**Structure:**
```markdown
## Clinical Utility & Quick Reference

> **TL;DR:** <3-5 sentence dense summary>

### When to Reference This Report
- <Specific scenarios>

### Key Numbers at a Glance
| Parameter | Value | Context | Source |
|-----------|-------|---------|--------|

### Decision Framework
<If applicable — omit for pure science topics>

---

## [Dynamic Module 1]
<Synthesized prose. Textbook woven in where it adds depth, cited as [BookName, Ch./p.X]>

## [Dynamic Module N]
...

---

## Synthesis & Integration

### Cross-Cutting Insights
### Contradictions & Evolving Consensus
### Confidence Assessment
### Knowledge Gaps & Future Directions

---
*Generated: YYYY-MM-DD | Sources: N PubMed, N web, N textbook*

---

## Related in This Vault
[Wikilinks if matches exist]
```

**Synthesis rules**: Textbook woven INTO modules (never segregated). Academic prose, not concatenated excerpts. Preserve all numbers/doses/trial names. Resolve contradictions explicitly. TL;DR must be genuinely actionable standalone.

---

## Phase 6: Cleanup, Index & Log

1. `rm -rf /tmp/neuro-report-XXXXX`
2. Update `Reports/INDEX.md` (per CLAUDE.md §7b). Wikilink format: `[[Title|Display]]`.
3. `log_study` with topics covered, depth 3.
4. Concept Extraction: 3-8 concepts per CLAUDE.md §7c. Reports cover more ground → extract more.
5. Post-Session Hook per CLAUDE.md §8.

---

## Phase 7: Present

Show: TL;DR + Clinical Utility, table of contents, source composition, cross-references, file path. Do NOT dump full report into chat.

---

## Key Rules

1. Never launch agents without user plan approval.
2. Web-primary, textbook-supplemental.
3. Medical source priority. No Wikipedia, blogs, patient sites.
4. Every claim needs inline citation. No fabricated citations.
5. Search → Write protocol is non-negotiable for agents.
6. Single output file persists. All temps deleted.
7. 300-800 words per module. 3,000-6,000 total.
8. Honest uncertainty. Mark gaps with *[citation needed]*.
9. Clinical Utility section is the most important — invest effort.
10. No Anki hooks, no transform subagents, no session files.
