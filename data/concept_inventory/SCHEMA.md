# Concept Inventory Source Schema

This directory holds the committed source of truth for the canonical neurosurgery
concept inventory. Each `*.json` file is one domain. `src/concept_inventory.py build`
compiles all files into `data/concept_inventory.db` (gitignored, rebuilt
automatically whenever sources change). Never edit the DB; edit these files.

The inventory is the stable domain map onto which the learner's memory is
projected (`map-learner`). It must stay deterministic, curated, and reviewable:
no generated content goes in without validation.

## File Format

```json
{
  "domain": "vascular",
  "code": "vasc",
  "display_name": "Vascular Neurosurgery",
  "topics": [
    {"id": "vasc.sah", "name": "Aneurysmal Subarachnoid Hemorrhage", "blurb": "One line."}
  ],
  "concepts": [
    {
      "id": "vasc.sah.hunt-hess",
      "name": "Hunt-Hess clinical grading",
      "topic": "vasc.sah",
      "type": "classification",
      "tier": "core",
      "blurb": "Clinical SAH severity grades I-V; predicts surgical risk and outcome.",
      "aliases": ["hunt and hess grade", "hh grade"],
      "prereqs": ["vasc.sah.clinical-presentation"],
      "discriminators": ["vasc.sah.wfns-grading"],
      "related": ["vasc.sah.outcome-prognosis"],
      "acgme": ["Subarachnoid Hemorrhage - Initial Management"]
    }
  ]
}
```

## Canonical File Layout

Every domain file uses one **canonical layout**: scalar keys (`domain`, `code`,
`display_name`) inline, and the `topics` and `concepts` arrays with **one object
per line** and inline sub-arrays (`aliases`/`prereqs`/`discriminators`/`related`/
`acgme`). This keeps edits diff-friendly — changing one concept is a one-line diff.

Do not hand-format or pretty-print (no `json.dumps(indent=2)`, which explodes
sub-arrays and produces noisy diffs). All writers emit this layout:
`src/inventory_authoring.py` (`propose --apply`, `add_aliases`) writes it directly,
and `python3 src/inventory_authoring.py --normalize` rewrites every file into it
(round-trips through JSON, so content is unchanged) and rebuilds.

## Field Rules

- **`domain`**: canonical slug — one of `general`, `anatomy`, `vascular`, `tumor`,
  `spine`, `trauma`, `neurocritical-care`, `skull-base`, `functional`, `pediatric`,
  `peripheral-nerve`.
- **`code`**: short unique prefix; every topic and concept id in the file must
  start with `<code>.`.
- **`id`**: `<code>.<topic-slug>.<concept-slug>`, lowercase, hyphenated, stable
  forever. Renaming an id breaks learner mappings — add aliases instead.
- **`name`**: precise clinical name, ≤ 10 words.
- **`type`**: one of `anatomy`, `physiology`, `pathology`, `presentation`,
  `diagnostics`, `imaging`, `classification`, `management`, `operative`,
  `complication`, `pharmacology`, `evidence`.
- **`tier`**: progression band toward mastery —
  `foundation` (prerequisite knowledge a novice needs first),
  `core` (every graduating resident must own it),
  `advanced` (senior-resident depth: nuanced management, operative judgment),
  `expert` (fellowship-level or frontier material).
- **`blurb`**: one sentence, ≤ 25 words, stating what mastery of this concept means.
- **`aliases`**: lowercase synonyms, abbreviations, and phrasings a learner-memory
  concept label might use. Generous aliasing is what makes learner projection
  accurate — include common abbreviations (e.g. "asdh", "tSAH", "cpp").
- **`prereqs`**: concept ids that should be understood first. Point to the most
  specific prerequisite, not the topic root.
- **`discriminators`**: confusable concept ids (the classic exam/management
  confusions). Symmetry is not required; the builder treats edges directionally.
- **`related`**: meaningful non-prereq associations (use sparingly).
- **`acgme`**: optional list of ACGME milestone topic titles (from
  `data/acgme_curriculum.json`) this concept serves. Use close title text; the
  builder links by token match and reports unmatched entries.

## Edge Discipline

- Edges may reference concepts in other files. Cross-domain references should
  use the Core Reference IDs below; any reference to a nonexistent id is dropped
  at build with a warning.
- No self-edges. Keep per-concept edges ≤ 6 total; prefer the highest-value ones.

## Core Reference IDs

These ids are guaranteed to exist (in `foundations.json` and `anatomy.json`) and
are safe targets for cross-domain `prereqs`/`related`:

Foundations (`fnd.*`):
`fnd.icp.monro-kellie`, `fnd.icp.icp-waveforms`, `fnd.icp.cpp-calculation`,
`fnd.icp.herniation-syndromes`, `fnd.icp.icp-treatment-thresholds`,
`fnd.cbf.autoregulation`, `fnd.cbf.co2-reactivity`, `fnd.cbf.ischemia-thresholds`,
`fnd.csf.production-circulation`, `fnd.csf.hydrocephalus-physiology`,
`fnd.exam.gcs`, `fnd.exam.cranial-nerve-exam`, `fnd.exam.motor-sensory-exam`,
`fnd.exam.brainstem-reflexes`, `fnd.imaging.ct-basics`, `fnd.imaging.mri-sequences`,
`fnd.imaging.angiography-basics`, `fnd.pharm.osmotherapy`, `fnd.pharm.antiepileptics`,
`fnd.pharm.anticoagulation-reversal`, `fnd.pharm.dexamethasone`,
`fnd.periop.hemostasis`, `fnd.periop.positioning`, `fnd.periop.neuromonitoring`,
`fnd.ebm.trial-interpretation`, `fnd.physio.neuronal-excitability`,
`fnd.physio.bbb`, `fnd.physio.cerebral-edema`

Anatomy (`ana.*`):
`ana.cortex.functional-anatomy`, `ana.cortex.white-matter-tracts`,
`ana.deep.basal-ganglia`, `ana.deep.thalamus`, `ana.deep.hypothalamus-pituitary`,
`ana.ventricles.ventricular-system`, `ana.brainstem.midbrain`, `ana.brainstem.pons`,
`ana.brainstem.medulla`, `ana.cerebellum.anatomy`, `ana.cn.cranial-nerves-overview`,
`ana.cn.cavernous-sinus`, `ana.vasc.circle-of-willis`, `ana.vasc.anterior-circulation`,
`ana.vasc.posterior-circulation`, `ana.vasc.venous-sinuses`,
`ana.vasc.spinal-cord-vascular`, `ana.spine.vertebral-column`,
`ana.spine.spinal-cord-tracts`, `ana.spine.nerve-roots-dermatomes`,
`ana.spine.craniovertebral-junction`, `ana.pns.brachial-plexus`,
`ana.pns.lumbosacral-plexus`, `ana.skullbase.anterior-fossa`,
`ana.skullbase.middle-fossa`, `ana.skullbase.posterior-fossa`,
`ana.approaches.pterional`, `ana.approaches.retrosigmoid`,
`ana.approaches.midline-suboccipital`, `ana.approaches.transsphenoidal`,
`ana.scalp-skull.scalp-layers`

## Validation

Per file while authoring:

```bash
python3 src/concept_inventory.py validate --file data/concept_inventory/<domain>.json
```

Whole inventory (resolves cross-file edges) and compile:

```bash
python3 src/concept_inventory.py validate
python3 src/concept_inventory.py build --force
python3 src/concept_inventory.py stats
```

A file is acceptable only when `validate` reports `"ok": true` for it.
