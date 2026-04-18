#!/usr/bin/env python3
"""Adaptive learning, session, and curriculum mixin for KnowledgeGraph."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone

from kg_constants import ABBREVIATION_MAP, DATA_DIR


class KnowledgeGraphLearningMixin:
    """Learner context, review queues, session narratives, and curriculum helpers."""

    # ------------------------------------------------------------------
    # Prefrontal Cortex — Learner-Aware Context Injection
    # ------------------------------------------------------------------

    _DEPTH_LABELS = {0: "never-seen", 1: "surface", 2: "mechanistic", 3: "decision-making"}

    # Stop words for topic fingerprinting (broader than _STOP_WORDS — excludes clinical generics)
    _FP_STOPWORDS = frozenset({
        "in", "of", "the", "a", "an", "and", "or", "with", "after", "from",
        "for", "to", "at", "by", "on", "is", "are", "was", "were", "be",
        "this", "that", "these", "those", "when", "then", "into", "upon",
        "over", "under", "above", "during", "before", "between", "versus",
        "new", "newly", "acute", "chronic", "per", "post", "pre", "non",
        "high", "low", "mild", "moderate", "severe", "grade",
    })

    # Words too generic to match on individually
    _STOP_WORDS = {
        "the", "and", "for", "with", "from", "that", "this", "after", "before",
        "during", "between", "about", "into", "through", "management", "treatment",
        "diagnosis", "clinical", "surgical", "approach", "technique", "presentation",
    }

    def _learner_profile_config(self) -> dict:
        """Return optional learner-stage preferences from data/pgy_config.json."""
        try:
            path = DATA_DIR / "pgy_config.json"
            if not path.exists():
                return {}
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _fuzzy_find_topics_in_query(self, query: str) -> list[str]:
        """Find stored topics whose canonical names significantly overlap with the query.

        Uses token overlap scoring: for each stored topic, count how many of its
        significant words appear in the query.  Return topics with >=50% word overlap,
        sorted by overlap ratio descending, capped at 3.
        """
        try:
            query_lower = query.lower()
            query_tokens = set(re.split(r"\W+", query_lower)) - self._STOP_WORDS - {""}

            if len(query_tokens) < 2:
                return []

            # Get all topics with encounters > 0 first, then others
            rows = self.conn.execute(
                "SELECT canonical_name FROM topics ORDER BY encounter_count DESC"
            ).fetchall()

            scored = []
            for r in rows:
                cn = r["canonical_name"]
                cn_tokens = set(re.split(r"\W+", cn)) - self._STOP_WORDS - {""}
                if len(cn_tokens) < 2:
                    continue
                overlap = cn_tokens & query_tokens
                ratio = len(overlap) / len(cn_tokens)
                if ratio >= 0.5 and len(overlap) >= 2:
                    scored.append((ratio, cn))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [s[1] for s in scored[:3]]
        except Exception:
            return []

    def _query_topics_with_fuzzy_fallback(self, query: str) -> list[str]:
        """Extract query topics and add fuzzy KG matches when extraction is too broad."""
        raw_topics = self.extract_topics_from_query(query)
        if len(raw_topics) > 1:
            return raw_topics

        seen = {self._normalize_topic(r) for r in raw_topics}
        for extra in self._fuzzy_find_topics_in_query(query):
            norm = self._normalize_topic(extra)
            if norm not in seen:
                raw_topics.append(extra)
                seen.add(norm)
        return raw_topics

    def _depth_adaptive_guidance(
        self,
        topic: str,
        depth: int,
        confidence: float,
    ) -> tuple[list[str], int]:
        """Return guidance lines and suggested target depth for a topic state."""
        if depth == 0:
            return [
                f"'{topic}' exists in the graph but has never been studied — "
                f"start with a diagnostic probe before deciding how much foundation is needed."
            ], 1
        if depth == 1:
            return [
                f"'{topic}' was seen at surface level (conf={confidence:.2f}) — "
                f"skip the overview, target mechanisms and the 'why'."
            ], 2
        if depth == 2 and confidence < 0.15:
            return [
                f"'{topic}' has been explored mechanistically but confidence is still low "
                f"(conf={confidence:.2f}) — reinforce the mechanism, then bridge to "
                f"clinical application with concrete scenarios."
            ], 2
        if depth == 2:
            return [
                f"'{topic}' has mechanistic understanding (conf={confidence:.2f}) — "
                f"advance to clinical decision-making, surgical indications, and complications."
            ], 3
        if confidence < 0.3:
            return [
                f"'{topic}' has been tested at decision-making level but confidence "
                f"remains low (conf={confidence:.2f}) — there may be a conceptual gap. "
                f"Re-anchor the core mechanism before advancing."
            ], 2
        return [
            f"'{topic}' is at decision-making depth (conf={confidence:.2f}) — "
            f"focus on nuance, controversies, edge cases, and board-style reasoning."
        ], 3

    def _recent_signals_with_summaries(
        self,
        topic_id: int,
        since_iso: str,
    ) -> tuple[list[dict], list]:
        """Return recent signal rows plus any compact concepts_taught metadata."""
        rows = self.conn.execute(
            """SELECT timestamp, source, signal_type, depth_at_event,
                    confidence_delta, metadata
               FROM signal_events
               WHERE topic_id = ? AND timestamp > ?
               ORDER BY timestamp DESC LIMIT 10""",
            (topic_id, since_iso),
        ).fetchall()
        signals: list[dict] = []
        prior_summaries: list = []
        for row in rows:
            signal = dict(row)
            raw_metadata = signal.pop("metadata", None)
            if raw_metadata:
                try:
                    metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else raw_metadata
                    summary = metadata.get("concepts_taught")
                    if summary:
                        prior_summaries.extend(summary if isinstance(summary, list) else [summary])
                    comprehension = metadata.get("comprehension")
                    if comprehension:
                        signal["comprehension"] = comprehension
                except (json.JSONDecodeError, TypeError):
                    pass
            signals.append(signal)
        return signals, prior_summaries

    def _concept_mastery_lists(self, topic_id: int) -> tuple[list[dict], list[dict]]:
        """Return known and unknown concept-mastery summaries for a topic."""
        rows = self.conn.execute(
            """SELECT concept_text, status, times_confirmed, times_missed,
                      error_type, misconception, remediation, last_updated
               FROM concept_mastery WHERE topic_id = ?
               ORDER BY last_updated DESC""",
            (topic_id,),
        ).fetchall()
        known = [
            {"concept": row["concept_text"], "confirmed": row["times_confirmed"]}
            for row in rows if row["status"] == "known"
        ][:5]  # cap — agent doesn't need the full mastered-concepts inventory
        unknown = []
        for row in rows:
            if row["status"] != "unknown":
                continue
            entry = {
                "concept": row["concept_text"],
                "missed": row["times_missed"],
            }
            if row["error_type"]:
                entry["error_type"] = row["error_type"]
            if row["misconception"]:
                entry["misconception"] = row["misconception"]
            if row["remediation"]:
                entry["remediation"] = row["remediation"]
            unknown.append(entry)
        return known, unknown

    @staticmethod
    def _concept_gap_guidance(topic: str, known: list[dict], unknown: list[dict]) -> str | None:
        """Return targeted guidance for topic-specific concept gaps."""
        if not unknown:
            return None
        gap_details = []
        for concept in unknown[:5]:
            detail = concept["concept"]
            if concept.get("misconception"):
                detail += f" (misconception: {concept['misconception']})"
            elif concept.get("error_type"):
                detail += f" ({concept['error_type']})"
            gap_details.append(detail)
        return (
            f"'{topic}' has {len(unknown)} specific concept gap(s): "
            + "; ".join(gap_details)
            + f". Target these directly — do not re-teach the {len(known)} concepts already mastered."
        )

    def _topic_capability_patterns(
        self,
        topic: str,
        topic_id: int,
        source_set: set[str],
        encounters: int,
        err_count: int,
    ) -> list[dict]:
        """Return cross-capability pattern alerts for one topic."""
        patterns = []
        if "rag" in source_set and "bootcamp" not in source_set and encounters >= 2:
            patterns.append({
                "type": "studied_not_tested",
                "topic": topic,
                "message": f"'{topic}' has been studied {encounters}x but never "
                           f"tested in simulation — consider offering a bootcamp scenario.",
            })
        if "bootcamp" in source_set and "rag" not in source_set:
            patterns.append({
                "type": "tested_not_studied",
                "topic": topic,
                "message": f"'{topic}' was encountered in simulation but never "
                           f"studied in depth — foundational knowledge may have gaps.",
            })
        if err_count >= 2 and "rag" in source_set:
            patterns.append({
                "type": "knowledge_application_gap",
                "topic": topic,
                "message": f"'{topic}' has been studied but errors persist — "
                           f"the gap may be in application, not knowledge. "
                           f"A targeted clinical scenario would test transfer.",
            })

        if "anki" in source_set:
            anki_stats = self.conn.execute(
                """SELECT AVG(ease_factor) AS avg_ease, AVG(lapses) AS avg_lapse
                   FROM anki_card_stats
                   WHERE matched_topic_id = ?
                   ORDER BY snapshot_id DESC LIMIT 20""",
                (topic_id,),
            ).fetchone()
            if (
                anki_stats
                and anki_stats["avg_ease"] is not None
                and (anki_stats["avg_ease"] < 2.0 or (anki_stats["avg_lapse"] or 0) >= 3)
            ):
                patterns.append({
                    "type": "anki_struggling",
                    "topic": topic,
                    "message": f"Anki cards for '{topic}' show poor retention "
                               f"(ease={anki_stats['avg_ease']:.1f}, "
                               f"lapses={anki_stats['avg_lapse']:.0f}) — "
                               f"the underlying concept may need re-teaching.",
                })
        return patterns

    def _domain_coverage_pattern(self, topic_contexts: list[dict]) -> dict | None:
        """Return a low-coverage domain alert when all query topics share one domain."""
        domains_seen = {
            cp["domain"]
            for tc in topic_contexts
            if (cp := tc.get("curriculum_priority")) and cp.get("domain")
        }
        if len(domains_seen) != 1:
            return None

        domain = next(iter(domains_seen))
        domain_stats = self.conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN t.encounter_count > 0 THEN 1 ELSE 0 END) AS studied
               FROM curriculum_topics ct
               LEFT JOIN topics t ON t.curriculum_id = ct.curriculum_id
               WHERE ct.domain = ?""",
            (domain,),
        ).fetchone()
        if not domain_stats or domain_stats["total"] <= 0:
            return None

        coverage = round(100 * (domain_stats["studied"] or 0) / domain_stats["total"], 1)
        if coverage >= 10:
            return None
        return {
            "type": "low_domain_coverage",
            "topic": domain,
            "message": f"Domain '{domain}' has only {coverage}% coverage — "
                       f"there are many related topics still unexplored.",
        }

    def _learning_style_summary(self) -> list[dict]:
        """Return compact meta-cognitive learning pattern rows."""
        try:
            rows = self.conn.execute(
                "SELECT pattern_type, description, confidence FROM learning_patterns ORDER BY confidence DESC LIMIT 5"
            ).fetchall()
        except Exception:
            return []
        return [
            {
                "pattern": row["pattern_type"],
                "description": row["description"],
                "confidence": round(row["confidence"], 2),
            }
            for row in rows
        ]

    def _same_topic_review_due(self, topic_contexts: list[dict], now: datetime) -> list[dict]:
        """Return known concepts from the current topics that are due for verification."""
        current_topic_ids = set()
        for tc in topic_contexts:
            if tc.get("canonical"):
                topic = self._find_topic(tc["canonical"])
                if topic:
                    current_topic_ids.add(topic["topic_id"])

        due = []
        for topic_id in current_topic_ids:
            rows = self.conn.execute(
                """SELECT concept_text, times_confirmed, times_missed,
                          last_updated, error_type, misconception
                   FROM concept_mastery
                   WHERE topic_id = ? AND status = 'known'""",
                (topic_id,),
            ).fetchall()
            for row in rows:
                has_err = (row["times_missed"] or 0) > 0
                base = 3.0 if has_err else 7.0
                confirmed = row["times_confirmed"] or 1
                interval = base * (1 + 0.3 * confirmed) ** 1.5
                last_up = self._parse_ts(row["last_updated"])
                if not last_up:
                    continue
                days_since = (now - last_up).total_seconds() / 86400.0
                if days_since >= interval:
                    due.append({
                        "concept": row["concept_text"],
                        "days_overdue": round(days_since - interval, 1),
                        "error_history": has_err,
                    })
        return due

    def _blocking_gaps_for_context(self, topic_contexts: list[dict]) -> list[dict]:
        """Return prerequisite blockers for encountered query topics."""
        gaps: list[dict] = []
        for tc in topic_contexts:
            if tc.get("status") != "never_encountered":
                gaps.extend(self.get_blocking_gaps(tc.get("topic", "")))
        return gaps

    def _topic_fingerprint(self, topics: list[str]) -> str:
        """Generate a stable, normalized bag-of-words fingerprint from a list of topics.

        Used for overlap-based retrieval in get_last_session_narrative — replaces
        fragile LIKE '%first_word%' matching with a word-intersection score.

        Expands known abbreviations (via ABBREVIATION_MAP), splits on non-alpha chars,
        filters stop words, and returns a pipe-delimited sorted set of content words.

        Example: ["ICP management in TBI"] → "brain|injury|management|pressure|traumatic"
        """
        words: set[str] = set()
        for topic in topics:
            # Expand abbreviations using the module-level map
            expanded = topic.lower()
            for abbr, full in ABBREVIATION_MAP.items():
                expanded = re.sub(rf'\b{re.escape(abbr)}\b', full, expanded)
            for word in re.split(r'[\s()\[\]/\-,;:]+', expanded):
                word = word.strip(".,;:!?\"'")
                if len(word) > 3 and word not in self._FP_STOPWORDS:
                    words.add(word)
        return "|".join(sorted(words))

    def backfill_topic_fingerprints(self) -> dict:
        """Backfill topic_fingerprint for existing session_narratives rows.

        Safe to run multiple times — only updates rows where topic_fingerprint is empty.
        Returns {"updated": N}.
        """
        try:
            rows = self.conn.execute(
                "SELECT narrative_id, topics_json FROM session_narratives "
                "WHERE topic_fingerprint = '' OR topic_fingerprint IS NULL"
            ).fetchall()
            updated = 0
            for row in rows:
                topics: list[str] = []
                try:
                    raw = json.loads(row["topics_json"]) if row["topics_json"] else []
                    topics = raw if isinstance(raw, list) else [str(raw)]
                except Exception:
                    pass
                fp = self._topic_fingerprint(topics)
                with self.conn:
                    self.conn.execute(
                        "UPDATE session_narratives SET topic_fingerprint = ? WHERE narrative_id = ?",
                        (fp, row["narrative_id"]),
                    )
                updated += 1
            return {"updated": updated}
        except Exception as exc:
            print(f"[knowledge_graph] backfill_topic_fingerprints error: {exc}", file=sys.stderr)
            return {"updated": 0, "error": str(exc)}

    def learner_context(self, query: str) -> dict:
        """Pre-flight check: build a learner context block for the given query.

        Extracts topics from the query, retrieves the learner's full history
        with each, identifies cross-capability patterns, and returns a
        structured JSON block the agent uses to adapt its response.

        Returns a dict with:
          - topics: per-topic learner state (confidence, depth, encounters, errors, signals)
          - adaptive_guidance: plain-English directives for the agent
          - cross_capability_patterns: detected patterns across modalities
          - suggested_depth: recommended target depth for this interaction
        """
        try:
            raw_topics = self._query_topics_with_fuzzy_fallback(query)
            learner_profile = self._learner_profile_config()
            now = datetime.now(timezone.utc)
            thirty_days_ago = (now - timedelta(days=30)).isoformat()

            topic_contexts = []
            guidance_lines = []
            patterns = []
            max_suggested_depth = 1
            seen_topic_ids = set()  # prevent duplicate entries

            for raw in raw_topics:
                if not raw:
                    continue
                canonical = self._normalize_topic(raw)
                topic = self._find_topic(canonical)
                if topic and topic["topic_id"] in seen_topic_ids:
                    continue
                if topic:
                    seen_topic_ids.add(topic["topic_id"])

                if topic is None:
                    # Never encountered
                    topic_contexts.append({
                        "topic": raw,
                        "status": "never_encountered",
                        "confidence": 0.0,
                        "depth": 0,
                        "depth_label": "never-seen",
                        "encounters": 0,
                        "last_seen": None,
                        "recent_signals": [],
                        "error_count_30d": 0,
                        "curriculum_priority": self._get_curriculum_priority(canonical),
                    })
                    guidance_lines.append(
                        f"'{raw}' is new to the memory graph, not necessarily new to Gabriel — "
                        f"use a compact anchor, then test mechanism, clinical discrimination, "
                        f"and management transfer."
                    )
                    continue

                tid = topic["topic_id"]

                recent_signals, _prior_summaries = self._recent_signals_with_summaries(
                    tid,
                    thirty_days_ago,
                )

                # Error count (last 30 days)
                err_count = self.conn.execute(
                    """SELECT COUNT(*) FROM signal_events
                       WHERE topic_id = ?
                         AND signal_type IN ('incorrect_recall', 'weakness_identified')
                         AND timestamp > ?""",
                    (tid, thirty_days_ago),
                ).fetchone()[0]

                # Capability coverage: which sources have touched this topic?
                source_set = set()
                all_signals = self.conn.execute(
                    "SELECT DISTINCT source FROM signal_events WHERE topic_id = ?",
                    (tid,),
                ).fetchall()
                for s in all_signals:
                    source_set.add(s["source"])

                # Days since last seen
                last_seen_dt = self._parse_ts(topic.get("last_seen"))
                days_ago = (now - last_seen_dt).days if last_seen_dt else None

                depth = topic["depth"]
                confidence = topic["confidence"]
                encounters = topic["encounter_count"]

                _n_signals = len(recent_signals)
                _n_correct = sum(1 for s in recent_signals if s["signal_type"] == "correct_recall")
                tc = {
                    "topic": raw,
                    "status": "known",
                    "confidence": round(confidence, 3),
                    "depth": depth,
                    "depth_label": self._DEPTH_LABELS.get(depth, f"depth-{depth}"),
                    "encounters": encounters,
                    "last_seen": topic.get("last_seen", "")[:10],
                    "days_since_last_seen": days_ago,
                    "signal_summary": {
                        "encounters_30d": _n_signals,
                        "errors_30d": err_count,
                        "correct_rate_30d": round(_n_correct / _n_signals, 2) if _n_signals else None,
                    },
                    "sources_used": sorted(source_set),
                }
                # Only include canonical when it differs meaningfully from the display name
                if topic["canonical_name"] and topic["canonical_name"] != raw.lower().strip():
                    tc["canonical"] = topic["canonical_name"]
                # Add learning history from study_session events
                if _prior_summaries:
                    tc["prior_concepts_taught"] = _prior_summaries[:6]

                known_concepts, unknown_concepts = self._concept_mastery_lists(tid)
                if known_concepts or unknown_concepts:
                    tc["concepts_known"] = known_concepts
                    tc["concepts_unknown"] = unknown_concepts
                    gap_guidance = self._concept_gap_guidance(raw, known_concepts, unknown_concepts)
                    if gap_guidance:
                        guidance_lines.append(gap_guidance)

                # ── Recent episodic exchanges for this topic (RRF three-stream recall) ──
                try:
                    rrf = self.recall_episodes_compact(
                        query=raw,
                        topic_name=canonical,
                        days_back=30,
                        max_results=5,
                        use_semantic=False,
                    )
                    rrf_exchanges = rrf.get("exchanges", [])
                    if rrf_exchanges:
                        tc["past_exchanges_compact"] = rrf_exchanges
                        incorrect = [x for x in rrf_exchanges if x.get("correct") == 0]
                        if incorrect:
                            ex = incorrect[0]
                            guidance_lines.append(
                                f"Last time on '{raw}': "
                                f"{ex.get('one_liner', ex.get('concept', '?'))}. "
                                f"Re-test this specific concept."
                            )
                except Exception:
                    pass  # non-fatal — falls back gracefully if LanceDB unavailable

                topic_contexts.append(tc)

                depth_guidance, target_depth = self._depth_adaptive_guidance(raw, depth, confidence)
                guidance_lines.extend(depth_guidance)
                max_suggested_depth = max(max_suggested_depth, target_depth)

                # Learning history guidance
                if _prior_summaries and encounters >= 2:
                    guidance_lines.append(
                        f"Prior sessions on '{raw}' taught: "
                        + "; ".join(str(s)[:80] for s in _prior_summaries[:3])
                        + " — build on this, don't repeat the same ground."
                    )

                # Error pattern detection
                if err_count >= 2:
                    # Find the specific error signals
                    err_signals = [s for s in recent_signals
                                   if s["signal_type"] in ("incorrect_recall", "weakness_identified")]
                    err_sources = [s["source"] for s in err_signals]
                    guidance_lines.append(
                        f"⚠️ '{raw}' has {err_count} errors in the last 30 days "
                        f"(sources: {', '.join(set(err_sources))}). "
                        f"Proactively address the gap pattern — don't just re-teach, "
                        f"isolate what keeps being missed."
                    )

                # Decay detection
                if days_ago and days_ago > 21 and confidence < 0.2:
                    guidance_lines.append(
                        f"'{raw}' hasn't been seen in {days_ago} days and confidence "
                        f"has decayed to {confidence:.2f} — include a brief recall anchor "
                        f"before advancing."
                    )

                patterns.extend(
                    self._topic_capability_patterns(
                        raw,
                        tid,
                        source_set,
                        encounters,
                        err_count,
                    )
                )

            # Domain coverage check (if topics map to a single domain)
            domain_pattern = self._domain_coverage_pattern(topic_contexts)
            if domain_pattern:
                patterns.append(domain_pattern)

            # ── Meta-cognitive learning patterns ──
            learning_style = self._learning_style_summary()

            # ── Spaced verification: concepts due for review ──
            # Exclude topics currently being queried (they'll get fresh signal)
            query_topic_canonicals = [
                tc.get("canonical", tc.get("topic", ""))
                for tc in topic_contexts if tc.get("status") != "never_encountered"
            ]
            review_queue = self.get_review_queue(
                n=5,
                exclude_topics=query_topic_canonicals,
            )
            # Also check if any concepts from the CURRENT query's topics are due
            same_topic_due = self._same_topic_review_due(topic_contexts, now)

            if same_topic_due:
                guidance_lines.append(
                    f"VERIFICATION OPPORTUNITY: {len(same_topic_due)} previously 'known' concept(s) "
                    f"on the current topic are overdue for review: "
                    + ", ".join(c["concept"] for c in same_topic_due[:5])
                    + ". Weave a quick verification question into the Gym section."
                )

            # ── Last session narrative for topic(s) — inject teaching strategy ──
            last_narrative = None
            if raw_topics:
                last_narrative = self.get_last_session_narrative(topic=raw_topics[0])
            if last_narrative and last_narrative.get("next_session_strategy"):
                guidance_lines.insert(0,
                    f"PRIOR SESSION STRATEGY (from {last_narrative.get('session_ts', '')[:10]}): "
                    + last_narrative["next_session_strategy"]
                )

            # ── Blocking gaps — prerequisite chains ──
            all_blocking_gaps = self._blocking_gaps_for_context(topic_contexts)
            if all_blocking_gaps:
                blockers = [b for b in all_blocking_gaps if b.get("prerequisite_also_unknown")]
                if blockers:
                    guidance_lines.append(
                        f"PREREQUISITE GAPS: {len(blockers)} gap(s) have unmet prerequisites — "
                        + "; ".join(
                            f"'{b['gap_concept']}' requires '{b['blocking_concept']}'"
                            for b in blockers[:3]
                        )
                        + ". Address prerequisites before the higher-level concept."
                    )

            # Deduplicate past_exchanges_compact across topic objects.
            # The same exchange_id can appear in multiple related topics; keep each once
            # in the first topic that surfaces it and drop it from subsequent ones.
            _seen_xids: set = set()
            for _tc in topic_contexts:
                if "past_exchanges_compact" in _tc:
                    _unique = [
                        ex for ex in _tc["past_exchanges_compact"]
                        if ex.get("exchange_id") not in _seen_xids
                    ]
                    _seen_xids.update(ex["exchange_id"] for ex in _unique if ex.get("exchange_id"))
                    if _unique:
                        _tc["past_exchanges_compact"] = _unique
                    else:
                        del _tc["past_exchanges_compact"]

            # Distill guidance_lines down to the 5 highest-signal items.
            # Everything else is already present as structured data in the result —
            # the agent derives its own session plan from that structure.
            _HIGH_PRI = (
                "PRIOR SESSION STRATEGY",
                "STAGNATION ALERT",
                "PREREQUISITE GAPS",
                "CALIBRATION ALERT",
                "CALIBRATION WARNING",
            )
            _high = [g for g in guidance_lines if any(g.startswith(p) for p in _HIGH_PRI)]
            _cog = [g for g in guidance_lines if g.startswith("COGNITIVE PATTERN ALERT")]
            if _cog:
                _high.append(_cog[0])  # first cognitive pattern only
            key_guidance = _high[:5]

            # Compile the context block
            result = {
                "query": query,
                "topics": topic_contexts,
                "suggested_depth": max_suggested_depth,
                "adaptive_guidance": key_guidance,
                "cross_capability_patterns": patterns,
            }
            if learner_profile:
                result["learner_profile"] = {
                    "training_stage": learner_profile.get("training_stage", ""),
                    "teaching_depth_policy": learner_profile.get("teaching_depth_policy", ""),
                    "target_depth_when_ready": learner_profile.get("target_depth_when_ready", ""),
                    "starting_probe": learner_profile.get("starting_probe", ""),
                    "default_question_style": learner_profile.get("default_question_style", ""),
                    "tone": learner_profile.get("tone", ""),
                    "learning_goal": learner_profile.get("learning_goal", ""),
                    "avoid_by_default": learner_profile.get("avoid_by_default", [])[:12],
                    "prefer_by_default": learner_profile.get("prefer_by_default", [])[:12],
                }
            if learning_style:
                result["learning_patterns"] = learning_style
            if same_topic_due:
                result["same_topic_review_due"] = same_topic_due
            if last_narrative:
                result["last_session_narrative"] = {
                    "session_ts": last_narrative.get("session_ts", "")[:10],
                    "skill": last_narrative.get("skill", ""),
                    "next_session_strategy": last_narrative.get("next_session_strategy", ""),
                    "summary": last_narrative.get("summary", ""),
                    "teaching_failures": last_narrative.get("teaching_failures", []),
                }
            if all_blocking_gaps:
                result["blocking_gaps"] = all_blocking_gaps[:10]

            # ── Remediation directives (error-type → mode routing) ──
            remediation_directives = self.generate_remediation_directives(query)
            if remediation_directives:
                # Drop redundant fields: topic_canonical duplicates topic; framing_hint
                # is a prose reconstruction of concept + mode + misconception (already present).
                result["remediation_directives"] = [
                    {
                        "concept": d["concept"],
                        "error_type": d["error_type"],
                        "misconception": d["misconception"],
                        "recommended_mode": d["recommended_mode"],
                        "times_missed": d["times_missed"],
                    }
                    for d in remediation_directives
                ]
                top = remediation_directives[0]
                guidance_lines.append(
                    f"REMEDIATION TARGET: '{top['concept']}' has a {top['error_type']} gap "
                    f"(missed {top['times_missed']}x). Recommended mode: {top['recommended_mode']}. "
                    f"{top['framing_hint']}"
                )

            # ── Transfer validation candidates ──
            transfer_candidates = self.get_transfer_candidates(n=5)
            if transfer_candidates:
                # Drop topic_canonical, times_confirmed, last_updated — internal tracking fields
                result["transfer_candidates"] = [
                    {
                        "concept": c["concept"],
                        "topic": c["topic"],
                        "domain": c.get("domain", ""),
                    }
                    for c in transfer_candidates
                ]
                guidance_lines.append(
                    f"TRANSFER OPPORTUNITY: {len(transfer_candidates)} concept(s) are confirmed "
                    f"but never tested in a different context: "
                    + ", ".join(c["concept"] for c in transfer_candidates[:3])
                    + ". Design the Gym scenario to test one in a novel clinical context."
                )

            # ── Iteration 3: ZPD difficulty recommendation ──
            zpd = self.recommend_difficulty_target(n_sessions=5)
            if zpd.get("zpd_status") and zpd["zpd_status"] != "optimal":
                result["zpd_recommendation"] = zpd
                guidance_lines.append(f"ZPD ALERT: {zpd['hint']}")
            elif zpd.get("zpd_status") == "optimal":
                result["zpd_recommendation"] = zpd

            # ── Round 3: Learning velocity stagnation alerts ──
            velocity_data = self.learning_velocity(n_sessions=10)
            stagnant_domains = [
                d for d in velocity_data.get("domains", [])
                if d.get("stagnating")
                and d.get("signal_count", 0) >= 5
                and d.get("velocity", 0.0) != 0.0  # exclude never-studied domains (delta always 0)
            ]
            if stagnant_domains:
                # Keep only the domain name — presence in this list implies stagnation
                result["stagnation_alerts"] = [d["domain"] for d in stagnant_domains]
                for sd in stagnant_domains[:2]:
                    guidance_lines.append(
                        f"STAGNATION ALERT: '{sd['domain']}' domain shows no confidence growth "
                        f"across {sd['signal_count']} study signals (velocity={sd['velocity']:+.4f}). "
                        f"Current approach is not producing retention — change teaching modality: "
                        f"switch from passive review to active recall, Socratic questioning, or "
                        f"clinical scenario to break the plateau."
                    )

            # ── Iteration 4: Unknown unknowns — adjacent blind spots ──
            unknown_unknowns = self.detect_unknown_unknowns(query, n=4)
            if unknown_unknowns:
                # Drop internal routing fields: topic_slug, adjacency_source, adjacent_to, subdomain
                result["unknown_unknowns"] = [
                    {
                        "topic": u["topic"],
                        "domain": u.get("domain", ""),
                        "acgme_milestone": u.get("acgme_milestone", ""),
                    }
                    for u in unknown_unknowns
                ]
                uu_names = [u["topic"] for u in unknown_unknowns[:3]]
                guidance_lines.append(
                    f"BLIND SPOT ALERT: {len(unknown_unknowns)} clinically adjacent topic(s) in "
                    f"the same curriculum subdomain have NEVER been studied: "
                    + ", ".join(uu_names)
                    + ". Consider surfacing one in the session's closing question."
                )

            # ── Cognitive error pattern detection (process-level) [Refinement #2] ──
            cognitive_patterns = self.detect_cognitive_patterns()
            if cognitive_patterns:
                result["cognitive_pattern_alerts"] = [
                    {**cp, "topics": cp["topics"][:3]}
                    for cp in cognitive_patterns
                ]
                for cp in cognitive_patterns:
                    topics_str = ", ".join(cp["topics"][:3])
                    guidance_lines.append(
                        f"COGNITIVE PATTERN ALERT: '{cp['error_type']}' errors detected "
                        f"{cp['occurrence_count']}x across {cp['topic_count']} topics "
                        f"({topics_str}). This is a PROCESS-LEVEL error, not a content gap. "
                        f"Intervention: {cp['intervention_hint']}"
                    )

            # ── Confidence calibration profile [Refinement #1] ──
            calibration = self.compute_calibration_profile()
            if calibration.get("total_signals", 0) >= 5:
                result["calibration_profile"] = calibration
                if calibration.get("domain_alerts"):
                    for da in calibration["domain_alerts"]:
                        guidance_lines.append(
                            f"CALIBRATION ALERT: {da['alert']} "
                            f"(overconfident-wrong rate: {da['overconfident_wrong_rate']:.0%} "
                            f"across {da['sample_size']} signals)"
                        )
                if calibration.get("calibration_score") is not None and calibration["calibration_score"] < 0.5:
                    guidance_lines.append(
                        f"CALIBRATION WARNING: Overall calibration score is "
                        f"{calibration['calibration_score']:.2f}/1.00 — the learner's "
                        f"confidence frequently does not match their accuracy. Use prediction-error "
                        f"confrontation: let wrong answers play out before correcting."
                    )

            # ── Confusable pair alerts [Refinement #3] ──
            confusable = self.get_confusable_pairs(query)
            if confusable:
                result["confusable_pairs"] = confusable
                direct = [p for p in confusable if p.get("relevance") == "direct"]
                if direct:
                    p = direct[0]
                    guidance_lines.append(
                        f"DISCRIMINATION ALERT: This topic has a known confusable pair — "
                        f"'{p['concept_a']}' vs '{p['concept_b']}'. "
                        f"Disambiguation: {p.get('disambiguation_axis', 'not specified')}. "
                        f"Proactively teach the discrimination to prevent cross-contamination."
                    )

            return result

        except Exception as exc:
            print(f"[knowledge_graph] learner_context error: {exc}", file=sys.stderr)
            return {"query": query, "topics": [], "adaptive_guidance": [], "cross_capability_patterns": [], "error": str(exc)}

    # ------------------------------------------------------------------
    # Closed-Loop Adaptive Routing — Remediation Directives
    # ------------------------------------------------------------------

    _REMEDIATION_MAP = {
        "numerical_recall": {
            "recommended_mode": "drill",
            "framing_template": "Fill-in-the-blank on exact values: {concept}.",
        },
        "conceptual_confusion": {
            "recommended_mode": "socratic",
            "framing_template": "Force reasoning through the mechanism step-by-step: {concept}. The gap is in the causal chain.",
        },
        "cross_contamination": {
            "recommended_mode": "disambiguation",
            "framing_template": "Side-by-side comparison needed: {concept} vs {misconception}. Previously cross-contaminated.",
        },
        "application_failure": {
            "recommended_mode": "scenario",
            "framing_template": "Clinical scenario requiring application of: {concept}. Knows the fact, can't apply it.",
        },
        "reasoning_gap": {
            "recommended_mode": "scaffold",
            "framing_template": "Step-by-step causal chain walkthrough for: {concept}. A link in the reasoning is missing.",
        },
        "omission": {
            "recommended_mode": "teach",
            "framing_template": "Never encountered: {concept}. Start from foundations.",
        },
    }

    def generate_remediation_directives(self, query: str) -> list[dict]:
        """Generate error-type-matched remediation directives for concepts
        related to the given query that are currently in 'unknown' status
        with a known error_type.

        Returns a list of dicts sorted by times_missed descending (cap 10):
            {concept, topic, topic_canonical, error_type, misconception,
             recommended_mode, framing_hint, times_missed}
        """
        try:
            raw_topics = self._query_topics_with_fuzzy_fallback(query)

            directives: list[dict] = []
            seen_concepts: set[str] = set()

            for raw in raw_topics:
                if not raw:
                    continue
                canonical = self._normalize_topic(raw)
                topic = self._find_topic(canonical)
                if not topic:
                    continue

                rows = self.conn.execute(
                    """SELECT concept_text, error_type, misconception, remediation, times_missed
                       FROM concept_mastery
                       WHERE topic_id = ? AND status = 'unknown'
                             AND error_type IS NOT NULL AND error_type != ''
                       ORDER BY times_missed DESC""",
                    (topic["topic_id"],),
                ).fetchall()

                for row in rows:
                    concept = row["concept_text"]
                    if concept in seen_concepts:
                        continue
                    seen_concepts.add(concept)

                    error_type = row["error_type"]
                    mapping = self._REMEDIATION_MAP.get(error_type, self._REMEDIATION_MAP["omission"])
                    misconception = row["misconception"] or ""
                    framing = mapping["framing_template"].format(
                        concept=concept,
                        misconception=misconception or "unknown",
                    )
                    if misconception:
                        framing += f" Prior misconception: {misconception}"

                    directives.append({
                        "concept": concept,
                        "topic": raw,
                        "topic_canonical": canonical,
                        "error_type": error_type,
                        "misconception": misconception or None,
                        "recommended_mode": mapping["recommended_mode"],
                        "framing_hint": framing,
                        "times_missed": row["times_missed"] or 0,
                    })

            directives.sort(key=lambda d: d["times_missed"], reverse=True)
            return directives[:10]

        except Exception as exc:
            print(f"[knowledge_graph] generate_remediation_directives error: {exc}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # Mechanism-Level Transfer Validation
    # ------------------------------------------------------------------

    def get_transfer_candidates(self, n: int = 5) -> list[dict]:
        """Return concepts eligible for cross-context transfer validation.

        A concept is a transfer candidate when:
        - status = 'known'
        - times_confirmed >= 2
        - transfer_validated = 0

        Returns list of dicts:
            {concept, topic, topic_canonical, domain, times_confirmed, last_updated}
        """
        try:
            rows = self.conn.execute(
                """SELECT cm.concept_text, cm.times_confirmed, cm.last_updated,
                          t.canonical_name, t.category,
                          COALESCE(t.display_name, t.canonical_name) AS display_name
                   FROM concept_mastery cm
                   JOIN topics t ON cm.topic_id = t.topic_id
                   WHERE cm.status = 'known'
                     AND cm.times_confirmed >= 2
                     AND (cm.transfer_validated IS NULL OR cm.transfer_validated = 0)
                   ORDER BY cm.times_confirmed DESC, cm.last_updated ASC
                   LIMIT ?""",
                (n,),
            ).fetchall()

            candidates = []
            for row in rows:
                canonical = row["canonical_name"]
                cp = self._get_curriculum_priority(canonical)
                domain = cp.get("domain", row["category"] or "general") if cp else (row["category"] or "general")
                candidates.append({
                    "concept": row["concept_text"],
                    "topic": row["display_name"],
                    "topic_canonical": canonical,
                    "domain": domain,
                    "times_confirmed": row["times_confirmed"],
                    "last_updated": row["last_updated"][:10] if row["last_updated"] else None,
                })
            return candidates

        except Exception as exc:
            print(f"[knowledge_graph] get_transfer_candidates error: {exc}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # Refinement #2: Cognitive Error Pattern Detection
    # ------------------------------------------------------------------

    _PROCESS_INTERVENTIONS = {
        "premature_closure": (
            "After your first diagnosis, always ask: 'What is the one thing that "
            "would make this NOT my diagnosis?' Check for it before committing."
        ),
        "anchoring": (
            "Explicitly generate 3 alternative explanations before acting on your "
            "leading diagnosis. Write them down."
        ),
        "cross_contamination": (
            "When two conditions share a feature, force yourself to name the ONE "
            "feature that discriminates them before choosing."
        ),
        "application_failure": (
            "Practice the concept under time pressure with gradually increasing "
            "complexity. The knowledge exists — it needs activation under stress."
        ),
        "reasoning_gap": (
            "When explaining your reasoning, narrate every step aloud. The gap is "
            "usually a skipped link you don't realize you're skipping."
        ),
        "numerical_recall": (
            "These values need to be automatic. Create rapid-fire drill cards and "
            "test until the number comes before the thought."
        ),
        "conceptual_confusion": (
            "Draw the mechanism diagram for each confused concept side by side. "
            "The confusion usually lives at one specific branch point."
        ),
    }

    def detect_cognitive_patterns(self) -> list[dict]:
        """Detect recurring cognitive error types across different topics.

        A cognitive pattern is flagged when the same error_type appears >=3
        times across >=2 different topics.  This signals a process-level
        thinking error, not a content gap.

        Returns list of dicts sorted by frequency:
            {error_type, occurrence_count, topic_count, topics,
             is_process_level, intervention_hint}
        """
        try:
            rows = self.conn.execute(
                """SELECT cm.error_type,
                          COUNT(*) AS freq,
                          COUNT(DISTINCT cm.topic_id) AS topic_count,
                          GROUP_CONCAT(DISTINCT COALESCE(t.display_name, t.canonical_name)) AS topics
                   FROM concept_mastery cm
                   JOIN topics t ON cm.topic_id = t.topic_id
                   WHERE cm.status = 'unknown'
                     AND cm.error_type IS NOT NULL AND cm.error_type != ''
                   GROUP BY cm.error_type
                   HAVING freq >= 3 AND topic_count >= 2
                   ORDER BY freq DESC"""
            ).fetchall()

            patterns = []
            for row in rows:
                error_type = row["error_type"]
                patterns.append({
                    "error_type": error_type,
                    "occurrence_count": row["freq"],
                    "topic_count": row["topic_count"],
                    "topics": row["topics"].split(",") if row["topics"] else [],
                    "is_process_level": True,
                    "intervention_hint": self._PROCESS_INTERVENTIONS.get(
                        error_type,
                        "Review your reasoning process for this error class.",
                    ),
                })
            return patterns

        except Exception as exc:
            print(f"[knowledge_graph] detect_cognitive_patterns error: {exc}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # Refinement #1: Confidence Calibration Tracking
    # ------------------------------------------------------------------

    def compute_calibration_profile(self) -> dict:
        """Compute a calibration profile from bootcamp signal_events metadata.

        Looks for 'calibration' entries in signal_events.metadata where source
        is 'bootcamp'.  Each entry is a list of:
            {"concept": str, "response_confidence": "high"|"low", "correct": bool}

        Returns:
            {total_signals, overconfident_wrong, underconfident_right,
             well_calibrated, calibration_score, domain_alerts}
        """
        try:
            rows = self.conn.execute(
                """SELECT se.metadata, se.signal_type, t.canonical_name, t.category
                   FROM signal_events se
                   JOIN topics t ON se.topic_id = t.topic_id
                   WHERE se.metadata LIKE '%response_confidence%'
                      OR se.metadata LIKE '%calibration%'
                   ORDER BY se.timestamp DESC"""
            ).fetchall()

            total = 0
            overconfident_wrong = 0  # high confidence + incorrect
            underconfident_right = 0  # low confidence + correct
            well_calibrated = 0  # confidence matches accuracy
            domain_overconfidence: dict[str, int] = {}
            domain_total: dict[str, int] = {}

            for row in rows:
                try:
                    meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
                    cal_entries = meta.get("calibration", [])
                    domain = row["category"] or "general"
                    if meta.get("response_confidence"):
                        correct = meta.get("answer_correct")
                        if correct is None:
                            correct = row["signal_type"] == "correct_recall"
                        cal_entries.append({
                            "concept": meta.get("concept", row["canonical_name"]),
                            "response_confidence": meta.get("response_confidence"),
                            "correct": bool(correct == 2 or correct is True),
                        })

                    for entry in cal_entries:
                        conf = entry.get("response_confidence", "").lower()
                        correct = entry.get("correct", False)
                        total += 1
                        domain_total[domain] = domain_total.get(domain, 0) + 1

                        if conf == "high" and not correct:
                            overconfident_wrong += 1
                            domain_overconfidence[domain] = domain_overconfidence.get(domain, 0) + 1
                        elif conf == "low" and correct:
                            underconfident_right += 1
                        else:
                            well_calibrated += 1
                except (json.JSONDecodeError, TypeError):
                    continue

            # Calibration score: 0.0 = terrible, 1.0 = perfect
            # Penalize overconfident-wrong more heavily than underconfident-right
            if total == 0:
                cal_score = None
            else:
                penalty = (overconfident_wrong * 2.0 + underconfident_right * 0.5) / total
                cal_score = round(max(0.0, 1.0 - penalty), 3)

            # Domain-level alerts: flag domains with >40% overconfident-wrong rate
            domain_alerts = []
            for domain, oc_count in domain_overconfidence.items():
                dtotal = domain_total.get(domain, 1)
                oc_rate = oc_count / dtotal
                if oc_rate >= 0.4 and dtotal >= 3:
                    domain_alerts.append({
                        "domain": domain,
                        "overconfident_wrong_rate": round(oc_rate, 2),
                        "sample_size": dtotal,
                        "alert": (
                            f"Learner historically overconfident in {domain} — "
                            f"use prediction-error confrontation, not direct correction."
                        ),
                    })

            return {
                "total_signals": total,
                "overconfident_wrong": overconfident_wrong,
                "underconfident_right": underconfident_right,
                "well_calibrated": well_calibrated,
                "calibration_score": cal_score,
                "domain_alerts": domain_alerts,
            }

        except Exception as exc:
            print(f"[knowledge_graph] compute_calibration_profile error: {exc}", file=sys.stderr)
            return {"total_signals": 0, "calibration_score": None, "domain_alerts": []}

    # ------------------------------------------------------------------
    # Refinement #3: Proactive Discrimination (Confusable Pairs)
    # ------------------------------------------------------------------

    def get_confusable_pairs(self, topic: str = "") -> list[dict]:
        """Return confusable pairs from confusion_matrix.json.

        If *topic* is provided, return only pairs where one member matches
        the topic string (case-insensitive substring match).  If empty,
        return all pairs.

        Returns list of dicts from confusion_matrix.json with an added
        'relevance' field ('direct' if topic matched, 'all' otherwise).
        """
        matrix_path = DATA_DIR / "confusion_matrix.json"
        try:
            if not matrix_path.exists():
                return []
            pairs = json.loads(matrix_path.read_text(encoding="utf-8"))
            if not topic:
                for p in pairs:
                    p["relevance"] = "all"
                return pairs

            topic_lower = topic.strip().lower()
            # Also extract significant words for broader matching
            _stop = {"the", "a", "an", "of", "in", "for", "and", "or", "vs", "with", "to", "is"}
            topic_words = {w for w in topic_lower.split() if w not in _stop and len(w) > 2}

            matched = []
            for p in pairs:
                ca = p.get("concept_a", "").lower()
                cb = p.get("concept_b", "").lower()
                combined = ca + " " + cb

                # Direct substring match
                if topic_lower in ca or topic_lower in cb:
                    p["relevance"] = "direct"
                    matched.append(p)
                # Significant word overlap (any 2+ words match)
                elif len(topic_words) >= 2:
                    combined_words = set(combined.split())
                    overlap = topic_words & combined_words
                    if len(overlap) >= 2:
                        p["relevance"] = "keyword"
                        matched.append(p)
                # Single word match for short queries
                elif topic_words and any(w in combined for w in topic_words):
                    p["relevance"] = "partial"
                    matched.append(p)

            return matched

        except Exception as exc:
            print(f"[knowledge_graph] get_confusable_pairs error: {exc}", file=sys.stderr)
            return []

    def log_transfer_outcome(
        self,
        concept_text: str,
        topic_name: str,
        new_context: str,
        success: bool,
    ) -> None:
        """Log the result of a transfer validation attempt.

        Parameters
        ----------
        concept_text : str
            The concept that was tested in a new context.
        topic_name : str
            The original topic the concept belongs to.
        new_context : str
            Description of the new clinical context where transfer was tested.
        success : bool
            Whether the learner correctly demonstrated the concept in the new context.
        """
        try:
            canonical = self._normalize_topic(topic_name)
            topic = self._find_topic(canonical)
            if not topic:
                print(f"[knowledge_graph] log_transfer: topic '{topic_name}' not found", file=sys.stderr)
                return

            concept_row = self.conn.execute(
                "SELECT concept_id, status FROM concept_mastery WHERE topic_id = ? AND concept_text = ?",
                (topic["topic_id"], concept_text),
            ).fetchone()

            if not concept_row:
                print(f"[knowledge_graph] log_transfer: concept '{concept_text}' not found in topic '{topic_name}'", file=sys.stderr)
                return

            now = datetime.now(timezone.utc).isoformat()
            cid = concept_row["concept_id"]

            if success:
                self.conn.execute(
                    """UPDATE concept_mastery
                       SET transfer_validated = 1,
                           times_confirmed = times_confirmed + 1,
                           last_updated = ?
                       WHERE concept_id = ?""",
                    (now, cid),
                )
                self.log_signal(
                    topic_name=topic_name,
                    source="transfer_validation",
                    signal_type="correct_recall",
                    depth_at_event=3,
                    metadata={"transfer_context": new_context, "concept": concept_text},
                )
            else:
                self.conn.execute(
                    """UPDATE concept_mastery
                       SET status = 'unknown',
                           transfer_validated = 0,
                           times_missed = times_missed + 1,
                           error_type = 'application_failure',
                           last_updated = ?
                       WHERE concept_id = ?""",
                    (now, cid),
                )
                self.log_signal(
                    topic_name=topic_name,
                    source="transfer_validation",
                    signal_type="incorrect_recall",
                    depth_at_event=3,
                    metadata={"transfer_context": new_context, "concept": concept_text},
                )
            self.conn.commit()

        except Exception as exc:
            print(f"[knowledge_graph] log_transfer_outcome error: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Spaced Verification — Review Queue
    # ------------------------------------------------------------------

    def get_review_queue(
        self,
        n: int = 5,
        domain: str | None = None,
        exclude_topics: list[str] | None = None,
    ) -> list[dict]:
        """Return concepts due for spaced verification, ranked by urgency.

        The review interval uses an expanding schedule based on confirmation
        count, with shorter intervals for concepts that have error history:

            interval_days = base * (1 + 0.3 * times_confirmed) ^ 1.5

        where base = 3 days (has error history) or 7 days (clean).

        A concept is "due" when now - last_updated > interval_days.
        Results are ranked by: overdue_ratio DESC, curriculum_priority ASC,
        times_confirmed ASC (least-confirmed first for tiebreaking).

        Parameters
        ----------
        n : int
            Maximum number of concepts to return.
        domain : str | None
            If set, only return concepts from topics in this curriculum domain.
        exclude_topics : list[str] | None
            Topic canonical names to skip (e.g., the topic currently being studied).

        Returns
        -------
        list[dict]
            Each entry: {concept, topic, topic_canonical, domain, confidence,
                         times_confirmed, times_missed, days_overdue,
                         interval_days, last_updated, error_history}
        """
        try:
            now = datetime.now(timezone.utc)
            exclude_topics = exclude_topics or []
            exclude_set = {self._normalize_topic(t) for t in exclude_topics}

            # Fetch 'known' and 'due' concepts with their topic metadata
            # 'due' = was known but next_review_due has passed (set by _apply_concept_srs_decay)
            query = """
                SELECT cm.concept_text, cm.times_confirmed, cm.times_missed,
                       cm.last_updated, cm.error_type, cm.misconception, cm.status,
                       t.canonical_name, t.display_name, t.confidence, t.topic_id
                FROM concept_mastery cm
                JOIN topics t ON cm.topic_id = t.topic_id
                WHERE cm.status IN ('known', 'due')
            """
            rows = self.conn.execute(query).fetchall()

            candidates = []
            for row in rows:
                canonical = row["canonical_name"]
                if canonical in exclude_set:
                    continue

                # Calculate spaced interval
                has_error_history = (row["times_missed"] or 0) > 0
                base = 3.0 if has_error_history else 7.0
                confirmed = row["times_confirmed"] or 1
                interval_days = base * (1 + 0.3 * confirmed) ** 1.5

                # Check if due
                last_updated = self._parse_ts(row["last_updated"])
                if last_updated is None:
                    continue
                days_since = (now - last_updated).total_seconds() / 86400.0
                if days_since < interval_days:
                    continue  # Not due yet

                # Overdue ratio — how far past the interval we are
                overdue_ratio = days_since / interval_days if interval_days > 0 else 999.0

                # Curriculum priority lookup
                cp = self._get_curriculum_priority(canonical)
                cur_domain = cp.get("domain", "") if cp else ""
                cur_priority = cp.get("priority", 3) if cp else 3

                # Domain filter
                if domain and cur_domain.lower() != domain.lower():
                    continue

                candidates.append({
                    "concept": row["concept_text"],
                    "topic": row["display_name"],
                    "topic_canonical": canonical,
                    "domain": cur_domain,
                    "confidence": round(row["confidence"], 3),
                    "times_confirmed": confirmed,
                    "times_missed": row["times_missed"] or 0,
                    "days_overdue": round(days_since - interval_days, 1),
                    "interval_days": round(interval_days, 1),
                    "last_updated": row["last_updated"][:10] if row["last_updated"] else "",
                    "error_history": bool(has_error_history),
                    "error_type": row["error_type"] or None,
                    "misconception": row["misconception"] or None,
                    "_overdue_ratio": overdue_ratio,
                    "_priority": cur_priority,
                })

            # Rank: most overdue first, then highest curriculum priority (1=core), then least confirmed
            candidates.sort(key=lambda c: (-c["_overdue_ratio"], c["_priority"], c["times_confirmed"]))

            # Clean internal sort keys before returning
            result = []
            for c in candidates[:n]:
                c.pop("_overdue_ratio", None)
                c.pop("_priority", None)
                result.append(c)

            return result

        except Exception as exc:
            print(f"[knowledge_graph] get_review_queue error: {exc}", file=sys.stderr)
            return []

    def _get_curriculum_priority(self, canonical_name: str) -> dict | None:
        """Look up curriculum metadata for a topic."""
        try:
            row = self.conn.execute(
                "SELECT domain, priority, pgy_target, acgme_milestone FROM curriculum_topics WHERE topic_name = ?",
                (canonical_name,),
            ).fetchone()
            if row:
                return dict(row)

            # Fuzzy match
            row = self.conn.execute(
                "SELECT domain, priority, pgy_target, acgme_milestone FROM curriculum_topics WHERE topic_name LIKE ? LIMIT 1",
                (f"%{canonical_name}%",),
            ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Document session tracking (1:1 with Study Material vault docs)
    # ------------------------------------------------------------------

    def get_doc_status(self, doc_path: str) -> dict:
        """Return study state for a Study Material document.

        Returns a dict with keys: doc_path, status ('new'|'returning'),
        session_count, coverage_pct, total_concepts, first_studied,
        last_studied, concepts_covered, concepts_understood, concepts_missed,
        session_notes.
        """
        try:
            row = self.conn.execute(
                "SELECT * FROM document_sessions WHERE doc_path = ?", (doc_path,)
            ).fetchone()
            if not row:
                return {
                    "doc_path": doc_path,
                    "status": "new",
                    "session_count": 0,
                    "coverage_pct": 0.0,
                    "total_concepts": 0,
                    "first_studied": None,
                    "last_studied": None,
                    "concepts_covered": [],
                    "concepts_understood": [],
                    "concepts_missed": [],
                    "session_notes": "",
                    "source_kind": "",
                    "preferred_study_mode": "",
                    "last_study_mode": "",
                    "pacing_goal": "",
                    "mode_confidence": 0.0,
                    "mode_reason": "",
                    "mode_updated_ts": None,
                }
            d = dict(row)
            d["concepts_covered"] = json.loads(d.get("concepts_covered") or "[]")
            d["concepts_understood"] = json.loads(d.get("concepts_understood") or "[]")
            d["concepts_missed"] = json.loads(d.get("concepts_missed") or "[]")
            d["status"] = "returning"
            return d
        except Exception as exc:
            print(f"[knowledge_graph] get_doc_status error: {exc}", file=sys.stderr)
            return {"doc_path": doc_path, "status": "error", "error": str(exc)}

    def _infer_document_study_profile(
        self,
        doc_path: str,
        doc_type: str = "study-material",
        content_sample: str = "",
    ) -> dict:
        """Infer default study posture from document identity and sample text."""
        path = (doc_path or "").strip()
        haystack = f"{path}\n{doc_type}\n{content_sample}".lower()
        source_kind = "unknown"
        study_mode = "ask"
        pacing_goal = "user_selected"
        confidence = 0.35
        reasons: list[str] = []

        review_markers = [
            "study material/",
            "review",
            "slides",
            "lab",
            "exam",
            "quiz",
            "question bank",
            "## questions",
            "total questions",
            "<summary>answer</summary>",
            "[recall]",
            "[spatial]",
            "[discrimination]",
        ]
        report_markers = [
            "reports/",
            "generated report",
            "generation mode",
            "tl;dr",
            "synthesis",
            "confidence assessment",
            "clinical utility",
        ]
        oral_markers = [
            "oral boards",
            "case seed",
            "case log",
            "board-mode",
            "examiner",
        ]

        review_score = sum(1 for marker in review_markers if marker in haystack)
        report_score = sum(1 for marker in report_markers if marker in haystack)
        oral_score = sum(1 for marker in oral_markers if marker in haystack)
        q_count = len(re.findall(r"(?:^|\n)\s*(?:\*\*)?\[?q\d+\]?|(?:^|\n)\s*(?:\*\*)?q\d+[\):.]", content_sample.lower()))
        if q_count >= 5:
            review_score += 3
            reasons.append(f"detected {q_count} question markers")

        if oral_score >= max(review_score, report_score, 1):
            source_kind = "oral_board_case_seed"
            study_mode = "oral_boards"
            pacing_goal = "exam_simulation"
            confidence = 0.75
            reasons.append("oral-board/case markers found")
        elif report_score > review_score and report_score >= 2:
            source_kind = "generated_report"
            study_mode = "deep_understanding"
            pacing_goal = "mastery"
            confidence = 0.7
            reasons.append("report/synthesis markers found")
        elif review_score >= 2:
            source_kind = "review_material"
            study_mode = "rapid_review"
            pacing_goal = "throughput"
            confidence = 0.7 if q_count < 5 else 0.85
            reasons.append("review/question-deck markers found")
        elif "study material/" in haystack:
            source_kind = "study_material"
            study_mode = "ask"
            pacing_goal = "user_selected"
            confidence = 0.45
            reasons.append("study-material file without clear pacing markers")

        return {
            "doc_path": path,
            "doc_type": doc_type or "study-material",
            "source_kind": source_kind,
            "preferred_study_mode": study_mode,
            "pacing_goal": pacing_goal,
            "mode_confidence": confidence,
            "mode_reason": "; ".join(reasons) if reasons else "insufficient document evidence; ask the user",
            "should_ask": study_mode == "ask" or confidence < 0.75,
        }

    def document_profile(
        self,
        doc_path: str,
        doc_type: str = "study-material",
        content_sample: str = "",
        source_kind: str = "",
        preferred_study_mode: str = "",
        pacing_goal: str = "",
        mode_reason: str = "",
        mode_confidence: float | None = None,
        apply: bool = False,
    ) -> dict:
        """Get or update a document's preferred study mode and pacing purpose."""
        now = datetime.now(timezone.utc).isoformat()
        doc_path = (doc_path or "").strip()
        if not doc_path:
            return {"ok": False, "error": "doc_path is required"}

        inferred = self._infer_document_study_profile(
            doc_path=doc_path,
            doc_type=doc_type,
            content_sample=content_sample,
        )
        row = self.conn.execute(
            "SELECT * FROM document_sessions WHERE doc_path = ?", (doc_path,)
        ).fetchone()
        existing = dict(row) if row else {}

        explicit_mode = (preferred_study_mode or "").strip()
        explicit_kind = (source_kind or "").strip()
        final = {
            **inferred,
            "status": "returning" if existing else "new",
            "session_count": int(existing.get("session_count") or 0) if existing else 0,
            "coverage_pct": float(existing.get("coverage_pct") or 0.0) if existing else 0.0,
            "last_studied": existing.get("last_studied") if existing else None,
        }
        if existing:
            for key in (
                "source_kind",
                "preferred_study_mode",
                "last_study_mode",
                "pacing_goal",
                "mode_confidence",
                "mode_reason",
                "mode_updated_ts",
            ):
                if existing.get(key) not in (None, ""):
                    final[key] = existing.get(key)

        if explicit_mode:
            final["preferred_study_mode"] = explicit_mode
            final["last_study_mode"] = explicit_mode
        if explicit_kind:
            final["source_kind"] = explicit_kind
        if pacing_goal:
            final["pacing_goal"] = pacing_goal
        elif explicit_mode == "rapid_review":
            final["pacing_goal"] = "throughput"
        elif explicit_mode == "deep_understanding":
            final["pacing_goal"] = "mastery"
        elif explicit_mode == "oral_boards":
            final["pacing_goal"] = "exam_simulation"
        if mode_reason:
            final["mode_reason"] = mode_reason
        if mode_confidence is not None:
            final["mode_confidence"] = max(0.0, min(1.0, float(mode_confidence)))

        mode = final.get("preferred_study_mode") or "ask"
        final["should_ask"] = mode in ("", "ask") or float(final.get("mode_confidence") or 0.0) < 0.75
        if mode == "rapid_review":
            final["agent_directive"] = (
                "Run this document as rapid review: ask source questions one at a time, grade briefly, "
                "advance after correct answers, and deep-dive only for partial/wrong/overconfident/safety-critical misses."
            )
        elif mode == "deep_understanding":
            final["agent_directive"] = (
                "Run this document as deep understanding: preserve cognitive friction and progressive reveal, "
                "then build mechanism, discriminator, and transfer schema."
            )
        elif mode == "oral_boards":
            final["agent_directive"] = (
                "Use the document as case seed material for staged oral-board style questioning."
            )
        else:
            final["agent_directive"] = (
                "Ask the user to choose Rapid Review or Deep Understanding before drilling this document."
            )

        if apply:
            with self.conn:
                if existing:
                    self.conn.execute(
                        """UPDATE document_sessions
                           SET doc_type = COALESCE(NULLIF(?, ''), doc_type),
                               source_kind = ?,
                               preferred_study_mode = ?,
                               last_study_mode = COALESCE(NULLIF(?, ''), last_study_mode),
                               pacing_goal = ?,
                               mode_confidence = ?,
                               mode_reason = ?,
                               mode_updated_ts = ?
                           WHERE doc_path = ?""",
                        (
                            doc_type or final.get("doc_type", "study-material"),
                            final.get("source_kind", ""),
                            final.get("preferred_study_mode", ""),
                            explicit_mode,
                            final.get("pacing_goal", ""),
                            float(final.get("mode_confidence") or 0.0),
                            final.get("mode_reason", ""),
                            now,
                            doc_path,
                        ),
                    )
                    doc_id = int(existing["doc_id"])
                else:
                    cur = self.conn.execute(
                        """INSERT INTO document_sessions
                           (doc_path, doc_type, source_kind, preferred_study_mode,
                            last_study_mode, pacing_goal, mode_confidence,
                            mode_reason, mode_updated_ts, session_count)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                        (
                            doc_path,
                            doc_type or "study-material",
                            final.get("source_kind", ""),
                            final.get("preferred_study_mode", ""),
                            explicit_mode or "",
                            final.get("pacing_goal", ""),
                            float(final.get("mode_confidence") or 0.0),
                            final.get("mode_reason", ""),
                            now,
                        ),
                    )
                    doc_id = int(cur.lastrowid or -1)
            final["doc_id"] = doc_id
            final["mode_updated_ts"] = now
            if hasattr(self, "_upsert_memory_item_v2"):
                summary = (
                    f"Document study profile for {doc_path}: "
                    f"source_kind={final.get('source_kind') or 'unknown'}, "
                    f"preferred_study_mode={final.get('preferred_study_mode') or 'ask'}, "
                    f"pacing_goal={final.get('pacing_goal') or 'user_selected'}."
                )
                item_id = self._upsert_memory_item_v2(
                    item_type="document_profile",
                    summary=summary,
                    details=final,
                    importance=0.8,
                    confidence=float(final.get("mode_confidence") or 0.5),
                    source_table="document_sessions",
                    source_id=doc_id if doc_id > 0 else None,
                    valid_from=now,
                    dedupe_key=self._memory_hash("document_profile", doc_path),
                )
                final["memory_item_id"] = item_id

        return {"ok": True, **final}

    def log_doc_progress(
        self,
        doc_path: str,
        doc_type: str = "unknown",
        covered: list | None = None,
        understood: list | None = None,
        missed: list | None = None,
        coverage_pct: float = 0.0,
        total_concepts: int = 0,
    ) -> None:
        """Upsert document study progress, merging with existing session data.

        covered/understood: list of concept/question ID strings.
        missed: list of dicts {"concept": str, "error_type": str, ...} or plain strings.
        Concepts that appear in `understood` are automatically removed from `concepts_missed`.
        """
        covered = covered or []
        understood = understood or []
        missed = missed or []
        now = datetime.now(timezone.utc).isoformat()
        try:
            existing = self.conn.execute(
                "SELECT * FROM document_sessions WHERE doc_path = ?", (doc_path,)
            ).fetchone()

            if existing:
                ex_covered = json.loads(existing["concepts_covered"] or "[]")
                ex_understood = json.loads(existing["concepts_understood"] or "[]")
                ex_missed_list = json.loads(existing["concepts_missed"] or "[]")

                # Merge covered / understood (union, dedup)
                merged_covered = list(set(ex_covered) | set(covered))
                merged_understood = list(set(ex_understood) | set(understood))

                # Merge missed: latest entry for each concept wins
                missed_dict: dict = {}
                for m in ex_missed_list:
                    if isinstance(m, dict) and "concept" in m:
                        missed_dict[m["concept"]] = m
                    elif isinstance(m, str):
                        missed_dict[m] = {"concept": m}
                for m in missed:
                    if isinstance(m, dict) and "concept" in m:
                        missed_dict[m["concept"]] = m
                    elif isinstance(m, str):
                        missed_dict[m] = {"concept": m}
                # Promote to understood: remove from missed if now confirmed
                for u in understood:
                    missed_dict.pop(u, None)
                merged_missed = list(missed_dict.values())

                new_count = (existing["session_count"] or 0) + 1
                new_total = total_concepts if total_concepts > 0 else (existing["total_concepts"] or 0)
                with self.conn:
                    self.conn.execute(
                        """UPDATE document_sessions
                           SET session_count=?, last_studied=?, total_concepts=?,
                               concepts_covered=?, concepts_understood=?,
                               concepts_missed=?, coverage_pct=?
                           WHERE doc_path=?""",
                        (
                            new_count, now, new_total,
                            json.dumps(merged_covered), json.dumps(merged_understood),
                            json.dumps(merged_missed), coverage_pct, doc_path,
                        ),
                    )
            else:
                # Normalise missed to list-of-dicts
                missed_list = [
                    m if isinstance(m, dict) else {"concept": m}
                    for m in missed
                ]
                with self.conn:
                    self.conn.execute(
                        """INSERT INTO document_sessions
                           (doc_path, doc_type, session_count, first_studied, last_studied,
                            total_concepts, concepts_covered, concepts_understood,
                            concepts_missed, coverage_pct)
                           VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            doc_path, doc_type, now, now, total_concepts,
                            json.dumps(list(set(covered))),
                            json.dumps(list(set(understood))),
                            json.dumps(missed_list),
                            coverage_pct,
                        ),
                    )
        except Exception as exc:
            print(f"[knowledge_graph] log_doc_progress error: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Session Narrative — forward-looking teaching intelligence
    # ------------------------------------------------------------------

    def log_session_narrative(
        self,
        skill: str,
        topics: list[str],
        summary: str = "",
        teaching_successes: list[str] | None = None,
        teaching_failures: list[dict] | None = None,
        next_session_strategy: str = "",
        key_confusions: list[dict] | None = None,
        depth_profile: dict | None = None,
        duration_turns: int = 0,
        session_success_rate: float | None = None,
        current_understood: list[str] | None = None,
        current_gaps: list[str] | None = None,
    ) -> int:
        """Persist a session-level teaching narrative.

        This is the highest-value forward-looking record in the KG.
        ``next_session_strategy`` is a directive for the NEXT session, written
        by the agent at session end.  It survives context compression and
        is injected by preflight into the next session so the agent does not
        have to re-derive teaching strategy from raw gap data.

        Parameters
        ----------
        skill : str
            The skill that produced this session (study-session, intern-bootcamp, etc.)
        topics : list[str]
            Topic names covered.
        summary : str
            1-2 sentence session recap.
        teaching_successes : list[str]
            What approaches clicked (plain-English descriptions).
        teaching_failures : list[dict]
            What did not work.  Each dict: {"concept": str, "attempted": str, "why_failed": str}
        next_session_strategy : str
            Forward directive for the NEXT session on these topics.  Example:
            "Start with vasogenic vs cytotoxic edema distinction before ICP targets in brain tumors.
             Learner anchors on TBI numbers; mechanism-first teaching required."
        key_confusions : list[dict]
            Concept pairs confused this session.
            Each dict: {"concept_a": str, "concept_b": str, "disambiguation_axis": str}
        depth_profile : dict
            {topic: depth_achieved} mapping.
        duration_turns : int
            Number of interaction turns in the session.

        Returns
        -------
        int
            narrative_id of the inserted row.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()

            # Iteration 2: evaluate whether prior session's strategy worked, before inserting
            if topics and (current_understood is not None or current_gaps is not None):
                self._evaluate_prior_strategy_outcome(
                    skill=skill,
                    topics=topics,
                    current_understood=current_understood or [],
                    current_gaps=current_gaps or [],
                )

            # Round 3: compute topic fingerprint for overlap-based retrieval
            topic_fp = self._topic_fingerprint(topics or [])

            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO session_narratives
                       (session_ts, skill, topics_json, summary,
                        teaching_successes, teaching_failures, next_session_strategy,
                        key_confusions_json, depth_profile_json, duration_turns,
                        session_success_rate, topic_fingerprint)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        now, skill,
                        json.dumps(topics or []),
                        summary,
                        json.dumps(teaching_successes or []),
                        json.dumps(teaching_failures or []),
                        next_session_strategy,
                        json.dumps(key_confusions or []),
                        json.dumps(depth_profile or {}),
                        duration_turns,
                        session_success_rate,
                        topic_fp,
                    ),
                )
                narrative_id = cur.lastrowid or -1

            # Auto-persist key_confusions to concept_relationships table
            for pair in (key_confusions or []):
                ca = pair.get("concept_a", "").strip().lower()
                cb = pair.get("concept_b", "").strip().lower()
                if ca and cb:
                    self._record_concept_relationship(
                        concept_a=ca, concept_b=cb,
                        relationship="confusable_with",
                        notes=pair.get("disambiguation_axis", ""),
                        source=f"session_narrative:{skill}",
                        now=now,
                    )

            return narrative_id
        except Exception as exc:
            print(f"[knowledge_graph] log_session_narrative error: {exc}", file=sys.stderr)
            return -1

    def get_last_session_narrative(
        self,
        skill: str | None = None,
        topic: str | None = None,
    ) -> dict | None:
        """Return the most recent session narrative, optionally filtered by skill or topic.

        Uses fingerprint overlap scoring (Round 3) instead of LIKE substring matching.
        This makes retrieval robust to topic name variation, abbreviation differences,
        and paraphrasing — "ICP management in TBI" correctly matches a stored narrative
        about "ICP management in traumatic brain injury (severe)".

        Scoring: count of shared words between query fingerprint and stored fingerprint.
        Falls back to LIKE matching for old rows that have no stored fingerprint.
        Returns the most recent row with the highest overlap score (>=1), or the most
        recent row overall when topic is None.
        """
        try:
            # Fetch candidate pool (capped at 20 most recent for the skill)
            if skill:
                rows = self.conn.execute(
                    "SELECT * FROM session_narratives WHERE skill = ? ORDER BY session_ts DESC LIMIT 20",
                    (skill,),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM session_narratives ORDER BY session_ts DESC LIMIT 20"
                ).fetchall()

            if not rows:
                return None

            if not topic:
                row = rows[0]  # no topic filter — return most recent
            else:
                query_fp = self._topic_fingerprint([topic])
                query_words = set(query_fp.split("|")) if query_fp else set()

                best_row = None
                best_score = -1

                for candidate in rows:
                    stored_fp = ""
                    try:
                        stored_fp = candidate["topic_fingerprint"] or ""
                    except (IndexError, KeyError):
                        pass

                    if stored_fp:
                        stored_words = set(stored_fp.split("|"))
                        overlap = len(query_words & stored_words)
                    else:
                        # Legacy row without fingerprint — fall back to substring check
                        overlap = 1 if (topic.lower() in (candidate["topics_json"] or "").lower()) else 0

                    if overlap > best_score:
                        best_score = overlap
                        best_row = candidate

                # Require at least 1 word in common to consider it a match
                row = best_row if best_score >= 1 else None

            if not row:
                return None

            d = dict(row)
            for json_col in ("topics_json", "teaching_successes", "teaching_failures",
                             "key_confusions_json", "depth_profile_json", "linked_signal_ids"):
                if json_col in d and d[json_col]:
                    try:
                        d[json_col] = json.loads(d[json_col])
                    except (json.JSONDecodeError, TypeError):
                        pass
            return d
        except Exception as exc:
            print(f"[knowledge_graph] get_last_session_narrative error: {exc}", file=sys.stderr)
            return None


    # ------------------------------------------------------------------
    # Concept Relationships — prerequisite graph
    # ------------------------------------------------------------------

    def add_concept_relationship(
        self,
        concept_a: str,
        concept_b: str,
        relationship: str,
        topic_a: str = "",
        topic_b: str = "",
        strength: float = 0.5,
        notes: str = "",
        source: str = "manual",
    ) -> None:
        """Public API to add a concept relationship.

        relationship: 'prerequisite_of' | 'confusable_with' | 'extends' | 'differentiates_from'
        """
        now = datetime.now(timezone.utc).isoformat()
        self._record_concept_relationship(
            concept_a=concept_a.strip().lower(),
            concept_b=concept_b.strip().lower(),
            relationship=relationship,
            topic_a=topic_a,
            topic_b=topic_b,
            strength=strength,
            notes=notes,
            source=source,
            now=now,
        )

    def get_blocking_gaps(self, topic_name: str) -> list[dict]:
        """Return gaps for a topic that have prerequisite concept gaps blocking them.

        For each 'unknown' concept in the topic, checks concept_relationships for
        'prerequisite_of' entries pointing to that concept from other unknown concepts.
        This surfaces the root of a gap chain: "you can't learn X until you fix Y."

        Returns list of dicts:
            {gap_concept, topic, blocking_concept, blocking_topic, notes,
             root_cause, error_type, misconception}
        """
        try:
            canonical = self._normalize_topic(topic_name)
            topic = self._find_topic(canonical)
            if not topic:
                return []

            # Get all unknown concepts for this topic
            unknown_rows = self.conn.execute(
                """SELECT concept_text, error_type, misconception, root_cause
                   FROM concept_mastery WHERE topic_id = ? AND status IN ('unknown', 'due')""",
                (topic["topic_id"],),
            ).fetchall()

            results = []
            for row in unknown_rows:
                concept = row["concept_text"]
                # Find prerequisites for this concept
                prereqs = self.conn.execute(
                    """SELECT concept_a, topic_a, notes, strength
                       FROM concept_relationships
                       WHERE concept_b = ? AND relationship = 'prerequisite_of'""",
                    (concept,),
                ).fetchall()
                for p in prereqs:
                    # Check if the prerequisite concept is also unknown
                    prereq_concept = p["concept_a"]
                    prereq_topic = p["topic_a"]
                    is_unknown = False
                    if prereq_topic:
                        pt = self._find_topic(self._normalize_topic(prereq_topic))
                        if pt:
                            cm = self.conn.execute(
                                """SELECT status FROM concept_mastery
                                   WHERE topic_id = ? AND concept_text = ?""",
                                (pt["topic_id"], prereq_concept),
                            ).fetchone()
                            is_unknown = cm and cm["status"] in ("unknown", "due")
                    results.append({
                        "gap_concept": concept,
                        "topic": topic_name,
                        "blocking_concept": prereq_concept,
                        "blocking_topic": prereq_topic or topic_name,
                        "notes": p["notes"] or "",
                        "strength": p["strength"],
                        "prerequisite_also_unknown": is_unknown,
                        "error_type": row["error_type"] or "",
                        "misconception": row["misconception"] or "",
                        "root_cause": row["root_cause"] or "",
                    })
            results.sort(key=lambda x: (-x["strength"], x["prerequisite_also_unknown"]))
            return results
        except Exception as exc:
            print(f"[knowledge_graph] get_blocking_gaps error: {exc}", file=sys.stderr)
            return []

    def concept_chain(
        self, concept_text: str, topic_name: str | None = None, max_depth: int = 5
    ) -> dict:
        """Return the full prerequisite chain and extension chain for a concept.

        prerequisite_chain: concepts that must be known BEFORE this one
        extension_chain: concepts that BUILD ON this one (breadth this unlocks)

        Returns:
            {concept, topic, prerequisite_chain: [...], extension_chain: [...]}
        """
        try:
            concept_lower = concept_text.strip().lower()

            def _walk(start: str, direction: str, depth: int = 0) -> list[dict]:
                if depth >= max_depth:
                    return []
                if direction == "prerequisites":
                    rows = self.conn.execute(
                        """SELECT concept_a AS next_concept, topic_a AS next_topic, notes, strength
                           FROM concept_relationships
                           WHERE concept_b = ? AND relationship = 'prerequisite_of'""",
                        (start,),
                    ).fetchall()
                else:  # extensions
                    rows = self.conn.execute(
                        """SELECT concept_b AS next_concept, topic_b AS next_topic, notes, strength
                           FROM concept_relationships
                           WHERE concept_a = ? AND relationship IN ('prerequisite_of', 'extends')""",
                        (start,),
                    ).fetchall()
                chain = []
                for r in rows:
                    entry = {
                        "concept": r["next_concept"],
                        "topic": r["next_topic"] or "",
                        "notes": r["notes"] or "",
                        "strength": r["strength"],
                        "depth": depth + 1,
                    }
                    entry["chain"] = _walk(r["next_concept"], direction, depth + 1)
                    chain.append(entry)
                return chain

            return {
                "concept": concept_text,
                "topic": topic_name or "",
                "prerequisite_chain": _walk(concept_lower, "prerequisites"),
                "extension_chain": _walk(concept_lower, "extensions"),
            }
        except Exception as exc:
            print(f"[knowledge_graph] concept_chain error: {exc}", file=sys.stderr)
            return {"concept": concept_text, "topic": topic_name or "",
                    "prerequisite_chain": [], "extension_chain": []}

    # ------------------------------------------------------------------
    # Topic Specificity Validation
    # ------------------------------------------------------------------

    # Clinical qualifier patterns that indicate a fine-grained topic
    _CLINICAL_QUALIFIERS = [
        r"\bin\b", r"\bpost[\-\s]", r"\bfollowing\b", r"\bduring\b", r"\bafter\b",
        r"\bfor\b", r"\bdue to\b", r"\bsecondary to\b", r"\bassociated with\b",
        r"\bwith\b", r"\bversus\b", r"\bvs\.?\b", r"\brelated to\b",
        r"\bcaused by\b", r"\bfrom\b", r"\bcomplicating\b",
    ]

    def validate_topic_specificity(self, topic_name: str) -> dict:
        """Check whether a topic name is sufficiently specific.

        Returns dict with:
            name: str, specificity_level: int, has_qualifier: bool,
            recommendation: str
        """
        lower = topic_name.strip().lower()
        has_qualifier = any(
            re.search(pat, lower) for pat in self._CLINICAL_QUALIFIERS
        )
        word_count = len(lower.split())
        if has_qualifier and word_count >= 4:
            level = 3
            rec = ""
        elif has_qualifier or word_count >= 4:
            level = 2
            rec = (
                f"Consider adding a clinical context qualifier. "
                f"Instead of '{topic_name}', prefer e.g. "
                f"'{topic_name} in [specific condition]'."
            )
        else:
            level = 1
            rec = (
                f"Topic '{topic_name}' is too coarse. It will store correctly but "
                f"future sessions cannot distinguish clinical sub-contexts. "
                f"Prefer: '{topic_name} in [specific clinical setting/population]'."
            )
        return {
            "name": topic_name,
            "specificity_level": level,
            "has_qualifier": has_qualifier,
            "word_count": word_count,
            "recommendation": rec,
        }

    # ------------------------------------------------------------------
    # Fine-Grained Gaps — concept-level with root_cause + error_process
    # ------------------------------------------------------------------

    def fine_grained_gaps(self, top: int = 10, domain: str | None = None) -> list[dict]:
        """Return concept-level gaps with root_cause and error_process, ranked by urgency.

        Unlike ``generate_recommendations()`` which operates at topic level,
        this returns individual concept gaps — the unit of actual learning failure.
        Each entry carries the full causal chain: error_type → error_process → root_cause.

        Ranking: times_missed DESC, then next_review_due ASC (most overdue first).
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            query = """
                SELECT cm.concept_text, cm.error_type, cm.error_process, cm.root_cause,
                       cm.misconception, cm.remediation, cm.teaching_notes,
                       cm.times_missed, cm.times_confirmed,
                       cm.next_review_due, cm.last_updated, cm.status,
                       t.canonical_name, t.display_name, t.category,
                       COALESCE(ct.domain, t.category) AS domain,
                       ct.priority, ct.acgme_milestone
                FROM concept_mastery cm
                JOIN topics t ON cm.topic_id = t.topic_id
                LEFT JOIN curriculum_topics ct ON t.curriculum_id = ct.curriculum_id
                WHERE cm.status IN ('unknown', 'due')
            """
            params: list = []
            if domain:
                query += " AND (LOWER(COALESCE(ct.domain, t.category)) LIKE ?)"
                params.append(f"%{domain.lower()}%")
            query += " ORDER BY cm.times_missed DESC, cm.next_review_due ASC LIMIT ?"
            params.append(top)

            rows = self.conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                # Compute days overdue
                nrd = self._parse_ts(d.get("next_review_due"))
                now_dt = self._parse_ts(now) or datetime.now(timezone.utc)
                days_overdue = round((now_dt - nrd).total_seconds() / 86400, 1) if nrd else None
                d["days_overdue"] = days_overdue
                results.append(d)
            return results
        except Exception as exc:
            print(f"[knowledge_graph] fine_grained_gaps error: {exc}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # SRS-Based Concept Review Queue
    # ------------------------------------------------------------------

    def concept_review_queue_srs(
        self, n: int = 10, domain: str | None = None
    ) -> list[dict]:
        """Return concepts due for review using persisted SM-2 scheduling.

        Priority order:
        1. status='due' (known but past next_review_due) — quick recall check needed
        2. status='unknown' (failed), ordered by next_review_due ASC
        3. status='known' with next_review_due IS NULL (pre-migration) — use heuristic

        Returns list of dicts:
            {concept, topic, topic_canonical, domain, status, times_confirmed,
             times_missed, next_review_due, days_overdue, ease_factor,
             error_type, root_cause, error_process, misconception}
        """
        try:
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()

            query = """
                SELECT cm.concept_text, cm.status, cm.times_confirmed, cm.times_missed,
                       cm.next_review_due, cm.ease_factor, cm.review_interval_days,
                       cm.error_type, cm.root_cause, cm.error_process, cm.misconception,
                       t.canonical_name, t.display_name, t.category,
                       COALESCE(ct.domain, t.category) AS domain,
                       ct.priority
                FROM concept_mastery cm
                JOIN topics t ON cm.topic_id = t.topic_id
                LEFT JOIN curriculum_topics ct ON t.curriculum_id = ct.curriculum_id
                WHERE cm.status IN ('due', 'unknown')
                   OR (cm.status = 'known' AND cm.next_review_due IS NULL
                       AND cm.last_updated < ?)
            """
            # For the legacy heuristic: mark known concepts not seen in 7+ days
            seven_days_ago = (now - timedelta(days=7)).isoformat()
            params: list = [seven_days_ago]

            if domain:
                query = query.replace(
                    "WHERE cm.status IN ('due', 'unknown')",
                    f"WHERE (LOWER(COALESCE(ct.domain, t.category)) LIKE '%{domain.lower()}%') AND cm.status IN ('due', 'unknown')",
                )

            rows = self.conn.execute(query, params).fetchall()

            candidates = []
            for row in rows:
                nrd = self._parse_ts(row["next_review_due"])
                if nrd:
                    days_overdue = round((now - nrd).total_seconds() / 86400, 1)
                    days_overdue = max(0.0, days_overdue)
                else:
                    days_overdue = 0.0

                # Status priority: due=0, unknown=1, known_legacy=2
                status = row["status"]
                sort_priority = 0 if status == "due" else (1 if status == "unknown" else 2)

                entry = {
                    "concept": row["concept_text"],
                    "topic": row["display_name"],
                    "domain": row["domain"] or row["category"] or "",
                    "times_confirmed": row["times_confirmed"] or 0,
                    "times_missed": row["times_missed"] or 0,
                    "days_overdue": days_overdue,
                    "_sort": (sort_priority, -days_overdue),
                }
                # Only include error context when it actually exists
                if row["error_type"]:
                    entry["error_type"] = row["error_type"]
                if row["misconception"]:
                    entry["misconception"] = row["misconception"]
                candidates.append(entry)

            candidates.sort(key=lambda c: c["_sort"])
            for c in candidates:
                c.pop("_sort", None)
            return candidates[:n]

        except Exception as exc:
            print(f"[knowledge_graph] concept_review_queue_srs error: {exc}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # Migrate confusion_matrix.json → concept_relationships table
    # ------------------------------------------------------------------

    def migrate_confusion_matrix(self) -> dict:
        """One-time migration: import confusion_matrix.json into concept_relationships.

        Idempotent — skips pairs already present (either direction).
        Returns {"migrated": N, "skipped": M}.
        """
        matrix_path = DATA_DIR / "confusion_matrix.json"
        if not matrix_path.exists():
            return {"migrated": 0, "skipped": 0, "error": "confusion_matrix.json not found"}
        try:
            pairs = json.loads(matrix_path.read_text(encoding="utf-8"))
            migrated = 0
            skipped = 0
            for p in pairs:
                ca = p.get("concept_a", "").strip().lower()
                cb = p.get("concept_b", "").strip().lower()
                if not ca or not cb:
                    skipped += 1
                    continue
                existing = self.conn.execute(
                    """SELECT rel_id FROM concept_relationships
                       WHERE ((concept_a = ? AND concept_b = ?) OR (concept_a = ? AND concept_b = ?))
                         AND relationship = 'confusable_with'""",
                    (ca, cb, cb, ca),
                ).fetchone()
                if existing:
                    skipped += 1
                    continue
                now = p.get("first_added") or datetime.now(timezone.utc).isoformat()
                with self.conn:
                    self.conn.execute(
                        """INSERT INTO concept_relationships
                           (concept_a, concept_b, relationship, notes, source, strength, created_ts)
                           VALUES (?, ?, 'confusable_with', ?, ?, 0.5, ?)""",
                        (ca, cb,
                         p.get("disambiguation_axis", ""),
                         p.get("source", "manual"),
                         now),
                    )
                migrated += 1
            return {"migrated": migrated, "skipped": skipped}
        except Exception as exc:
            print(f"[knowledge_graph] migrate_confusion_matrix error: {exc}", file=sys.stderr)
            return {"migrated": 0, "skipped": 0, "error": str(exc)}

    # ------------------------------------------------------------------
    # Iteration 1: Teaching Notes Auto-Population
    # ------------------------------------------------------------------

    def _auto_populate_teaching_notes(
        self,
        concept_id: int,
        root_cause: str,
        error_process: str,
        remediation: str,
        session_date: str,
    ) -> None:
        """Auto-populate teaching_notes when a concept first transitions unknown → known.

        Called once per concept, at the moment of the transition. Records the
        causal chain that was addressed so the agent can re-use the same approach
        in future sessions without re-deriving it from raw gap data.
        """
        if not any([root_cause, error_process, remediation]):
            return
        parts: list[str] = [f"[{session_date}] First mastered:"]
        if error_process:
            parts.append(f"error process was '{error_process}'")
        if root_cause:
            parts.append(f"root cause: {root_cause[:120]}")
        if remediation:
            parts.append(f"what worked: {remediation[:120]}")
        note = " — ".join(parts)
        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE concept_mastery SET teaching_notes = TRIM(teaching_notes || char(10) || ?) WHERE concept_id = ?",
                    (note, concept_id),
                )
        except Exception as exc:
            print(f"[knowledge_graph] _auto_populate_teaching_notes error: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Iteration 2: Prerequisite Seeding + Strategy Feedback Loop
    # ------------------------------------------------------------------

    def _evaluate_prior_strategy_outcome(
        self,
        skill: str,
        topics: list[str],
        current_understood: list[str],
        current_gaps: list[str],
    ) -> str | None:
        """Evaluate whether the prior session's strategy improved outcomes.

        Called just before inserting a new session narrative. Looks up the most
        recent narrative for overlapping topics and records whether the prior
        next_session_strategy produced measurable improvement.

        Outcome classification:
            improved   — more concepts understood than missed this session
            partial    — roughly even understood vs. gaps
            unchanged  — more gaps than understood (or no understood data)
            no_prior   — no prior narrative found with a strategy

        Returns the outcome string, or None if not enough data.
        """
        if not topics:
            return None
        prior = self.get_last_session_narrative(skill=skill, topic=topics[0])
        if not prior or not prior.get("next_session_strategy") or not prior.get("narrative_id"):
            return None

        # Round 3: concept-anchored delta — measure improvement on the specific concepts
        # the prior strategy was trying to address, not aggregate session quality.
        prior_failures = prior.get("teaching_failures") or []
        if isinstance(prior_failures, str):
            try:
                prior_failures = json.loads(prior_failures)
            except Exception:
                prior_failures = []

        prior_failed_concepts = [
            (f.get("concept") or "").lower().strip()
            for f in prior_failures
            if isinstance(f, dict) and f.get("concept")
        ]

        if prior_failed_concepts:
            # Primary path: check how many of the prior-failed concepts are now understood
            understood_lower = [(c or "").lower().strip() for c in (current_understood or [])]
            recovered = sum(
                1 for fc in prior_failed_concepts
                if fc and any(fc in u or u in fc for u in understood_lower if u)
            )
            recovery_rate = recovered / len(prior_failed_concepts)
            outcome = "improved" if recovery_rate >= 0.5 else (
                "partial" if recovery_rate >= 0.25 else "unchanged"
            )
        else:
            # Fallback: no specific failure concepts logged in prior narrative;
            # use aggregate ratio as a coarser signal
            n_understood = len(current_understood or [])
            n_gaps = len(current_gaps or [])
            total = n_understood + n_gaps
            if total == 0:
                return None
            ratio = n_understood / total
            outcome = "improved" if ratio >= 0.7 else ("partial" if ratio >= 0.45 else "unchanged")

        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE session_narratives SET strategy_outcome = ? WHERE narrative_id = ?",
                    (outcome, prior["narrative_id"]),
                )
        except Exception as exc:
            print(f"[knowledge_graph] _evaluate_prior_strategy_outcome error: {exc}", file=sys.stderr)

        return outcome

    def seed_prerequisites_from_cooccurrence(self, min_cooccurrence: int = 2) -> dict:
        """Auto-seed concept_relationships from co-occurring gaps.

        Two mechanisms:
        1. error_process='prerequisite_absent': the 'misconception' field names the
           missing prerequisite concept. Automatically add a prerequisite_of edge.
        2. Same-topic concept pairs both in 'unknown' status: likely confusable within
           their clinical context. Add confusable_with edge if not already present.

        Returns {"prerequisite_edges": N, "confusable_edges": M, "skipped": K}
        """
        now = datetime.now(timezone.utc).isoformat()
        prereq_added = 0
        confusable_added = 0
        skipped = 0

        try:
            # Mechanism 1: error_process='prerequisite_absent' → named prerequisite
            prereq_rows = self.conn.execute(
                """SELECT cm.concept_text, cm.misconception, t.canonical_name AS topic
                   FROM concept_mastery cm
                   JOIN topics t ON cm.topic_id = t.topic_id
                   WHERE cm.error_process = 'prerequisite_absent'
                     AND cm.misconception IS NOT NULL AND cm.misconception != ''""",
            ).fetchall()
            for row in prereq_rows:
                prereq_concept = row["misconception"].strip().lower()
                gap_concept = row["concept_text"].strip().lower()
                topic = row["topic"]
                if prereq_concept and gap_concept and prereq_concept != gap_concept:
                    existing = self.conn.execute(
                        """SELECT rel_id FROM concept_relationships
                           WHERE concept_a = ? AND concept_b = ? AND relationship = 'prerequisite_of'""",
                        (prereq_concept, gap_concept),
                    ).fetchone()
                    if not existing:
                        self._record_concept_relationship(
                            concept_a=prereq_concept,
                            concept_b=gap_concept,
                            relationship="prerequisite_of",
                            topic_a=topic,
                            topic_b=topic,
                            notes="auto-seeded from error_process=prerequisite_absent",
                            source="auto_cooccurrence",
                            now=now,
                        )
                        prereq_added += 1
                    else:
                        skipped += 1

            # Mechanism 2: same-topic concept pairs both unknown →  confusable_with
            same_topic_pairs = self.conn.execute(
                """SELECT a.concept_text AS ca, b.concept_text AS cb,
                          t.canonical_name AS topic
                   FROM concept_mastery a
                   JOIN concept_mastery b ON a.topic_id = b.topic_id AND a.concept_id < b.concept_id
                   JOIN topics t ON a.topic_id = t.topic_id
                   WHERE a.status IN ('unknown', 'due')
                     AND b.status IN ('unknown', 'due')
                     AND a.times_missed >= ? AND b.times_missed >= ?""",
                (min_cooccurrence, min_cooccurrence),
            ).fetchall()
            for row in same_topic_pairs:
                ca = row["ca"].strip().lower()
                cb = row["cb"].strip().lower()
                topic = row["topic"]
                existing = self.conn.execute(
                    """SELECT rel_id FROM concept_relationships
                       WHERE ((concept_a = ? AND concept_b = ?) OR (concept_a = ? AND concept_b = ?))
                         AND relationship = 'confusable_with'""",
                    (ca, cb, cb, ca),
                ).fetchone()
                if not existing:
                    self._record_concept_relationship(
                        concept_a=ca,
                        concept_b=cb,
                        relationship="confusable_with",
                        topic_a=topic,
                        topic_b=topic,
                        notes=f"co-occurrence: both missed {min_cooccurrence}+ times in same topic",
                        source="auto_cooccurrence",
                        now=now,
                    )
                    confusable_added += 1
                else:
                    skipped += 1

        except Exception as exc:
            print(f"[knowledge_graph] seed_prerequisites_from_cooccurrence error: {exc}", file=sys.stderr)

        return {"prerequisite_edges": prereq_added, "confusable_edges": confusable_added, "skipped": skipped}

    # ------------------------------------------------------------------
    # Iteration 3: ZPD Adaptive Difficulty Calibration
    # ------------------------------------------------------------------

    def recommend_difficulty_target(self, n_sessions: int = 5) -> dict:
        """Compute a Zone of Proximal Development recommendation from recent sessions.

        Analyzes the last N sessions with a recorded session_success_rate.
        ZPD thresholds (Schmidt's Challenge Point Framework):
            > 0.85 — too easy; push to deeper complexity (increase depth, add cross-topic)
            0.65–0.85 — in ZPD; maintain current difficulty
            < 0.65 — too hard; scaffold back to prerequisites

        Returns:
            {mean_success_rate, session_count, zpd_status, direction,
             recommended_depth, hint, domain_breakdown}
        """
        try:
            rows = self.conn.execute(
                """SELECT session_success_rate, depth_profile_json, topics_json, skill
                   FROM session_narratives
                   WHERE session_success_rate IS NOT NULL
                   ORDER BY session_ts DESC LIMIT ?""",
                (n_sessions,),
            ).fetchall()

            if not rows:
                return {
                    "status": "insufficient_data",
                    "session_count": 0,
                    "recommended_depth": 2,
                    "direction": "maintain",
                    "hint": "Not enough session data — start with a diagnostic calibration probe before choosing depth.",
                }

            rates = [float(r["session_success_rate"]) for r in rows]
            mean_rate = sum(rates) / len(rates)

            # Trend: compare first half vs second half of window
            mid = len(rates) // 2
            if mid > 0:
                recent_mean = sum(rates[:mid]) / mid
                older_mean = sum(rates[mid:]) / (len(rates) - mid)
                trend = "improving" if recent_mean > older_mean + 0.05 else (
                    "declining" if recent_mean < older_mean - 0.05 else "stable"
                )
            else:
                trend = "stable"

            if mean_rate > 0.85:
                direction = "increase"
                zpd_status = "too_easy"
                recommended_depth = 3
                hint = (
                    f"Mean success rate {mean_rate:.0%} is above ZPD ceiling — material is too easy. "
                    f"Push to depth 3: surgical decision-making, edge cases, cross-domain transfer."
                )
            elif mean_rate < 0.65:
                direction = "decrease"
                zpd_status = "too_hard"
                recommended_depth = 1
                hint = (
                    f"Mean success rate {mean_rate:.0%} is below ZPD floor — material is too hard. "
                    f"Scaffold back: address prerequisites, build mechanism before application."
                )
            else:
                direction = "maintain"
                zpd_status = "optimal"
                recommended_depth = 2
                hint = (
                    f"Mean success rate {mean_rate:.0%} is in the optimal ZPD range (65–85%). "
                    f"Maintain current depth and complexity — learning is happening here."
                )

            return {
                "mean_success_rate": round(mean_rate, 2),
                "session_count": len(rates),
                "zpd_status": zpd_status,
                "direction": direction,
                "recommended_depth": recommended_depth,
                "trend": trend,
                "hint": hint,
            }

        except Exception as exc:
            print(f"[knowledge_graph] recommend_difficulty_target error: {exc}", file=sys.stderr)
            return {"status": "error", "error": str(exc)}

    def learning_velocity(self, domain: str | None = None, n_sessions: int = 10) -> dict:
        """Compute per-domain confidence change rate over recent study events.

        'Velocity' is the mean signed confidence delta per session for tracked topics
        in each domain. Positive = improving; negative = declining (decay outpacing study).

        Stagnation signal: |velocity| < 0.005 across 5+ sessions = study mode change needed.

        Returns:
            {domains: [{domain, velocity, signal_count, stagnating, status}],
             overall_velocity, sessions_analyzed}
        """
        try:
            now = datetime.now(timezone.utc)
            cutoff = (now - timedelta(days=n_sessions * 3)).isoformat()  # approx window

            query = """
                SELECT ct.domain,
                       AVG(se.confidence_delta) AS mean_delta,
                       COUNT(*)                  AS signal_count
                FROM signal_events se
                JOIN topics t ON se.topic_id = t.topic_id
                LEFT JOIN curriculum_topics ct ON t.curriculum_id = ct.curriculum_id
                WHERE se.timestamp > ?
                  AND se.signal_type IN ('study_session', 'correct_recall', 'incorrect_recall',
                                         'weakness_identified', 'partial_recall', 'lecture_received')
            """
            params: list = [cutoff]
            if domain:
                query += " AND LOWER(COALESCE(ct.domain, t.category)) LIKE ?"
                params.append(f"%{domain.lower()}%")
            query += " GROUP BY COALESCE(ct.domain, t.category) ORDER BY ABS(mean_delta) DESC"

            rows = self.conn.execute(query, params).fetchall()

            domain_results = []
            overall_deltas = []
            for row in rows:
                d = row["domain"] or "(uncategorised)"
                vel = round(float(row["mean_delta"] or 0), 4)
                cnt = row["signal_count"] or 0
                stagnating = abs(vel) < 0.005 and cnt >= 5
                status = "declining" if vel < -0.01 else ("improving" if vel > 0.01 else "stagnant")
                domain_results.append({
                    "domain": d,
                    "velocity": vel,
                    "signal_count": cnt,
                    "stagnating": stagnating,
                    "status": status,
                })
                overall_deltas.extend([vel] * cnt)

            overall = round(sum(overall_deltas) / len(overall_deltas), 4) if overall_deltas else 0.0

            return {
                "domains": domain_results,
                "overall_velocity": overall,
                "sessions_analyzed": n_sessions,
            }

        except Exception as exc:
            print(f"[knowledge_graph] learning_velocity error: {exc}", file=sys.stderr)
            return {"domains": [], "overall_velocity": 0.0, "sessions_analyzed": n_sessions}

    # ------------------------------------------------------------------
    # Iteration 4: Blind Spot Detection + Topic Adjacency
    # ------------------------------------------------------------------

    def auto_seed_topic_adjacency(self) -> dict:
        """Seed topic_adjacency from ACGME milestone + domain groupings.

        Topics sharing the same ACGME milestone (preferred) or same domain (fallback)
        are clinically adjacent — studying one without the other is a blind spot risk.
        Only pairs where at least one topic has encounter_count > 0 are included
        (no point surfacing adjacency for topics the learner has never touched at all).

        Returns {"seeded": N, "skipped": M}
        """
        now = datetime.now(timezone.utc).isoformat()
        seeded = 0
        skipped = 0
        try:
            # Group by ACGME milestone (preferred) — topics in same milestone are adjacent
            # Join via curriculum_id (correct linkage — canonical_name differs from topic_name)
            subdomain_rows = self.conn.execute(
                """SELECT ct1.topic_name AS ta, ct2.topic_name AS tb, ct1.domain
                   FROM curriculum_topics ct1
                   JOIN curriculum_topics ct2
                     ON COALESCE(NULLIF(ct1.subdomain,''), ct1.acgme_milestone, ct1.domain)
                        = COALESCE(NULLIF(ct2.subdomain,''), ct2.acgme_milestone, ct2.domain)
                     AND ct1.curriculum_id < ct2.curriculum_id
                   LEFT JOIN topics t1 ON t1.curriculum_id = ct1.curriculum_id
                   LEFT JOIN topics t2 ON t2.curriculum_id = ct2.curriculum_id
                   WHERE COALESCE(t1.encounter_count,0) + COALESCE(t2.encounter_count,0) > 0
                   LIMIT 2000"""
            ).fetchall()

            for row in subdomain_rows:
                ta = row["ta"].strip().lower()
                tb = row["tb"].strip().lower()
                if not ta or not tb:
                    continue
                existing = self.conn.execute(
                    "SELECT adj_id FROM topic_adjacency WHERE (topic_a = ? AND topic_b = ?) OR (topic_a = ? AND topic_b = ?)",
                    (ta, tb, tb, ta),
                ).fetchone()
                if existing:
                    skipped += 1
                    continue
                with self.conn:
                    self.conn.execute(
                        """INSERT INTO topic_adjacency (topic_a, topic_b, domain, adjacency_strength, source, created_ts)
                           VALUES (?, ?, ?, 0.7, 'curriculum_milestone', ?)""",
                        (ta, tb, row["domain"] or "", now),
                    )
                seeded += 1

        except Exception as exc:
            print(f"[knowledge_graph] auto_seed_topic_adjacency error: {exc}", file=sys.stderr)

        return {"seeded": seeded, "skipped": skipped}

    def detect_unknown_unknowns(self, query: str, n: int = 5) -> list[dict]:
        """Surface curriculum topics adjacent to the query that have never been touched.

        These are the blind spots the learner doesn't know they have: topics in the same
        ACGME milestone/subdomain that co-occur clinically but haven't been studied yet.

        For each matched topic, checks if any adjacent topic in topic_adjacency or in the
        same curriculum subdomain has encounter_count = 0.

        Returns list of dicts:
            {topic, domain, subdomain, priority, acgme_milestone, adjacency_source, adjacent_to}
        """
        try:
            raw_topics = self._query_topics_with_fuzzy_fallback(query)

            # Find matching curriculum topics for the query using fuzzy text match on topic_name
            matched_curriculum = []
            for raw in raw_topics:
                canonical = self._normalize_topic(raw)
                # Match against display_name (which stores the natural language version)
                rows = self.conn.execute(
                    """SELECT ct.topic_name, ct.subdomain, ct.domain, ct.acgme_milestone,
                              ct.curriculum_id
                       FROM curriculum_topics ct
                       WHERE LOWER(ct.display_name) LIKE ?
                          OR LOWER(ct.topic_name) LIKE ?
                       LIMIT 3""",
                    (f"%{canonical}%", f"%{canonical.replace(' ', '_')}%"),
                ).fetchall()
                matched_curriculum.extend(rows)
                # Also try matching via the topics table (via curriculum_id)
                t_row = self._find_topic(canonical)
                if t_row and t_row.get("curriculum_id"):
                    ct_row2 = self.conn.execute(
                        "SELECT * FROM curriculum_topics WHERE curriculum_id = ?",
                        (t_row["curriculum_id"],),
                    ).fetchone()
                    if ct_row2:
                        matched_curriculum.append(ct_row2)

            # Deduplicate by curriculum_id
            seen_cids: set[int] = set()
            deduped_curriculum = []
            for r in matched_curriculum:
                cid = r["curriculum_id"] if isinstance(r, dict) else r["curriculum_id"]
                if cid not in seen_cids:
                    seen_cids.add(cid)
                    deduped_curriculum.append(r)
            matched_curriculum = deduped_curriculum

            if not matched_curriculum:
                return []

            # For each matched topic, find adjacent topics never studied
            results: list[dict] = []
            seen: set[str] = set()

            for ct_row in matched_curriculum:
                # Use milestone > domain as proximity grouping
                group_val = (ct_row["acgme_milestone"] or "").strip() or (ct_row["domain"] or "").strip()
                group_col = "acgme_milestone" if (ct_row["acgme_milestone"] or "").strip() else "domain"
                if not group_val:
                    continue

                adjacent_rows = self.conn.execute(
                    f"""SELECT ct2.topic_name, ct2.display_name, ct2.domain, ct2.subdomain,
                               ct2.priority, ct2.acgme_milestone,
                               COALESCE(t.encounter_count, 0) AS enc
                       FROM curriculum_topics ct2
                       LEFT JOIN topics t ON t.curriculum_id = ct2.curriculum_id
                       WHERE ct2.{group_col} = ? AND ct2.curriculum_id != ?
                         AND COALESCE(t.encounter_count, 0) = 0
                       ORDER BY ct2.priority ASC
                       LIMIT 10""",
                    (group_val, ct_row["curriculum_id"]),
                ).fetchall()

                for adj in adjacent_rows:
                    tn = adj["topic_name"]
                    if tn in seen:
                        continue
                    seen.add(tn)
                    display = adj["display_name"] or tn
                    results.append({
                        "topic": display,
                        "topic_slug": tn,
                        "domain": adj["domain"] or "",
                        "subdomain": adj["subdomain"] or "",
                        "priority": adj["priority"] or 2,
                        "acgme_milestone": adj["acgme_milestone"] or "",
                        "adjacency_source": group_col,
                        "adjacent_to": ct_row["topic_name"],
                    })

            # Sort by priority (1=most important first)
            results.sort(key=lambda x: x["priority"])
            return results[:n]

        except Exception as exc:
            print(f"[knowledge_graph] detect_unknown_unknowns error: {exc}", file=sys.stderr)
            return []

    # Cognitive theme keywords for misconception clustering
    _CLUSTER_KEYWORDS: dict[str, list[str]] = {
        "mechanism_gap": ["mechanism", "pathway", "physiology", "pathophysiology", "biology",
                          "receptor", "cascade", "process", "how", "why", "causes"],
        "context_misapplication": ["context", "setting", "scenario", "condition", "patient",
                                   "apply", "confusion", "confus", "distinct", "difference"],
        "threshold_anchor": ["threshold", "value", "dose", "number", "level", "range",
                             "mmhg", "mg", "kg", "ml", "percent", "%", "units", "measure"],
        "anatomical_ambiguity": ["anatomy", "structure", "location", "border", "adjacent",
                                 "relation", "landmark", "space", "vessel", "nerve", "tract"],
        "classification_mismatch": ["grade", "stage", "class", "type", "category", "system",
                                    "criterion", "criteria", "classification", "scale"],
        "temporal_confusion": ["timing", "sequence", "order", "first", "before", "after",
                               "step", "phase", "day", "hour", "week", "interval"],
    }

    def misconception_clusters(self) -> list[dict]:
        """Group root_cause descriptions by cognitive theme using keyword matching.

        Returns a clustered view of why the learner's errors occur — reveals whether
        gaps stem from a single underlying cognitive deficit (high-leverage intervention)
        or scattered content gaps (require individual remediation per concept).

        Returns list of dicts sorted by concept_count DESC:
            {cluster, label, concept_count, sample_root_causes, concepts, intervention}
        """
        try:
            rows = self.conn.execute(
                """SELECT cm.concept_text, cm.root_cause, cm.error_process,
                          t.canonical_name AS topic, t.category
                   FROM concept_mastery cm
                   JOIN topics t ON cm.topic_id = t.topic_id
                   WHERE cm.status IN ('unknown', 'due')
                     AND cm.root_cause IS NOT NULL AND cm.root_cause != ''""",
            ).fetchall()

            clusters: dict[str, list[dict]] = {k: [] for k in self._CLUSTER_KEYWORDS}
            clusters["other"] = []

            for row in rows:
                rc = (row["root_cause"] or "").lower()
                matched = False
                for cluster, keywords in self._CLUSTER_KEYWORDS.items():
                    if any(kw in rc for kw in keywords):
                        clusters[cluster].append({
                            "concept": row["concept_text"],
                            "topic": row["topic"],
                            "root_cause": row["root_cause"],
                            "error_process": row["error_process"] or "",
                        })
                        matched = True
                        break
                if not matched:
                    clusters["other"].append({
                        "concept": row["concept_text"],
                        "topic": row["topic"],
                        "root_cause": row["root_cause"],
                        "error_process": row["error_process"] or "",
                    })

            _labels = {
                "mechanism_gap": "Mechanistic understanding gaps",
                "context_misapplication": "Context/application mismatches",
                "threshold_anchor": "Numerical anchor errors",
                "anatomical_ambiguity": "Anatomical confusion",
                "classification_mismatch": "Classification system errors",
                "temporal_confusion": "Timing/sequencing errors",
                "other": "Uncategorised root causes",
            }
            _interventions = {
                "mechanism_gap": "Teach the biological pathway first; derive all management from it.",
                "context_misapplication": "Drill context-switching: same concept, different patient scenarios.",
                "threshold_anchor": "Rapid-fire value recall drill; make these automatic before reasoning.",
                "anatomical_ambiguity": "Side-by-side anatomical diagrams; enforce landmark naming.",
                "classification_mismatch": "One system at a time; explicit side-by-side comparison table.",
                "temporal_confusion": "Timeline visualization for each sequence; narrate steps aloud.",
                "other": "Individual review of each root cause — no single intervention applies.",
            }

            results = []
            for cluster, entries in clusters.items():
                if not entries:
                    continue
                sample = [e["root_cause"][:80] for e in entries[:3]]
                results.append({
                    "cluster": cluster,
                    "label": _labels.get(cluster, cluster),
                    "concept_count": len(entries),
                    "concepts": [e["concept"] for e in entries[:10]],
                    "sample_root_causes": sample,
                    "intervention": _interventions.get(cluster, ""),
                })

            results.sort(key=lambda x: x["concept_count"], reverse=True)
            return results

        except Exception as exc:
            print(f"[knowledge_graph] misconception_clusters error: {exc}", file=sys.stderr)
            return []
