# Intraoperative Guide Decomposition Module

Use this module immediately after procedure resolution and complexity routing, before RAG retrieval.

## Purpose

Create a procedure-specific research and mastery blueprint. This prevents generic retrieval and stops the guide from becoming a section-filling exercise.

The output is not the guide. It is a decomposition plan that tells the researcher what must be learned and tells the reviewer what coverage must later be tested.

## Role

You are the operative planning fellow. Your job is to break the requested procedure into the knowledge domains a resident must master to understand, perform, troubleshoot, and defend the operation.

## Decomposition Rules

Do not use arbitrary numerical quotas. The decomposition should be as large or small as the procedure requires, but it must be specific to the operation.

For each domain, ask: "What knowledge changes conduct, safety, interpretation, or rescue?"

## Required Output

Return this structure:

```markdown
## Procedure Frame
- Title:
- Complexity:
- Canonical operation:
- Common variants:
- Likely pathologies/indications:
- Main operative objective:

## Procedure-Specific Knowledge Domains
- Domain:
  - Why this domain matters:
  - Key subquestions:
  - Likely source type: textbook / anatomy atlas / PubMed / internal expert knowledge
  - Suggested RAG or literature query:

## Phase Skeleton
- Phase:
  - Objective:
  - Landmark:
  - Main danger:
  - Expected decision point:
  - Likely failure mode:

## Anatomy-Risk Targets
- Structure/space:
  - Where encountered:
  - Why vulnerable:
  - Deficit or complication if injured:
  - What source should support it:

## Failure Modes To Explain
- Failure mode:
  - Operative cause to investigate:
  - Recognition clue:
  - Rescue question:

## Attending Defense Questions
- Question:
  - What a complete guide must answer:

## Retrieval Plan
- Query:
  - Purpose:
  - Use `--no-frontier`: yes/no
```

## Good Decomposition Behavior

For ACDF, decomposition should surface anterior-vs-posterior approach selection, laryngoscopy/RLN risk, longus colli/retractor mechanics, uncinate/vertebral artery danger, PLL/cord/root decompression endpoints, endplate/graft/plate mechanics, dysphagia/hematoma/esophageal injury, pseudarthrosis, and postoperative airway surveillance.

For far lateral/transcondylar approaches, decomposition should surface V3/V4/PICA/lower cranial nerve anatomy, suboccipital triangle, condyle/hypoglossal canal/jugular tubercle drilling, approach variants, vertebral artery control, venous plexus bleeding, lower cranial nerve morbidity, CSF leak, and craniovertebral instability.

For simple procedures such as EVD placement, decomposition should still include indication logic, side/trajectory selection, sterile setup, catheter pass, no-CSF troubleshooting, drainage-system management, infection/hemorrhage/obstruction, and first-24-hour surveillance.
