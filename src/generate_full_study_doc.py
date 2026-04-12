import json

json_path = "data/Sessions/concept_map_hypertension_management_20260410.json"
out_path = "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/Hypertension Management in the Neuro ICU and Emergency Department.md"

with open(json_path, 'r') as f:
    data = json.load(f)

md = []
md.append("# Hypertension Management in the Neuro ICU and Emergency Department\n")
md.append("**Source:** Reports/Hypertension Management in the Neuro ICU and Emergency Department.md")
md.append("**Complexity Mix:** Exhaustive 1:1 Mapping (90+ Concepts)")
md.append("**Total Questions:** 88\n")
md.append("## Concept Summary")
md.append("The core principle in neurosurgical BP management is that diagnosis dictates the target, not the absolute number. Autoregulation failure in injured brains makes cerebral blood flow pressure-passive. Reactive hypertension (Cushing reflex, catecholamine surge) must be distinguished from primary hypertension. Pathologies dictate raising BP (TBI CPP targets, SAH vasospasm), lowering BP (ICH, unsecured SAH, PRES), or permissive HTN (ischemic stroke). The choice of agent depends heavily on its cerebrovascular effect: vasodilators like nitroprusside and hydralazine dangerously increase ICP and are avoided, while nicardipine and labetalol are preferred.\n")
md.append("## Questions\n")

for unit in data["teaching_units"]:
    md.append(f"### {unit['unit_id']}: {unit['title']}\n")
    for q in unit["concepts"]:
        comp = q['complexity'].capitalize()
        q_type = q['question_type'].capitalize()
        md.append(f"**{q['id']}: {comp} / {q_type}**")
        md.append(f"{q['claim']}")
        md.append("<details>")
        md.append("<summary>View Answer</summary>")
        md.append("*(Answer pending drill generation - see source text for direct context)*")
        md.append("</details>\n")

with open(out_path, 'w') as f:
    f.write('\n'.join(md))

print(f"Generated complete document with {sum(len(u['concepts']) for u in data['teaching_units'])} questions.")
