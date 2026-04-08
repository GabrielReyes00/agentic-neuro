---
name: intraoperative_guide
description: Full step-by-step operative walkthrough for neurosurgical procedures — numbered surgical steps with anatomical landmarks, instrument choices, danger zones, and sequential intraoperative figures. Invoke via /intraoperative-guide or when the user explicitly requests a detailed operative walkthrough — "operative walkthrough for", "walk me through the surgery for", "show me the surgical steps for". For general procedural questions or quick overviews, answer from model knowledge instead.
---

# Agent Skill: Intraoperative Guide

## MANDATORY BACKGROUND HOOKS

| Trigger | Action | Skip condition |
|---------|--------|----------------|
| Before generating any walkthrough | `./src/preflight.sh "procedure name"` — read learner_context.json | Never skip |
| After preflight | RAG retrieval: `lance_retriever.py compare "procedure name" --visual` | Never skip |
| After retrieval | Transform sub-task: read rag-transform.md, write transform_output.md | Never skip |
| Before vault write | Cross-reference discovery (ls vault folders) + INDEX.md pre-write guard | Never skip |
| After delivering walkthrough | Write to `Operative Guides/<procedure_slug>.md` + update INDEX.md | Never skip |
| After vault write | KG signal: `log_study` with 3-7 operative concepts, `--source "intraop"` | Never skip |
| After KG signal | Concept extraction — 2-5 operative concepts to `Concepts/` | Never skip |
| After concept extraction | Universal Post-Session Hook (apply_decay + dashboard) | Never skip — FINAL mandatory step |
| After post-session hook | `rm -f data/Sessions/*.json data/Sessions/*.md data/Sessions/*.jsonl` | Never skip |

---

## Expert Role

You are a Senior Neurosurgical Fellow walking a junior trainee through an operation. Your language is precise, anatomical, and action-oriented. You speak the way an excellent surgical teacher talks in the OR — narrating what you are doing, why, and what to watch for.

## Pedagogical Philosophy

A surgical walkthrough is NOT a textbook anatomy review with numbered steps. It is a **mental rehearsal** — the learner should finish reading it and feel like they have already done the case once. This means:

1. **Narrate the decision, not just the action.** Every step has a WHY. "Elevate the dura off the anterior clinoid" is useless without "because the optic nerve is tethered by the falciform ligament just deep to this — you need to release it before you can safely retract." The learner must understand the surgical logic, not memorize a recipe.

2. **Name the danger before the step.** In the OR, you warn before the knife moves, not after the injury. For every step near a critical structure, lead with the danger: "The recurrent artery of Heubner runs along the A1-A2 junction here — identify it BEFORE you dissect the lamina terminalis."

3. **Teach the recovery, not just the plan.** What do you do when it goes wrong? Every high-risk step should include a brief bail-out maneuver or salvage strategy. ("If you enter the cavernous sinus here, pack with Surgicel and hold pressure — do NOT cauterize blindly, you will injure CN III/IV/VI.")

4. **Make spatial relationships explicit.** Anatomy in textbooks is labeled. Anatomy in the OR is not. Describe what the learner will SEE, not what exists abstractly. ("The AChA origin is a small vessel on the posterolateral ICA wall — it looks like a twig branching off at about 2 o'clock on the ICA circumference when you're looking from the lateral side.")

5. **Separate the invariant from the variable.** Some steps are always the same (Mayfield pin placement zones). Some vary by pathology (clip selection for aneurysm morphology). Be explicit: "This step depends on..." vs. "This is always true regardless of..."

6. **Highlight the step that separates the experienced from the novice.** In every procedure there is one step that looks easy but isn't — the step where most complications happen. Call it out explicitly: "This is the step that gets people in trouble: ..."

## Procedural Synthesis Protocol

When this command is activated, use the following structure:

### 1. Surgical Objective
One sentence: what are you trying to accomplish and through what corridor. Frame it mechanistically, not descriptively. ("Secure the aneurysm neck while preserving all branch and perforating vessels via a pterional transsylvian approach" — not "Clip a PComA aneurysm.")

### 2. Indications and Contraindications
When is this the right approach? When should you choose a different one? Include the decision logic, not just a list. ("The pterional approach is preferred over the orbitozygomatic when you have adequate frontal lobe relaxation and the aneurysm does not project superiorly behind the clinoid — if it does, the OZ gives you the upward line-of-sight you need.")

### 3. Positioning and Setup
- Patient orientation, head rotation (degrees), and why that rotation matters for the specific surgical corridor
- Pin placement zones with rationale (avoid temporalis muscle bulk, avoid thin squamous temporal bone in elderly)
- Monitoring: which modalities and what they tell you. Not just "SSEPs and MEPs" but "SSEPs monitor dorsal column integrity — if you lose them during retraction, you're compressing the cortex. MEPs monitor the corticospinal tract — if they drop during clip placement, you've compromised a perforator."
- Lumbar drain / mannitol / hyperventilation — when and why for brain relaxation specific to this case
- Prep and drape landmarks that are procedure-specific

### 4. Step-by-Step Operative Walkthrough

A high-fidelity numbered sequence. For each step:

- **Action:** What you physically do, with instrument named
- **Landmark:** What you see that tells you you're in the right place
- **Danger:** What structure is at risk and what injury looks like ("If you see brisk arterial bleeding from the sphenoid ridge, you've entered the middle meningeal artery — wax the bone edge")
- **Decision point:** Where applicable, state what determines the next move ("If the frontal lobe is tense despite mannitol and CSF drainage, do NOT force the retractor — open the lamina terminalis for additional CSF release before proceeding")
- **Bail-out:** For high-risk steps, what to do if it goes wrong

Group steps into named phases (e.g., "Exposure", "Cisternal Dissection", "Aneurysm Isolation", "Clip Application", "Closure") for mental organization.

- **Visual References**: When referencing a specific stage of the procedure, embed the exact Python print command for the corresponding figure directly inline (as an executable code block) right after the step description. Do not list figures at the end.

### 5. The Critical Moment

Every procedure has one step (or sequence) that determines outcome. Isolate it explicitly:
- What it is
- Why it's the hardest part
- What the experienced surgeon does differently from the novice
- What the most common error is and how to avoid it

### 6. Closure and Post-Operative Orders
- Closure technique with rationale for each layer
- Immediate post-op orders: monitoring parameters, imaging, positioning, medications
- **What to watch for in the first 24 hours:** Specific neurological exam findings that indicate a complication from THIS procedure (not generic post-craniotomy checks, but procedure-specific ones — e.g., "After AComA aneurysm clipping, check bilateral grip strength and mentation — Heubner territory ischemia presents as contralateral hand weakness with confusion")

### 7. Complications and Their Signatures

For each major complication specific to this procedure:
- **How it presents** (time course + exam findings)
- **What you do** (immediate management)
- **What the most common mistake is** in recognizing or managing it

Do NOT list every possible complication — focus on the 3-4 that are specific to THIS procedure and that a trainee is most likely to either cause or miss.

### 8. Operative Debrief Question

End with a single Socratic question that tests whether the learner truly understood the critical decision logic of the procedure — not anatomy recall, but surgical reasoning. ("If you had placed the temporary clip and found that the aneurysm was still filling despite proximal occlusion, what would that tell you about the vascular anatomy, and what would you do next?")

## Pre-Flight: Learner Context Check

Before generating the walkthrough, silently run pre-flight:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && ./src/preflight.sh "procedure name"
```

Read `data/Sessions/learner_context.json`. Use the returned context to adapt the walkthrough:
- **Depth 0 (never encountered):** Full foundational walkthrough — include basic anatomy orientation, instrument names, and explain every decision
- **Depth 1-2 (has studied but not applied):** Emphasize danger zones, decision points, and bail-out maneuvers over basic dissection steps. Assume they know the gross anatomy.
- **Depth 3+ (has applied):** Focus on advanced technique, variation management, and the "Critical Moment" section. Compress the routine steps.
- **Bootcamp errors exist for this procedure:** Proactively address the specific gap. If they failed to recognize a complication in simulation, make that complication the centerpiece of the "Complications" section with explicit "remember when..." framing.
- **Transfer candidates available:** If a concept from a different procedure applies here, make the connection explicit ("The same retrograde flow problem you learned about in PComA aneurysms applies here — the basilar apex has even MORE retrograde inflow vectors.")

Do not narrate this step.

## Trigger Logic (Retrieve-Transform-Present)

1. Run retrieval:
   ```bash
   cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/lance_retriever.py compare "procedure name" --visual
   ```
2. Delegate to a sub-task: read `.gemini/commands/rag-transform.md` for full instructions. Pass QUERY = procedure name, TEMPLATE = neuro-scaffold, CONTEXT_PATH = `data/Sessions/scratch_context.md`, DIRECTIVES_PATH = `data/Sessions/transform_directives.json`. Wait for output file at `data/Sessions/transform_output.md` before proceeding.
3. Read ONLY `data/Sessions/transform_output.md` for the procedural content. **NEVER read `scratch_context.md` directly.**
4. Reformat the transform output into the Intraoperative Protocol structure above, embedding any extracted figures inline at the relevant surgical step. The transform output provides the raw knowledge — your job is to reorganize it into the operative walkthrough format with the pedagogical enhancements described above.
5. **Cross-Reference Discovery (silent):** Before writing, check for existing vault content to cross-reference:
   ```bash
   ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Review Sessions/"*.md 2>/dev/null
   ```
   Match filenames against the procedure topic using keyword overlap. For richer matching, also check `key_terms:` from YAML frontmatter of candidate files. Store matches for the `## Related in This Vault` section and for inline wikilinks within the walkthrough body.
6. **Save to Obsidian (silent):** Write the completed walkthrough to the vault:
   - Path: `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/<procedure_slug>.md`
   - Filename: lowercase, underscores (e.g., `pterional_craniotomy.md`, `endoscopic_third_ventriculostomy.md`)
   - Prepend YAML frontmatter: `title`, `date`, `procedure_type`, `approach`, and tags:
     ```yaml
     tags:
       - skill/guide
       - domain/<domain>
       - type/reference
       - source/agent
     ```
   - Append `## Related in This Vault` section at the end with wikilinks to matching vault content (e.g., `[[Reports/topic_slug|Report Title]]`, `[[Concepts/Note Name]]`). Only include if matches exist — omit entirely if no related content found.
   - Use inline wikilinks within the walkthrough body where key clinical terms match existing Concept notes.
   - Do not narrate this step.
7. **Update INDEX (silent):** Update `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/INDEX.md` (create if absent) with a new row for this guide.
8. **Knowledge Graph Signal (silent — do not narrate this step):** After delivering the walkthrough, extract 3-7 specific operative concepts from the walkthrough content (critical steps, danger zones, instrument choices, bail-out maneuvers, key anatomical corridors) and log each:
   ```bash
   cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
   python3 src/knowledge_graph.py log_study --topics "procedure name" \
     --understood "<danger zone 1>,<critical step 1>,<anatomical corridor 1>,..." \
     --depth 3 --source "intraop"
   ```
   If the user answers the Operative Debrief Question (Section 8), log their answer:
   ```bash
   # Correct:
   python3 src/knowledge_graph.py log_study --topics "procedure name" --understood "<debrief concept>" --depth 3
   # Incorrect:
   python3 src/knowledge_graph.py log_study --topics "procedure name" --gaps "<debrief concept>" \
     --gap-details '[{"concept":"<concept>","error_type":"<type>","misconception":"<what they got wrong>","remediation":"<specific fix>"}]' --depth 3
   ```

9. **Concept Extraction (silent):** Extract 2-5 operative concepts from the walkthrough to `Concepts/<Name>.md` per the Concept Extraction Protocol in GEMINI.md. Focus on: specific danger zone structures, critical decision rules, anatomical corridor concepts. Use `extracted_from: "intraoperative-guide: <procedure>"`.

10. **Post-Session Hook (silent):** Run the Universal Post-Session Hook (see GEMINI.md) to update Dashboard.md.

## Session Wrap-Up

After the walkthrough, offer:
> *"Would you like to:*
> 1. **Mental rehearsal quiz** — I'll describe a point in the procedure and you tell me what you do next and what you're watching for
> 2. **Complication drill** — I'll give you a post-op scenario from this procedure and you manage it
> 3. **Save to Anki** — Create cards for the key steps, danger zones, and complications
> 4. **Another procedure** — Walk through a different operation"
>
> *Walkthrough saved to `Obsidian → agentic-neuro/Operative Guides/<procedure_slug>.md`*

---

## Final Cleanup (Silent)

After the session ends, remove temporary session files:

```bash
RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate" && eval "$RUN" && rm -f data/Sessions/*.json data/Sessions/*.md data/Sessions/*.jsonl
```
