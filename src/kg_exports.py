#!/usr/bin/env python3
"""Vault/export reporting mixin for KnowledgeGraph."""

from __future__ import annotations

import json
import re
import sys
from collections import OrderedDict
from kg_constants import DATA_DIR
from vault_kg_sync import stub_filename


class KnowledgeGraphExportMixin:
    """Obsidian/Error Atlas/ACGME export helpers."""

    # ------------------------------------------------------------------
    # Obsidian Redesign — Error Atlas, Concept Stubs, ACGME Readiness
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_short_concept_name(concept_text: str) -> str:
        """Extract a short display name from a full concept description.

        Priority:
        1. ALL-CAPS abbreviation inside parentheses (2–6 chars), e.g. (CSW)
        2. First word if it is an ALL-CAPS abbreviation (2–6 chars)
        3. First 3 significant words (stopwords stripped), title-cased
        """
        # 1. Abbreviation in parens
        m = re.search(r'\(([A-Z]{2,6})\)', concept_text)
        if m:
            return m.group(1)
        # 2. First word looks like an abbreviation
        first = concept_text.split()[0].strip('(),;:') if concept_text.split() else ""
        if re.match(r'^[A-Z]{2,6}$', first):
            return first
        # 3. First 3 significant words
        _STOP = {'the', 'a', 'an', 'of', 'in', 'for', 'and', 'or', 'at', 'vs',
                 'to', 'is', 'are', 'was', 'with', 'by', 'from', 'on', 'after',
                 'during', 'following', 'post', 'pre'}
        words = [w.strip('(),;:—-') for w in concept_text.split()]
        sig = [w for w in words if w and w.lower() not in _STOP][:3]
        result = ' '.join(sig)
        # Title-case but preserve existing capitalisation where possible
        return result if result else concept_text[:20]

    @staticmethod
    def _domain_to_tag(domain: str) -> str:
        """Convert a domain name to a lowercase hyphenated tag."""
        tag = domain.lower()
        tag = re.sub(r'[—–&]', '-', tag)
        tag = re.sub(r'[^\w\s\-]', '', tag)
        tag = re.sub(r'\s+', '-', tag.strip())
        tag = re.sub(r'-+', '-', tag)
        # Shorten long milestone names
        _MAP = {
            'medical-knowledge--neuroanatomy-and-neuroimaging': 'medical-knowledge-neuroanatomy',
            'medical-knowledge--neurosciences-neuropathology-and-neurology': 'medical-knowledge-neurosciences',
            'surgical-treatment-of-epilepsy-and-movement-disorders': 'epilepsy-movement-disorders',
            'pain-and-peripheral-nerve-disorders': 'pain-peripheral-nerve',
            'pediatric-neurological-surgery': 'pediatric',
            'critical-care--general-neurosurgery': 'critical-care',
        }
        return _MAP.get(tag, tag)

    def _load_misconceptions_for_key(self, key: str) -> tuple[list[dict], int]:
        """Return recent misconception rows whose text matches a key fragment."""
        if not key:
            return [], 0
        rows = self.conn.execute(
            """SELECT concept_text, misconception, times_missed, last_updated
               FROM concept_mastery
               WHERE LOWER(misconception) LIKE ? AND times_missed > 0
               ORDER BY times_missed DESC LIMIT 3""",
            (f"%{key}%",),
        ).fetchall()
        misconceptions = [
            {
                "concept": r["concept_text"],
                "misconception": r["misconception"],
                "times_missed": r["times_missed"],
                "last_updated": str(r["last_updated"] or "")[:10],
            }
            for r in rows
        ]
        return misconceptions, sum(r["times_missed"] for r in rows)

    def generate_error_atlas(self) -> list[dict]:
        """Export all confusable pairs for Error Atlas vault generation.

        Merges confusion_matrix.json + concept_relationships WHERE relationship =
        'confusable_with'. For each pair queries concept_mastery for any logged
        misconceptions matching either concept (case-insensitive substring).

        Returns list of dicts:
          slug, short_a, short_b, concept_a, concept_b, disambiguation_axis,
          source, first_added, times_confused, misconceptions_a, misconceptions_b
        """
        pairs: list[dict] = []
        seen: set[frozenset] = set()  # dedup by (normalized_a, normalized_b)

        # ── Source 1: confusion_matrix.json ──
        cm_path = DATA_DIR / "confusion_matrix.json"
        if cm_path.exists():
            try:
                raw = json.loads(cm_path.read_text(encoding="utf-8"))
                for p in raw:
                    ca = p.get("concept_a", "")
                    cb = p.get("concept_b", "")
                    key = frozenset([ca.lower()[:40], cb.lower()[:40]])
                    if key in seen:
                        continue
                    seen.add(key)
                    pairs.append({
                        "concept_a": ca,
                        "concept_b": cb,
                        "disambiguation_axis": p.get("disambiguation_axis", ""),
                        "source": p.get("source", "manual"),
                        "first_added": str(p.get("first_added", ""))[:10],
                    })
            except Exception as exc:
                print(f"[generate_error_atlas] confusion_matrix.json error: {exc}", file=sys.stderr)

        # ── Source 2: concept_relationships (confusable_with) ──
        try:
            rows = self.conn.execute(
                """SELECT concept_a, concept_b, notes, source, created_ts
                   FROM concept_relationships WHERE relationship = 'confusable_with'"""
            ).fetchall()
            for row in rows:
                ca, cb = row["concept_a"], row["concept_b"]
                key = frozenset([ca.lower()[:40], cb.lower()[:40]])
                if key in seen:
                    continue
                seen.add(key)
                pairs.append({
                    "concept_a": ca,
                    "concept_b": cb,
                    "disambiguation_axis": row["notes"] or "",
                    "source": row["source"] or "kg",
                    "first_added": str(row["created_ts"] or "")[:10],
                })
        except Exception as exc:
            print(f"[generate_error_atlas] concept_relationships error: {exc}", file=sys.stderr)

        # ── Enrich each pair with short names, slug, misconception records ──
        result = []
        for p in pairs:
            short_a = self._extract_short_concept_name(p["concept_a"])
            short_b = self._extract_short_concept_name(p["concept_b"])
            slug_raw = f"{short_a}_vs_{short_b}".lower().replace(" ", "_")
            slug = re.sub(r'[^\w]', '', slug_raw)

            # Query concept_mastery for misconceptions matching either concept
            misconceptions_a: list[dict] = []
            misconceptions_b: list[dict] = []
            times_confused = 0
            try:
                # Use first significant word as search key (avoid over-broad matches)
                key_a = short_a.split()[0].lower() if short_a.split() else ""
                key_b = short_b.split()[0].lower() if short_b.split() else ""
                misconceptions_a, confused_a = self._load_misconceptions_for_key(key_a)
                misconceptions_b, confused_b = self._load_misconceptions_for_key(key_b)
                times_confused += confused_a + confused_b
            except Exception:
                pass

            result.append({
                "slug": slug,
                "short_a": short_a,
                "short_b": short_b,
                "concept_a": p["concept_a"],
                "concept_b": p["concept_b"],
                "disambiguation_axis": p["disambiguation_axis"],
                "source": p["source"],
                "first_added": p["first_added"],
                "times_confused": times_confused,
                "misconceptions_a": misconceptions_a,
                "misconceptions_b": misconceptions_b,
            })

        return result

    def export_concept_stubs(self, only_studied: bool = False) -> list[dict]:
        """Export curriculum topics for Obsidian concept stub generation.

        Returns one dict per curriculum topic with all data needed to write a stub
        file. Uses GROUP BY curriculum_id + MAX() aggregation to handle cases where
        multiple topics rows join to the same curriculum_id (KG normalisation artefact).

        Args:
            only_studied: If True, return only topics with encounter_count > 0.
        """
        _DEPTH_LABELS = {0: "not_studied", 1: "surface", 2: "mechanistic",
                         3: "decision-making", 4: "expert", 5: "mastery"}
        _PRIORITY_LABELS = {1: "core", 2: "advanced", 3: "specialty"}

        # Load confusion_matrix.json once for confusable pair matching
        cm_path = DATA_DIR / "confusion_matrix.json"
        confusion_pairs: list[dict] = []
        if cm_path.exists():
            try:
                confusion_pairs = json.loads(cm_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        where = "WHERE 1=1"
        if only_studied:
            where = "HAVING MAX(COALESCE(t.encounter_count, 0)) > 0"

        try:
            rows = self.conn.execute(
                f"""SELECT ct.curriculum_id,
                           ct.topic_name   AS slug,
                           ct.display_name AS title,
                           ct.domain,
                           ct.acgme_milestone,
                           ct.pgy_target,
                           ct.priority,
                           MAX(COALESCE(t.confidence, 0.0))     AS confidence,
                           MAX(COALESCE(t.encounter_count, 0))  AS encounter_count,
                           MAX(COALESCE(t.depth, 0))            AS depth,
                           MAX(t.last_seen)                     AS last_seen
                    FROM curriculum_topics ct
                    LEFT JOIN topics t ON t.curriculum_id = ct.curriculum_id
                    GROUP BY ct.curriculum_id
                    {where if only_studied else ''}
                    ORDER BY ct.domain, ct.pgy_target, ct.priority"""
            ).fetchall()
        except Exception as exc:
            print(f"[export_concept_stubs] query error: {exc}", file=sys.stderr)
            return []

        # Apply only_studied filter post-query if not in HAVING clause
        if only_studied:
            rows = [r for r in rows if (r["encounter_count"] or 0) > 0]

        result = []
        for row in rows:
            enc = row["encounter_count"] or 0
            conf = round(float(row["confidence"] or 0.0), 4)
            depth = int(row["depth"] or 0)
            pgy = int(row["pgy_target"] or 1)
            priority = int(row["priority"] or 2)
            title = row["title"] or row["slug"] or ""

            # Status
            if enc == 0:
                status = "not_studied"
            elif conf >= 0.15 and depth >= 2:
                status = "known"
            else:
                status = "gap"

            # Confusable atlas entries: any pair whose concept_a or concept_b
            # contains the slug as a case-insensitive substring
            atlas_entries: list[str] = []
            slug_lower = (row["slug"] or "").lower().replace("_", " ")
            for cp in confusion_pairs:
                ca_lower = (cp.get("concept_a") or "").lower()
                cb_lower = (cp.get("concept_b") or "").lower()
                # Match if any word from the slug appears in either concept
                slug_words = [w for w in slug_lower.split() if len(w) > 4]
                if any(w in ca_lower or w in cb_lower for w in slug_words):
                    sa = self._extract_short_concept_name(cp.get("concept_a", ""))
                    sb = self._extract_short_concept_name(cp.get("concept_b", ""))
                    entry = f"{sa} vs {sb}"
                    if entry not in atlas_entries:
                        atlas_entries.append(entry)

            result.append({
                "filename": stub_filename(title),
                "title": title,
                "slug": row["slug"] or "",
                "domain": row["domain"] or "",
                "domain_tag": self._domain_to_tag(row["domain"] or ""),
                "acgme_milestone": row["acgme_milestone"] or "",
                "pgy_target": pgy,
                "priority": priority,
                "priority_label": _PRIORITY_LABELS.get(priority, "advanced"),
                "studied": enc > 0,
                "confidence": conf,
                "depth": depth,
                "depth_label": _DEPTH_LABELS.get(depth, "not_studied"),
                "encounter_count": enc,
                "last_studied": str(row["last_seen"] or "")[:10] or None,
                "status": status,
                "confusable_atlas_entries": atlas_entries,
            })

        return result

    def acgme_readiness(self, pgy: int | None = None) -> dict:
        """Generate ACGME readiness data for the given PGY year.

        Filters curriculum_topics WHERE pgy_target <= pgy and aggregates by domain.
        Reads data/pgy_config.json for the default PGY year when pgy is None.

        Returns structured dict with per-domain breakdowns and per-topic study status.
        """
        # Determine PGY year
        if pgy is None:
            config_path = DATA_DIR / "pgy_config.json"
            try:
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
                pgy = int(cfg.get("current_pgy", 1))
            except Exception:
                pgy = 1

        _DEPTH_LABELS = {0: "Not studied", 1: "Surface", 2: "Mechanistic",
                         3: "Decision-making", 4: "Expert", 5: "Mastery"}

        try:
            rows = self.conn.execute(
                """SELECT ct.curriculum_id, ct.domain, ct.acgme_milestone,
                          ct.display_name, ct.topic_name, ct.priority,
                          ct.pgy_target,
                          MAX(COALESCE(t.confidence, 0.0))    AS confidence,
                          MAX(COALESCE(t.encounter_count, 0)) AS encounter_count,
                          MAX(COALESCE(t.depth, 0))           AS depth,
                          MAX(t.last_seen)                    AS last_seen
                   FROM curriculum_topics ct
                   LEFT JOIN topics t ON t.curriculum_id = ct.curriculum_id
                   WHERE ct.pgy_target <= ?
                   GROUP BY ct.curriculum_id
                   ORDER BY ct.domain, confidence DESC""",
                (pgy,)
            ).fetchall()
        except Exception as exc:
            print(f"[acgme_readiness] query error: {exc}", file=sys.stderr)
            return {"current_pgy": pgy, "total_in_scope": 0, "domains": [], "error": str(exc)}

        # Aggregate
        total_in_scope = len(rows)
        topics_touched = sum(1 for r in rows if (r["encounter_count"] or 0) > 0)
        topics_at_target = sum(
            1 for r in rows
            if (r["confidence"] or 0) >= 0.15 and (r["depth"] or 0) >= 2
        )
        topics_never_studied = total_in_scope - topics_touched

        # Group by domain (preserve ordering of first occurrence)
        from collections import OrderedDict
        domain_map: dict[str, dict] = OrderedDict()
        for row in rows:
            domain = row["domain"] or "General"
            if domain not in domain_map:
                domain_map[domain] = {
                    "domain": domain,
                    "acgme_milestone": row["acgme_milestone"] or "",
                    "total_topics": 0,
                    "topics_touched": 0,
                    "topics_at_target": 0,
                    "coverage_pct": 0.0,
                    "avg_confidence": 0.0,
                    "_conf_sum": 0.0,
                    "_conf_count": 0,
                    "topics": [],
                }
            d = domain_map[domain]
            d["total_topics"] += 1
            enc = row["encounter_count"] or 0
            conf = float(row["confidence"] or 0.0)
            depth = int(row["depth"] or 0)
            studied = enc > 0
            at_target = conf >= 0.15 and depth >= 2

            if studied:
                d["topics_touched"] += 1
                d["_conf_sum"] += conf
                d["_conf_count"] += 1
            if at_target:
                d["topics_at_target"] += 1

            title = row["display_name"] or row["topic_name"] or ""
            stub_file = stub_filename(title).replace('.md', '')

            d["topics"].append({
                "display_name": title,
                "slug": row["topic_name"] or "",
                "pgy_target": int(row["pgy_target"] or 1),
                "priority": int(row["priority"] or 2),
                "studied": studied,
                "confidence": round(conf, 4),
                "depth": depth,
                "depth_label": _DEPTH_LABELS.get(depth, "Not studied"),
                "encounter_count": enc,
                "last_studied": str(row["last_seen"] or "")[:10] or None,
                "at_target": at_target,
                "concept_stub": f"Concepts/{stub_file}",
            })

        # Finalize per-domain stats
        domains = []
        for d in domain_map.values():
            total = d["total_topics"]
            touched = d["topics_touched"]
            d["coverage_pct"] = round(touched / total * 100, 1) if total > 0 else 0.0
            d["avg_confidence"] = round(d["_conf_sum"] / d["_conf_count"], 4) if d["_conf_count"] > 0 else 0.0
            del d["_conf_sum"], d["_conf_count"]
            # Sort topics: studied first (by confidence desc), then unstudied
            d["topics"].sort(key=lambda t: (-int(t["studied"]), -t["confidence"]))
            domains.append(d)

        # Sort domains by coverage_pct ascending (most-needed first)
        domains.sort(key=lambda d: d["coverage_pct"])

        return {
            "current_pgy": pgy,
            "total_in_scope": total_in_scope,
            "topics_at_target": topics_at_target,
            "topics_touched": topics_touched,
            "topics_never_studied": topics_never_studied,
            "coverage_pct": round(topics_at_target / total_in_scope * 100, 1) if total_in_scope > 0 else 0.0,
            "domains": domains,
        }
