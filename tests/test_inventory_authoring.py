"""Pillar C: inventory node-addition protocol — dedup guard, validation, apply."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import concept_inventory  # noqa: E402
import inventory_authoring  # noqa: E402


class _InventoryFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.inv_dir = Path(self.tmp.name) / "sources"
        self.inv_dir.mkdir()
        self.db_path = Path(self.tmp.name) / "inv.db"
        vascular = {
            "domain": "vascular", "code": "vasc", "display_name": "Vascular Neurosurgery",
            "topics": [{"id": "vasc.sah", "name": "Subarachnoid Hemorrhage", "blurb": "SAH."}],
            "concepts": [
                {"id": "vasc.sah.vasospasm", "name": "Cerebral vasospasm", "topic": "vasc.sah",
                 "type": "pathology", "tier": "core", "blurb": "Arterial narrowing after SAH.",
                 "aliases": ["vasospasm"], "prereqs": [], "discriminators": [], "related": []},
                {"id": "vasc.sah.dci", "name": "Delayed cerebral ischemia", "topic": "vasc.sah",
                 "type": "pathology", "tier": "core", "blurb": "Deterioration after SAH.",
                 "aliases": ["dci"], "prereqs": [], "discriminators": [], "related": []},
            ],
        }
        (self.inv_dir / "vascular.json").write_text(json.dumps(vascular))
        self._patches = [
            unittest.mock.patch.object(concept_inventory, "INVENTORY_DIR", self.inv_dir),
            unittest.mock.patch.object(concept_inventory, "DB_PATH", self.db_path),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def _inv(self):
        return concept_inventory._open_inventory(self.inv_dir, self.db_path)


class ProposeTests(_InventoryFixture):
    def test_genuine_gap(self) -> None:
        inv = self._inv()
        # A name with no token overlap with existing nodes is a clean gap.
        report = inventory_authoring.propose_node(
            inv, name="Lumbar drain placement", domain="vascular",
            concept_type="management", tier="core",
            blurb="External lumbar CSF drainage after SAH.", topic_id="vasc.sah",
            prereqs=["vasc.sah.vasospasm"],
        )
        inv.close()
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["gap_assessment"], "genuine_gap")
        self.assertEqual(report["placement"]["concept_id"], "vasc.sah.lumbar-drain-placement")
        self.assertEqual(report["connections"]["prereqs"], ["vasc.sah.vasospasm"])

    def test_adjacent_node_is_not_blocked(self) -> None:
        inv = self._inv()
        report = inventory_authoring.propose_node(
            inv, name="Nimodipine for vasospasm prophylaxis", domain="vascular",
            concept_type="pharmacology", tier="core",
            blurb="Oral nimodipine reduces DCI after SAH.", topic_id="vasc.sah",
            aliases=["nimodipine"], prereqs=["vasc.sah.vasospasm"],
        )
        inv.close()
        self.assertTrue(report["ok"])
        # adjacent (shares "vasospasm") but not a duplicate -> safe to add
        self.assertNotEqual(report["gap_assessment"], "possible_duplicate")

    def test_duplicate_blocked(self) -> None:
        inv = self._inv()
        report = inventory_authoring.propose_node(
            inv, name="Cerebral vasospasm", domain="vascular", concept_type="pathology",
            tier="core", blurb="Arterial narrowing.", topic_id="vasc.sah",
        )
        inv.close()
        self.assertEqual(report["gap_assessment"], "possible_duplicate")
        self.assertTrue(any(n["score"] >= 0.7 for n in report["near_duplicates"]))

    def test_invalid_edge_id_errors(self) -> None:
        inv = self._inv()
        report = inventory_authoring.propose_node(
            inv, name="New SAH concept", domain="vascular", concept_type="management",
            tier="core", blurb="Something.", topic_id="vasc.sah", prereqs=["vasc.sah.nonexistent"],
        )
        inv.close()
        self.assertFalse(report["ok"])
        self.assertTrue(any("unknown inventory ids" in e for e in report["errors"]))

    def test_invalid_type_and_tier_errors(self) -> None:
        inv = self._inv()
        report = inventory_authoring.propose_node(
            inv, name="X", domain="vascular", concept_type="not-a-type", tier="not-a-tier",
            blurb="b", topic_id="vasc.sah",
        )
        inv.close()
        self.assertFalse(report["ok"])
        self.assertTrue(any("invalid type" in e for e in report["errors"]))
        self.assertTrue(any("invalid tier" in e for e in report["errors"]))


class ApplyTests(_InventoryFixture):
    def test_apply_writes_validates_and_rebuilds(self) -> None:
        inv = self._inv()
        report = inventory_authoring.propose_node(
            inv, name="Nimodipine for vasospasm prophylaxis", domain="vascular",
            concept_type="pharmacology", tier="core",
            blurb="Oral nimodipine reduces DCI after SAH.", topic_id="vasc.sah",
            aliases=["nimodipine"], prereqs=["vasc.sah.vasospasm"], related=["vasc.sah.dci"],
        )
        inv.close()
        result = inventory_authoring.apply_node(report)
        self.assertTrue(result["ok"], result.get("errors"))
        # The node is now present and the rebuilt DB resolves it.
        inv2 = self._inv()
        row = inv2.execute(
            "SELECT id, type, tier FROM concepts WHERE id = ?",
            ("vasc.sah.nimodipine-for-vasospasm-prophylaxis",),
        ).fetchone()
        edge = inv2.execute(
            "SELECT 1 FROM edges WHERE src = ? AND dst = ? AND edge_type = 'prereq'",
            ("vasc.sah.nimodipine-for-vasospasm-prophylaxis", "vasc.sah.vasospasm"),
        ).fetchone()
        inv2.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["type"], "pharmacology")
        self.assertIsNotNone(edge)  # the prereq edge wired correctly

    def test_apply_creates_new_topic(self) -> None:
        inv = self._inv()
        report = inventory_authoring.propose_node(
            inv, name="Spinal AVM embolization", domain="vascular", concept_type="operative",
            tier="advanced", blurb="Endovascular treatment of spinal AVM.",
            topic_name="Spinal Vascular Malformations",
        )
        inv.close()
        self.assertEqual(report["placement"]["topic_status"], "new")
        result = inventory_authoring.apply_node(report)
        self.assertTrue(result["ok"], result.get("errors"))
        inv2 = self._inv()
        topic = inv2.execute("SELECT 1 FROM topics WHERE id = ?", ("vasc.spinal-vascular-malformations",)).fetchone()
        inv2.close()
        self.assertIsNotNone(topic)


class CanonicalFormatTests(unittest.TestCase):
    def test_canonical_dump_is_one_per_line_and_idempotent(self) -> None:
        doc = {
            "domain": "vascular", "code": "vasc", "display_name": "Vascular",
            "topics": [{"id": "vasc.sah", "name": "SAH", "blurb": "x"}],
            "concepts": [
                {"id": "vasc.sah.a", "name": "A", "topic": "vasc.sah", "type": "pathology",
                 "tier": "core", "blurb": "b", "aliases": ["a1"], "prereqs": [], "discriminators": [], "related": []},
                {"id": "vasc.sah.b", "name": "B", "topic": "vasc.sah", "type": "management",
                 "tier": "core", "blurb": "b", "aliases": [], "prereqs": [], "discriminators": [], "related": []},
            ],
        }
        out = inventory_authoring.canonical_dump(doc)
        # each concept on exactly one line; arrays inline
        concept_lines = [l for l in out.splitlines() if l.strip().startswith('{"id": "vasc.sah.')]
        self.assertEqual(len(concept_lines), 2)
        self.assertNotIn('\n      "aliases"', out)  # no exploded multi-line arrays
        # content round-trips and re-dump is identical (idempotent)
        self.assertEqual(json.loads(out), doc)
        self.assertEqual(inventory_authoring.canonical_dump(json.loads(out)), out)


class AddAliasesTests(unittest.TestCase):
    """add_aliases must enrich existing nodes in both JSON layouts."""

    def _run(self, indent):
        tmp = tempfile.TemporaryDirectory()
        inv_dir = Path(tmp.name) / "sources"
        inv_dir.mkdir()
        db_path = Path(tmp.name) / "inv.db"
        doc = {
            "domain": "vascular", "code": "vasc", "display_name": "Vascular",
            "topics": [{"id": "vasc.sah", "name": "SAH", "blurb": "x"}],
            "concepts": [{
                "id": "vasc.sah.vasospasm", "name": "Cerebral vasospasm", "topic": "vasc.sah",
                "type": "pathology", "tier": "core", "blurb": "Arterial narrowing.",
                "aliases": ["vasospasm"], "prereqs": [], "discriminators": [], "related": [],
            }],
        }
        (inv_dir / "vascular.json").write_text(_multiline(doc) if indent else _one_per_line(doc))
        patches = [
            unittest.mock.patch.object(concept_inventory, "INVENTORY_DIR", inv_dir),
            unittest.mock.patch.object(concept_inventory, "DB_PATH", db_path),
        ]
        for p in patches:
            p.start()
        try:
            result = inventory_authoring.add_aliases({"vasc.sah.vasospasm": ["angiographic vasospasm", "vasospasm"]})
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["aliases_added"], 1)  # one new, "vasospasm" deduped
            conn = concept_inventory._open_inventory(inv_dir, db_path)
            aliases = {r["alias"] for r in conn.execute(
                "SELECT alias FROM aliases WHERE concept_id='vasc.sah.vasospasm'")}
            conn.close()
            self.assertIn("angiographic vasospasm", aliases)
        finally:
            for p in patches:
                p.stop()
            tmp.cleanup()

    def test_multiline_format(self) -> None:
        self._run(indent=2)

    def test_one_per_line_format(self) -> None:
        self._run(indent=0)


def _one_per_line(doc) -> str:
    import json as _json
    lines = ['{', f'  "domain": "{doc["domain"]}",', f'  "code": "{doc["code"]}",',
             f'  "display_name": "{doc["display_name"]}",', '  "topics": [',
             "    " + _json.dumps(doc["topics"][0], separators=(", ", ": ")), "  ],", '  "concepts": [',
             "    " + _json.dumps(doc["concepts"][0], separators=(", ", ": ")), "  ]", "}"]
    return "\n".join(lines) + "\n"


def _multiline(doc) -> str:
    """Real inventory layout: concept fields on their own lines, arrays inline."""
    import json as _json
    c = doc["concepts"][0]
    lines = [
        '{',
        f'  "domain": "{doc["domain"]}",',
        f'  "code": "{doc["code"]}",',
        f'  "display_name": "{doc["display_name"]}",',
        '  "topics": [',
        "    " + _json.dumps(doc["topics"][0], separators=(", ", ": ")),
        "  ],",
        '  "concepts": [',
        "    {",
        f'      "id": "{c["id"]}",',
        f'      "name": "{c["name"]}",',
        f'      "topic": "{c["topic"]}",',
        f'      "type": "{c["type"]}",',
        f'      "tier": "{c["tier"]}",',
        f'      "blurb": "{c["blurb"]}",',
        '      "aliases": ' + _json.dumps(c["aliases"], separators=(", ", ": ")) + ',',
        '      "prereqs": [],',
        '      "discriminators": [],',
        '      "related": []',
        "    }",
        "  ]",
        "}",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    unittest.main()
