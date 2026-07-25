from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import vault_index


CONCEPT_NOTE = """**ENRICH Trial**: Early minimally invasive surgery trial for selected lobar ICH.

## Quick Reference

- Selected spontaneous supratentorial ICH.
- Early surgery is a time-sensitive selection question.

## Durable Mental Model

Treat ENRICH as a corridor-selection rule, not a universal instruction to evacuate every hematoma.

## Critical Discriminators

- ENRICH differs from MISTIE because it tests early parafascicular surgery.
- Lobar and deep hemorrhage have different corridor-risk profiles.

## Evidence Card

| Element | Anchor |
|---|---|
| Window | 24 hours |

## Execution Check

- State location, volume, time from onset, IVH, and baseline function.
- Explain why unsafe deep corridors weaken the surgical argument.

## Related In This Vault

- [[Reports/Temporal ICH Management|Temporal ICH Management]]

## References

- Primary study: [ENRICH](https://doi.org/10.1056/NEJMoa2308440).

---
aliases: [ENRICH, lobar ICH trial]
created: 2026-06-06
extracted_from: "generate-report: Temporal ICH Management"
domain: vascular
summary: "Trial card for selected early minimally invasive evacuation of lobar ICH."
tags: [type/concept, domain/vascular, source/agent]
---
"""


BRAIN_DUMP_NOTE = """## Clinical Focus

- VA spine consult readiness.

## Clinical & Anatomical Synthesis

Postoperative neck swelling after ACDF requires immediate airway concern and senior escalation.

## Institutional & Local Clarifications

- At the VA, confirm local airway cart location and senior notification workflow.

## Operational Mental Models

- Treat anterior neck swelling as an airway clock until proven otherwise.

## References

- External review: [Airway compromise](https://example.com/airway).

---
tags: [skill/brain-dump, domain/spine, type/reference, source/user]
generated: 2026-06-06
summary: "Local spine-service teaching about ACDF airway escalation."
domain: spine
provenance: "de-identified service teaching"
internal_knowledge_used: true
---
"""


class VaultIndexTests(unittest.TestCase):
    def _build_vault(self, root: Path) -> Path:
        vault = root / "vault"
        concepts = vault / "Concepts"
        brain_dumps = vault / "Brain Dumps"
        concepts.mkdir(parents=True)
        brain_dumps.mkdir(parents=True)
        (concepts / "ENRICH Trial.md").write_text(CONCEPT_NOTE, encoding="utf-8")
        (brain_dumps / "ACDF Airway Teaching.md").write_text(BRAIN_DUMP_NOTE, encoding="utf-8")
        return vault

    def test_sync_indexes_field_aware_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = self._build_vault(root)
            db = root / "vault_index.db"

            result = vault_index.sync_vault(vault_root=vault, db_path=db)

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["notes_indexed"], 2)
            self.assertGreaterEqual(result["sections_indexed"], 10)
            concept = vault_index.get_section(db_path=db, note="Concepts/ENRICH Trial.md", section_type="critical_discriminators")
            self.assertTrue(concept["ok"])
            self.assertEqual(concept["hits"][0]["section_type"], "critical_discriminators")
            self.assertIn("MISTIE", concept["hits"][0]["text"])
            self.assertIn("knowledge_boundary", concept)

    def test_search_uses_task_policy_without_hiding_other_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = self._build_vault(root)
            db = root / "vault_index.db"
            vault_index.sync_vault(vault_root=vault, db_path=db)

            result = vault_index.search_sections(
                "MISTIE lobar deep corridor",
                db_path=db,
                task="concept-repair",
                limit=5,
            )

            self.assertTrue(result["ok"])
            self.assertIn("durable_mental_model", result["preferred_section_types"])
            section_types = {hit["section_type"] for hit in result["hits"]}
            self.assertIn("critical_discriminators", section_types)
            self.assertEqual(result["knowledge_boundary"], vault_index.KNOWLEDGE_BOUNDARY)

    def test_search_can_exclude_local_service_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = self._build_vault(root)
            db = root / "vault_index.db"
            vault_index.sync_vault(vault_root=vault, db_path=db)

            local = vault_index.search_sections(
                "VA airway cart ACDF",
                db_path=db,
                task="service-local",
                include_local=True,
                limit=5,
            )
            formal = vault_index.search_sections(
                "VA airway cart ACDF",
                db_path=db,
                task="service-local",
                include_local=False,
                limit=5,
            )

            self.assertTrue(any(hit["folder"] == "Brain Dumps" for hit in local["hits"]))
            self.assertFalse(any(hit["folder"] == "Brain Dumps" for hit in formal["hits"]))

    def test_task_plan_names_field_policy(self) -> None:
        plan = vault_index.task_plan("consult")

        self.assertTrue(plan["ok"])
        self.assertIn("quick_reference", plan["preferred_section_types"])
        self.assertIn("evidence_card", plan["preferred_section_types"])

    def test_journal_club_task_and_folder_are_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            folder = vault / "Journal Club"
            folder.mkdir(parents=True)
            (folder / "Hybrid Epilepsy Surgery.md").write_text(
                "## Start Here\n\nHybrid strategy.\n\n"
                "## Results That Matter\n\nSeven selected patients.\n\n"
                "## Limitations That Actually Matter\n\nNo comparator.\n\n"
                "---\ndomain: functional\nsummary: \"Hybrid evidence.\"\n"
                "tags: [skill/journal-club, type/article, domain/functional]\n---\n",
                encoding="utf-8",
            )
            db = root / "vault_index.db"

            result = vault_index.sync_vault(vault_root=vault, db_path=db)
            plan = vault_index.task_plan("journal-club")
            search = vault_index.search_sections(
                "hybrid epilepsy comparator",
                db_path=db,
                task="journal-club",
                limit=5,
            )

            self.assertTrue(result["ok"], result)
            self.assertTrue(plan["ok"], plan)
            self.assertIn("evidence_card", plan["preferred_section_types"])
            self.assertTrue(any(hit["folder"] == "Journal Club" for hit in search["hits"]))

    def _build_linked_vault(self, root: Path) -> Path:
        vault = root / "vault"
        reports = vault / "Reports"
        concepts = vault / "Concepts"
        brain_dumps = vault / "Brain Dumps"
        for d in (reports, concepts, brain_dumps):
            d.mkdir(parents=True)
        # Anchor report links out to two concepts.
        (reports / "Acute Spinal Cord Injury.md").write_text(
            "**Anchor**: acute SCI management.\n\n"
            "## Related In This Vault\n\n"
            "- [[Concepts/MAP Augmentation|MAP Augmentation]]\n"
            "- [[Concepts/Steroid Decision|Steroid Decision]]\n\n"
            "---\ndomain: spine\nsummary: \"Acute spinal cord injury anchor.\"\n"
            "tags: [type/report, domain/spine]\n---\n",
            encoding="utf-8",
        )
        (concepts / "MAP Augmentation.md").write_text(
            "**MAP Augmentation**: vasopressor target.\n\n"
            "---\ndomain: spine\nsummary: \"MAP goals in SCI.\"\ntags: [type/concept, domain/spine]\n---\n",
            encoding="utf-8",
        )
        (concepts / "Steroid Decision.md").write_text(
            "**Steroid Decision**: NASCIS controversy.\n\n"
            "---\ndomain: spine\nsummary: \"Steroid decision in SCI.\"\ntags: [type/concept, domain/spine]\n---\n",
            encoding="utf-8",
        )
        # A brain dump links *into* the anchor (inbound edge).
        (brain_dumps / "SCI Service Note.md").write_text(
            "## Clinical Focus\n\n- Inbound link test.\n\n"
            "## Related In This Vault\n\n- [[Reports/Acute Spinal Cord Injury|Acute Spinal Cord Injury]]\n\n"
            "---\ndomain: spine\nsummary: \"Service note linking to the anchor.\"\n"
            "tags: [type/reference, domain/spine]\n---\n",
            encoding="utf-8",
        )
        return vault

    def _catalog(self, root: Path) -> Path:
        path = root / "acgme.json"
        path.write_text(json.dumps({
            "milestones": {
                "SPINE": {"name": "Spine", "topics": [
                    {"title": "Acute Spinal Cord Injury - ASIA Classification",
                     "domain": "spine", "pgy_target": 1, "priority": "core"},
                    {"title": "Brain Tumor Craniotomy",
                     "domain": "tumor", "pgy_target": 3, "priority": "important"},
                ]},
            },
            "total_topics": 2,
        }), encoding="utf-8")
        return path

    def test_landscape_traverses_wikilinks_with_branching_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = self._build_linked_vault(root)
            db = root / "vault_index.db"
            catalog = self._catalog(root)
            vault_index.sync_vault(vault_root=vault, db_path=db)

            res = vault_index.landscape_map(
                db_path=db, catalog_path=catalog,
                note="Reports/Acute Spinal Cord Injury.md", max_neighbors=8,
            )
            self.assertTrue(res["ok"], res)
            titles = {n["title"] for n in res["neighbors"]}
            # Outbound concept links and the inbound brain-dump link are all found.
            self.assertIn("MAP Augmentation", titles)
            self.assertIn("Steroid Decision", titles)
            self.assertIn("SCI Service Note", titles)
            directions = {n["title"]: n["direction"] for n in res["neighbors"]}
            self.assertEqual(directions["MAP Augmentation"], "outbound")
            self.assertEqual(directions["SCI Service Note"], "inbound")
            # Adjacency comes from the wikilink graph, never embedding similarity.
            self.assertEqual(res["adjacency_source"], "vault_wikilinks+acgme_catalog")

    def test_landscape_branching_factor_is_capped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = self._build_linked_vault(root)
            db = root / "vault_index.db"
            catalog = self._catalog(root)
            vault_index.sync_vault(vault_root=vault, db_path=db)

            res = vault_index.landscape_map(
                db_path=db, catalog_path=catalog,
                note="Reports/Acute Spinal Cord Injury.md", max_neighbors=1,
            )
            self.assertEqual(res["neighbor_count"], 1)
            self.assertGreaterEqual(res["neighbors_available"], 3)
            self.assertLessEqual(len(res["neighbors"]), 1)

    def test_landscape_acgme_neighbors_match_token_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = self._build_linked_vault(root)
            db = root / "vault_index.db"
            catalog = self._catalog(root)
            vault_index.sync_vault(vault_root=vault, db_path=db)

            res = vault_index.landscape_map(
                db_path=db, catalog_path=catalog,
                note="Reports/Acute Spinal Cord Injury.md", max_neighbors=8,
            )
            competencies = {a["competency"] for a in res["acgme_neighbors"]}
            self.assertIn("Acute Spinal Cord Injury - ASIA Classification", competencies)
            # An unrelated competency (tumor) must not appear.
            self.assertNotIn("Brain Tumor Craniotomy", competencies)

    def test_refresh_after_vault_write_skips_temp_vaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(vault_index, "sync_vault") as sync:
                result = vault_index.refresh_default_index_after_vault_write(
                    vault_root=Path(tmp) / "vault"
                )

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["skipped"], result)
        self.assertEqual("non_default_vault_root", result["reason"])
        sync.assert_not_called()

    def test_refresh_after_vault_write_syncs_default_vault(self) -> None:
        with mock.patch.object(
            vault_index,
            "sync_vault",
            return_value={"ok": True, "notes_indexed": 1, "sections_indexed": 2},
        ) as sync:
            result = vault_index.refresh_default_index_after_vault_write()

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["skipped"], result)
        sync.assert_called_once()

    def test_lance_sync_uses_section_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = self._build_vault(root)
            db = root / "vault_index.db"
            lance_dir = root / "vault.lance"
            vault_index.sync_vault(vault_root=vault, db_path=db)

            def fake_encode(texts: list[str], **_: object) -> list[list[float]]:
                return [[float(idx), 0.0, 1.0] for idx, _text in enumerate(texts)]

            with mock.patch.object(vault_index, "_encode_passages", side_effect=fake_encode):
                result = vault_index.sync_lance(db_path=db, lance_dir=lance_dir, table_name="vault_notes")

            self.assertTrue(result["ok"], result)
            self.assertGreater(result["sections_embedded"], 0)
            import lancedb

            table = lancedb.connect(str(lance_dir)).open_table("vault_notes")
            rows = table.head(1).to_pylist()
            self.assertGreater(len(rows), 0)
            self.assertIn("Section:", rows[0]["embedding_text"])
            self.assertIn("text", rows[0])
            with mock.patch.object(vault_index, "_encode_passages", return_value=[[0.0, 0.0, 1.0]]):
                search = vault_index.search_lance(
                    "ENRICH lobar hemorrhage",
                    lance_dir=lance_dir,
                    table_name="vault_notes",
                    limit=1,
                )
            self.assertTrue(search["ok"], search)
            self.assertEqual(search["count"], 1)

    def test_recall_packet_combines_sqlite_and_lance_hits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = self._build_vault(root)
            db = root / "vault_index.db"
            vault_index.sync_vault(vault_root=vault, db_path=db)

            vector_hit = {
                "section_id": "semantic-only",
                "note_path": "Concepts/ENRICH Trial.md",
                "title": "ENRICH Trial",
                "folder": "Concepts",
                "note_type": "concept",
                "summary": "Semantic selection context.",
                "section_heading": "Evidence Card",
                "section_type": "evidence_card",
                "section_path": "Concepts/ENRICH Trial.md#Evidence Card",
                "text": "Semantic vector hit about selected lobar hemorrhage trial evidence.",
                "references": [],
                "wikilinks": [],
                "provenance_tier": "curated_vault_context",
                "source_role": "personalized_supplement",
                "score": 0.91,
            }
            with mock.patch.object(
                vault_index,
                "search_lance",
                return_value={
                    "ok": True,
                    "query": "ENRICH lobar hemorrhage",
                    "hits": [vector_hit],
                    "count": 1,
                    "retriever": "lancedb",
                    "knowledge_boundary": vault_index.KNOWLEDGE_BOUNDARY,
                },
            ) as vector_search:
                packet = vault_index.recall_packet(
                    "ENRICH lobar hemorrhage",
                    db_path=db,
                    task="weak-spot-review",
                    limit=8,
                )

            self.assertTrue(packet["ok"], packet)
            self.assertEqual(packet["schema"], "vault_intelligence_compact_v1")
            self.assertEqual(packet["retrieval_status"], "complete")
            self.assertTrue(packet["retrieval_plan"]["combined"])
            self.assertGreaterEqual(packet["sqlite"]["count"], 1)
            self.assertEqual(packet["vector"]["count"], 1)
            self.assertEqual(packet["warnings"], [])
            self.assertIn("evidence_card", packet["field_context"])
            self.assertTrue(any("sqlite" in hit["retrievers"] for hit in packet["merged_hits"]))
            self.assertTrue(any("lance" in hit["retrievers"] for hit in packet["merged_hits"]))
            self.assertTrue(json.dumps(packet, separators=(",", ":")))
            vector_search.assert_called_once()

    def test_recall_packet_keeps_sqlite_context_when_lance_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = self._build_vault(root)
            db = root / "vault_index.db"
            vault_index.sync_vault(vault_root=vault, db_path=db)

            with mock.patch.object(
                vault_index,
                "search_lance",
                side_effect=RuntimeError("vector index unavailable"),
            ):
                packet = vault_index.recall_packet(
                    "ENRICH lobar hemorrhage MISTIE",
                    db_path=db,
                    task="concept-repair",
                    limit=5,
                )

            self.assertTrue(packet["ok"], packet)
            self.assertEqual(packet["retrieval_status"], "partial")
            self.assertTrue(packet["sqlite"]["ok"])
            self.assertFalse(packet["vector"]["ok"])
            self.assertGreaterEqual(packet["sqlite"]["count"], 1)
            self.assertTrue(packet["merged_hits"])
            self.assertTrue(any("LanceDB semantic retrieval failed" in warning for warning in packet["warnings"]))

    def test_cli_sync_and_search_return_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = self._build_vault(root)
            db = root / "vault_index.db"

            sync = vault_index.sync_vault(vault_root=vault, db_path=db)
            search = vault_index.search_sections("ENRICH", db_path=db, task="trial-evidence", limit=1)

            self.assertTrue(json.dumps(sync))
            self.assertTrue(json.dumps(search))
            self.assertEqual(search["hits"][0]["folder"], "Concepts")


if __name__ == "__main__":
    unittest.main()
