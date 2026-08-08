# Refactor Manual Note Visualize

Load this module only when `visualize` is active. Add visuals as part of the
note's explanation, not as decoration or a detached gallery. Zero new visuals
is valid when no candidate improves understanding, spatial recall, comparison,
or decision-making.

## Visual Planning

Run visualization after all requested answering, expansion, verification, and
distillation so every visual reflects the final content.

1. Read the integrated note and inspect every existing embed before proposing a
   new asset.
2. Identify concepts whose meaning depends on geometry, sequence, branching,
   comparison, imaging appearance, operative orientation, or quantitative
   pattern.
3. Give each candidate one learning job and select the smallest set that adds
   information not already communicated efficiently in prose.
4. Place each visual at the point where the learner needs it. Add a concise
   caption that states what relationship, landmark, pattern, or decision to
   inspect.

Do not add a visual merely because the flag was present. Do not convert ordinary
prose into a flowchart or table when reading the prose is faster.

## Choose The Safest Medium

Use the first route that faithfully serves the learning job:

1. **Existing note asset:** preserve and reuse a relevant embed; improve only
   its placement, size, or learning-focused caption.
2. **Native explanatory visual:** use a spatial or comparison table, inline
   sequence, or Mermaid diagram for exact text relationships, mechanisms, and
   genuine branches.
3. **Source visual:** use an existing figure from supplied material or retrieve
   an authoritative anatomy, imaging, operative, or published figure. Prefer
   the original publisher, author, professional society, government source, or
   open-license repository. Preserve panel labels, orientation, scale, legend,
   and scientific context. Record a normal source citation and license or usage
   status when available.
4. **Generated schematic:** use available image-generation capability only for
   a conceptual illustration that can be checked against authoritative sources.
   Never generate patient imaging, operative photographs, pathology, study data,
   or a realistic substitute for source evidence. Do not rely on generated text
   labels; prefer a clean schematic with verified labels supplied in the note.

For exact microsurgical anatomy, radiographic findings, or pathology, prefer a
source visual. Use a generated anatomical schematic only when every depicted
relationship can be independently verified. If fidelity cannot be established,
omit the asset and report the limitation.

## Rights, Storage, And Embedding

- Prefer open-license figures. A figure from user-supplied or lawfully accessed
  source material may be retained for private study with its complete citation
  and source link; never bypass access controls, strip attribution, or republish
  it. When access or usage constraints prevent safe storage, link to the source
  or choose an open-license alternative.
- Store each new image once in the vault's configured attachment directory:
  `z_Images/<Descriptive Title Case Name>.<ext>`. Check for an existing asset
  with the same subject, filename, or content before writing a duplicate.
- Use the shortest unambiguous embed, for example
  `![[Opticocarotid Recess Boundaries.png|450]]`.
- Keep attribution in a concise caption or the note's existing sources section.
  Mark generated content as a schematic so it cannot be mistaken for patient or
  source data, but do not add process commentary.
- Preserve existing attachments even when a better visual is added. Remove or
  replace an existing asset only with explicit user authorization.

## Visual Verification

Inspect every new or altered visual at full size before completion. Confirm:

- anatomy, laterality, orientation, labels, scale, and arrows agree with the
  verified note content;
- figure crops retain the context needed to interpret them;
- text and labels remain legible in Obsidian at the selected embed width;
- the caption tells the learner what to inspect without restating the section;
- source, license or usage status, and generated-schematic status are accurate;
- no visual resembles fabricated patient, operative, radiographic, pathologic,
  or quantitative evidence.

After any image is added or changed, run `python3 src/vault_library.py refresh`
from the repository environment and require zero integrity failures plus a
backlink to the edited note. Report visual paths and sources in the completion
message, not as workflow metadata in the note.
