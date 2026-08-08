from pathlib import Path
import json
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class RecallContractReferenceTests(unittest.TestCase):
    def test_cross_agent_study_review_adapters_require_startup_recall(self) -> None:
        registry = json.loads(
            (ROOT / ".agents/shared/workflow-registry.json").read_text()
        )["workflows"]["study-review"]
        self.assertEqual(
            registry["contract"],
            ".agents/shared/commands/study-review-startup.md",
        )
        self.assertEqual(
            registry["modules"],
            [
                ".agents/shared/commands/study-review-turn.md",
                ".agents/shared/commands/study-review-vault-repair.md",
                ".agents/shared/commands/study-review-end.md",
            ],
        )
        paths = (
            ".agents/codex/skills/study-review/SKILL.md",
            ".claude/commands/study-review.md",
            ".gemini/commands/study-review.md",
            "plugins/agentic-neuro/commands/study-review.md",
        )
        for relative_path in paths:
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn(".agents/shared/commands/study-review-startup.md", text)
                self.assertNotIn("Read and follow `.agents/shared/commands/study-review.md`", text)
                self.assertLessEqual(len(text.split()), 120)

    def test_shared_learning_startup_uses_typed_entry_and_bounded_state(self) -> None:
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        tutor = (ROOT / ".agents/shared/commands/tutor-state.md").read_text()
        self.assertIn("start-session --stdin", startup)
        self.assertIn("tutor_state", startup)
        self.assertIn("tutor_state_v1", tutor)
        self.assertIn("node-recall", tutor)
        self.assertIn("never preload the whole map", tutor)
        self.assertNotIn("summary --topic", startup)

    def test_startup_recall_contract_does_not_use_json_flag(self) -> None:
        memory_ops = (ROOT / ".agents/shared/commands/memory-operations.md").read_text()
        self.assertIn("does not accept `--json`", memory_ops)
        self.assertNotIn("startup-recall --json", memory_ops)
        self.assertNotIn("--json --profile", memory_ops)

    def test_anki_overlay_contract_preserves_sqlite_precedence(self) -> None:
        retrieval = (ROOT / ".agents/shared/commands/memory-retrieval.md").read_text()
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        turn = (ROOT / ".agents/shared/commands/study-review-turn.md").read_text()
        anki_workflow = (ROOT / ".agents/shared/commands/anki-session-workflow.md").read_text()

        for fragment in (
            "planning_brief.anki_overlay",
            "startup_recall.anki_feedback_status",
            "atomic_focus",
            "atomic_scaffolds",
            "atomic_primes",
            "avoid_direct_quiz",
            "concept_rollup",
            "macro_counts",
            "SQLite vector cache semantic candidates",
            "Strong semantic hits",
            "Generic words",
            "SQLite precedence",
            "Anki success does not clear",
            "does not become `claim_state`",
            "ignore off-topic atomic facts",
        ):
            with self.subTest(retrieval_fragment=fragment):
                self.assertIn(fragment, retrieval)

        for fragment in (
            "Anki shapes the queue; it does not own the queue",
            "do not let Anki success clear a SQLite misconception",
        ):
            with self.subTest(retrieval_overlay_fragment=fragment):
                self.assertIn(fragment.lower(), retrieval.lower())

        # Startup consumes only the compact advisory pointer.  Detailed overlay
        # semantics remain in the memory interpretation contract.
        self.assertIn("Anki", startup)
        self.assertNotIn("planning_brief.anki_overlay", startup)

        for fragment in (
            "match_claim_state_id",
            "Card Follow-Through",
        ):
            with self.subTest(turn_fragment=fragment):
                self.assertIn(fragment, turn.replace('`',''))

        for fragment in (
            "topic/<slug>",
            "concept/<slug>",
            "claim/<claim_id>",
            "Do not manually add, rewrite, or remove these stable tags",
            "service/site tags",
        ):
            with self.subTest(anki_workflow_fragment=fragment):
                self.assertIn(fragment, anki_workflow)

        for stale_key in ("intervention_targets", "bridge_scaffolds", "light_primes", "recent_anki_reviews"):
            with self.subTest(stale_key=stale_key):
                self.assertNotIn(stale_key, retrieval)
                self.assertNotIn(stale_key, startup)
                self.assertNotIn(stale_key, turn)

    def test_study_review_startup_stays_quiet_and_fast(self) -> None:
        study_review = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        normalized_startup = _normalized(study_review)
        root = (ROOT / "AGENTS.md").read_text()
        normalized_root = _normalized(root)
        for invariant in (
            "Startup is silent",
            "ask one answerable clinical question and stop",
            "Do not narrate memory",
            "never preload the whole map",
            "profile=audit",
        ):
            self.assertIn(invariant, normalized_startup + " " + (ROOT / ".agents/shared/commands/tutor-state.md").read_text())
        self.assertNotIn("open with a one-sentence recap", study_review)
        self.assertNotIn("brief returning-session recap", study_review)
        self.assertNotIn("recap/question pattern", study_review)
        self.assertIn("For `study-review` startup", normalized_root)
        self.assertIn("do not announce the workflow or send progress updates during this pre-question phase unless blocked", normalized_root)
        self.assertIn("one clinical question", normalized_root)
        self.assertIn("Do not narrate `handoff.summary`", normalized_root)
        self.assertNotIn("vault-intelligence.md", study_review)
        self.assertNotIn("vault_retriever.py", study_review)
        self.assertNotIn("weak-spot-review", study_review)
        self.assertNotIn("--task doc-review", study_review)

        for relative_path in (
            ".agents/codex/skills/study-review/SKILL.md",
            ".claude/commands/study-review.md",
            ".gemini/commands/study-review.md",
            "plugins/agentic-neuro/commands/study-review.md",
        ):
            with self.subTest(adapter=relative_path):
                adapter_text = (ROOT / relative_path).read_text()
                self.assertIn("study-review-startup.md", adapter_text)
                self.assertLessEqual(len(adapter_text.split()), 120)
                self.assertNotIn("Startup is silent", adapter_text)
                self.assertNotIn("planning_brief", adapter_text)

        self.assertLessEqual(len(study_review.split()), 700)
        self.assertIn("start-session --stdin", study_review)

    def test_learning_contract_defers_later_phase_modules_until_needed(self) -> None:
        contract = (ROOT / ".agents/shared/commands/learning-session-contract.md").read_text()
        self.assertIn("Read only the modules that apply to the current phase", contract)
        self.assertIn("Do not preload later-phase modules before the first learner-facing question", contract)
        self.assertIn("Pre-Question Minimal Path", contract)
        self.assertIn("Ask one clinical question", contract)
        self.assertIn("Use `handoff.next_action` silently", contract)
        self.assertIn("do not quote `handoff.summary`", contract)
        self.assertIn("study-review-startup.md", contract)
        self.assertIn("study-review-turn.md", contract)
        self.assertIn("study-review-vault-repair.md", contract)
        self.assertIn("study-review-end.md", contract)

    def test_study_review_phase_files_are_lean_and_linked(self) -> None:
        phase_paths = {
            ".agents/shared/commands/study-review-startup.md": 1500,
            ".agents/shared/commands/study-review-turn.md": 1500,
            ".agents/shared/commands/study-review-vault-repair.md": 700,
            ".agents/shared/commands/study-review-end.md": 800,
        }
        for relative_path, max_words in phase_paths.items():
            text = (ROOT / relative_path).read_text()
            with self.subTest(path=relative_path):
                self.assertLessEqual(len(text.split()), max_words)
                self.assertIn("study-review", relative_path)
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        turn = (ROOT / ".agents/shared/commands/study-review-turn.md").read_text()
        vault = (ROOT / ".agents/shared/commands/study-review-vault-repair.md").read_text()
        end = (ROOT / ".agents/shared/commands/study-review-end.md").read_text()
        self.assertIn("study-review-turn.md", startup)
        self.assertIn("study-review-end.md", turn)
        self.assertIn("study-review-vault-repair.md", turn)
        self.assertIn("vault_retriever.py recall", vault)
        self.assertIn("close-session --stdin", end)
        self.assertIn("anki-session-workflow.md", end)

    def test_root_agent_instructions_share_startup_recall_invariant(self) -> None:
        for relative_path in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                normalized = _normalized(text).lower()
                self.assertIn("startup-recall", normalized)
                self.assertIn("raw `summary`", normalized)

    def test_root_clinical_answer_doctrine_separates_broad_teaching_from_urgent_consult(self) -> None:
        root = _normalized((ROOT / "AGENTS.md").read_text()).lower()
        for fragment in (
            "## clinical answer doctrine",
            "broad disease-management question",
            "chief-resident/attending-level teaching",
            "concrete patient, task, or immediate decision",
            "compact operational bottom line",
            "how each variable changes the branch",
            "missed variable → changed decision branch → clinical consequence → future recognition cue",
            "hard guideline/standard",
            "institution- or attending-dependent practice",
            "unknown unknowns",
            "do not route it to a workflow solely because it asks about management",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, root)

        self.assertFalse((ROOT / ".agents/shared/commands/clinical-answer.md").exists())
        self.assertFalse((ROOT / ".agents/codex/skills/clinical-answer").exists())

    def test_service_log_adapters_point_to_shared_contract(self) -> None:
        paths = (
            ".agents/codex/skills/service-log/SKILL.md",
            ".claude/commands/service-log.md",
            ".gemini/commands/service-log.md",
            ".gemini/commands/service-log.toml",
            "plugins/agentic-neuro/commands/service-log.md",
        )
        for relative_path in paths:
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn(".agents/shared/commands/service-log.md", text)

    def test_service_log_adapters_are_clean_current_product_language(self) -> None:
        paths = (
            ".agents/codex/skills/service-log/SKILL.md",
            ".claude/commands/service-log.md",
            ".gemini/commands/service-log.md",
            ".gemini/commands/service-log.toml",
            "plugins/agentic-neuro/commands/service-log.md",
        )
        stale_fragments = (
            "Deprecated compatibility",
            "deprecated compatibility",
            "compatibility route",
            "compatibility wrapper",
            "deprecated compatibility route",
        )
        for relative_path in paths:
            text = (ROOT / relative_path).read_text()
            with self.subTest(path=relative_path):
                self.assertIn("service", text.lower())
                self.assertIn(".agents/shared/commands/service-log.md", text)
                for fragment in stale_fragments:
                    self.assertNotIn(fragment, text)

    def test_service_log_contract_routes_through_shift_debrief_with_service_memory(self) -> None:
        contract = (ROOT / ".agents/shared/commands/service-log.md").read_text()
        implementation = (
            (ROOT / "src/study_memory.py").read_text()
            + (ROOT / "src/study_memory_cli.py").read_text()
        )
        for command in (
            "rotation-current",
            "rotation-start",
            "startup-recall",
        ):
            with self.subTest(command=command):
                self.assertIn(command, contract)
                self.assertIn(command, implementation)
        for flag in ("--lens", "--origin", "--convention"):
            with self.subTest(flag=flag):
                self.assertIn(flag, contract)
                self.assertIn(flag, implementation)
        self.assertIn("service-debrief entry point", contract)
        self.assertIn(".agents/shared/commands/shift-debrief.md", contract)
        self.assertIn("service", implementation)

    def test_shift_debrief_contract_owns_service_memory_and_candidates(self) -> None:
        contract = (ROOT / ".agents/shared/commands/shift-debrief.md").read_text()
        for fragment in (
            "shift-debrief-candidate-add",
            "--shift-debrief-candidate-id",
            "startup-recall --lens service",
            "Neurosurgery::Service Learning",
            "canned closing sentence",
        ):
            with self.subTest(contract_fragment=fragment):
                self.assertIn(fragment, contract)

    def test_root_agent_instructions_route_service_log_through_shift_debrief(self) -> None:
        for relative_path in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn("service-log", text)
                self.assertIn("shift-debrief", text)

    def test_vault_intelligence_contract_preserves_knowledge_boundary(self) -> None:
        contract = (ROOT / ".agents/shared/commands/vault-intelligence.md").read_text()
        implementation = (ROOT / "src/vault_index.py").read_text()
        for fragment in (
            "not the full neurosurgery curriculum",
            "Absence from the vault",
            "native clinical knowledge",
            "formal verification",
            "vault_notes",
            "data/vault_index.db",
            "retrieval_status",
            "partial",
            "sync-lance",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, contract)
        for task in (
            "doc-review",
            "weak-spot-review",
            "concept-repair",
            "consult",
            "service-local",
            "operative-rehearsal",
            "trial-evidence",
        ):
            with self.subTest(task=task):
                self.assertIn(task, contract)
                self.assertIn(task, implementation)

    def test_vault_intelligence_contract_uses_recall_as_agent_entrypoint(self) -> None:
        contract = (ROOT / ".agents/shared/commands/vault-intelligence.md").read_text()
        self.assertIn("normal vault entry point", contract)
        self.assertIn("vault_retriever.py recall", contract)
        self.assertIn("not a startup step", contract)
        self.assertIn("point of need", contract)
        self.assertNotIn('vault_retriever.py search "<query>"', contract)
        self.assertNotIn("vault_retriever.py search-lance", contract)

    def test_learning_contract_keeps_vault_out_of_study_review_startup(self) -> None:
        contract = (ROOT / ".agents/shared/commands/learning-session-contract.md").read_text()
        retrieval = (ROOT / ".agents/shared/commands/memory-retrieval.md").read_text()
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        self.assertIn("Optional point-of-need Obsidian section retrieval", contract)
        self.assertIn("`study-review` startup uses `.agents/shared/commands/study-review-startup.md`", contract)
        self.assertIn("after the first question", contract)
        self.assertIn("`startup-recall` itself is SQLite learner-state plus optional Anki overlay, not Obsidian vault search", retrieval)
        self.assertIn("do not query the vault at startup for the same document", retrieval)
        self.assertIn("do not preload semantic vault recall", (ROOT / ".agents/shared/commands/study-review-turn.md").read_text())
        # The approved startup map pass is the deterministic concept-inventory
        # projection, distinct from banned semantic vault recall. Guard both: it
        # must be present and must not reintroduce semantic recall at startup.
        self.assertIn("start-session", startup)
        self.assertIn("tutor_state", startup)
        self.assertIn("Artifact Map Gate", startup)
        self.assertNotIn("vault_retriever.py", startup)

    def test_study_review_contracts_carry_phase_controller_invariant(self) -> None:
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        turn = (ROOT / ".agents/shared/commands/study-review-turn.md").read_text()
        tutor = (ROOT / ".agents/shared/commands/tutor-state.md").read_text()
        doctrine = (ROOT / ".agents/shared/commands/adaptive-teaching-doctrine.md").read_text()
        for fragment in ("ORIENT", "DEEPEN", "CONNECT", "REMEDIATE", "CONSOLIDATE"):
            with self.subTest(doctrine_fragment=fragment):
                self.assertIn(fragment, doctrine)
        combined = startup + turn + tutor + doctrine
        for fragment in ("phase_controller", "active_target", "learner_evidence", "knowledge_map", "nearby_nodes"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, combined)
        self.assertIn("deterministic recommendation", turn)
        self.assertIn("phase_override", turn)
        self.assertIn("Hard constraints are binding", turn)

    def test_doc_artifact_alignment_contract_is_named_and_operational(self) -> None:
        root = (ROOT / "AGENTS.md").read_text()
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        memory_ops = (ROOT / ".agents/shared/commands/memory-operations.md").read_text()
        retrieval = (ROOT / ".agents/shared/commands/memory-retrieval.md").read_text()
        doctrine = (ROOT / ".agents/shared/commands/adaptive-teaching-doctrine.md").read_text()
        turn = (ROOT / ".agents/shared/commands/study-review-turn.md").read_text()
        adapters = "\n".join(
            (ROOT / p).read_text()
            for p in (
                ".agents/codex/skills/study-review/SKILL.md",
                ".claude/commands/study-review.md",
                ".gemini/commands/study-review.md",
                "plugins/agentic-neuro/commands/study-review.md",
            )
        )
        for fragment in (
            "artifact_alignment",
            "three-map",
            "map_context",
            "artifact_map",
            "learner_map",
            "artifact_remaining_high_yield",
            "map_context_only",
            "horizon_expansion",
            "artifact-map-upsert",
        ):
            with self.subTest(artifact_fragment=fragment):
                self.assertIn(fragment, root + startup + memory_ops + retrieval + doctrine + turn + adapters)

    def test_core_workflows_reference_vault_intelligence(self) -> None:
        paths = (
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            ".agents/shared/commands/learning-session-contract.md",
            ".agents/shared/commands/memory-retrieval.md",
            ".agents/shared/commands/consult.md",
            ".agents/shared/commands/study-material.md",
            ".agents/shared/commands/generate-report.md",
            ".agents/shared/commands/intraoperative-guide.md",
            ".agents/shared/commands/grand-rounds.md",
            ".agents/shared/commands/shift-debrief.md",
        )
        for relative_path in paths:
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn("vault-intelligence.md", text)
        for relative_path in (
            ".agents/shared/commands/consult.md",
            ".agents/shared/commands/study-material.md",
            ".agents/shared/commands/generate-report.md",
            ".agents/shared/commands/intraoperative-guide.md",
            ".agents/shared/commands/grand-rounds.md",
            ".agents/shared/commands/shift-debrief.md",
        ):
            with self.subTest(tool_path=relative_path):
                self.assertIn("vault_retriever.py", (ROOT / relative_path).read_text())
        for relative_path in (
            ".agents/shared/commands/consult.md",
            ".agents/shared/commands/study-material.md",
            ".agents/shared/commands/generate-report.md",
            ".agents/shared/commands/intraoperative-guide.md",
            ".agents/shared/commands/grand-rounds.md",
            ".agents/shared/commands/shift-debrief.md",
        ):
            with self.subTest(recall_tool_path=relative_path):
                self.assertIn("vault_retriever.py recall", (ROOT / relative_path).read_text())
        self.assertIn("vault_index.db", (ROOT / "AGENTS.md").read_text())

    def test_adaptive_teaching_doctrine_defines_database_driven_pedagogy(self) -> None:
        doctrine = (ROOT / ".agents/shared/commands/adaptive-teaching-doctrine.md").read_text()
        for fragment in (
            "high friction at the question boundary; depth and elegance after commitment",
            "clear, clinically serious, intellectually generous tutor",
            "Default Deep Tutor",
            "Repair Mode",
            "Intern Firefight",
            "Operative Rehearsal",
            "Oral Board",
            "Rapid Fire",
            "Modes are postures, not hard templates",
            "Vault Field To Teaching Move",
            "Use retrieved fields as design material, not scripts",
            "critical_discriminators",
            "durable_mental_model",
            "surgical_coordinates",
            "retest_prompt_shape",
            "operation_profile",
            "Scaffold-as-premise",
            "Bounded prerequisite checks",
            "Shadow-rule temptation",
            "Use learner memory and native clinical reasoning to choose the next move",
            "use vault intelligence only when already retrieved by the workflow or when a point-of-need repair",
            "not routine startup context",
            "Use native clinical knowledge and formal verification when the vault is silent",
            "Use high-pressure attending or oral-board tone only when the user requests it",
            "Use the retrieval packet and memory state to think like a tutor",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, doctrine)

    def test_learning_contract_keeps_adaptive_doctrine_as_teaching_home(self) -> None:
        contract = (ROOT / ".agents/shared/commands/learning-session-contract.md").read_text()
        root = (ROOT / "AGENTS.md").read_text()
        self.assertIn(".agents/shared/commands/adaptive-teaching-doctrine.md", contract)
        self.assertIn("Tutor voice, teaching modes", contract)
        self.assertIn("field-to-teaching-move mapping", contract)
        self.assertIn("tutor voice, teaching modes", _normalized(root))
        self.assertIn("repetition avoidance", root)

    def test_session_synthesis_is_not_logged_as_claim_state(self) -> None:
        study_review_turn = (ROOT / ".agents/shared/commands/study-review-turn.md").read_text()
        study_review_end = (ROOT / ".agents/shared/commands/study-review-end.md").read_text()
        memory_ops = (ROOT / ".agents/shared/commands/memory-operations.md").read_text()
        learning_contract = (ROOT / ".agents/shared/commands/learning-session-contract.md").read_text()
        curation = (ROOT / ".agents/shared/commands/memory-curation.md").read_text()

        self.assertIn("pending_adjudication", study_review_turn)
        self.assertIn("not a tracked clinical claim", study_review_end)
        self.assertIn("Never log a tracked concept for a session-synthesis", memory_ops)
        self.assertIn("Metacognitive synthesis prompts shape the session handoff rather than tracked claim state", learning_contract)
        self.assertNotIn("session synthesis self-assessment", study_review_turn)
        self.assertIn("as rows in `data/study_memory.db`", curation)
        self.assertIn("memory is not compressed into Python source files", curation)

    def test_legacy_study_review_contract_is_absent(self) -> None:
        self.assertFalse((ROOT / ".agents/shared/commands/study-review.md").exists())

    def test_postures_are_subordinate_to_phase_controller(self) -> None:
        doctrine = (ROOT / ".agents/shared/commands/adaptive-teaching-doctrine.md").read_text()
        root = (ROOT / "AGENTS.md").read_text()
        self.assertIn("Postures are subordinate to the phase controller", doctrine)
        self.assertIn("The user\npicks the posture", doctrine)
        self.assertIn(
            "posture subordinate to the deterministic teaching policy",
            _normalized(root),
        )

    def test_signal_precedence_order_is_defined_once(self) -> None:
        doctrine = (ROOT / ".agents/shared/commands/adaptive-teaching-doctrine.md").read_text()
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        turn = (ROOT / ".agents/shared/commands/study-review-turn.md").read_text()
        self.assertIn("## Signal Precedence", doctrine)
        # Remediate outranks consolidate outranks phase work outranks handoff.
        remediate_pos = doctrine.index("`interrupts.remediate`", doctrine.index("## Signal Precedence"))
        consolidate_pos = doctrine.index("`interrupts.consolidate`", remediate_pos)
        phase_pos = doctrine.index("Phase work", consolidate_pos)
        handoff_pos = doctrine.index("`handoff.next_action`", phase_pos)
        self.assertTrue(remediate_pos < consolidate_pos < phase_pos < handoff_pos)
        # Phase contracts carry only the actionable controller, not a duplicate
        # copy of the precedence doctrine.
        tutor = (ROOT / ".agents/shared/commands/tutor-state.md").read_text()
        self.assertIn("phase_controller", startup + turn + tutor)
        self.assertNotIn("## Signal Precedence", startup)
        self.assertNotIn("## Signal Precedence", turn)

    def test_empty_plan_rule_is_deterministic(self) -> None:
        doctrine = (ROOT / ".agents/shared/commands/adaptive-teaching-doctrine.md").read_text()
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        retrieval = (ROOT / ".agents/shared/commands/memory-retrieval.md").read_text()
        self.assertIn("empty_no_inventory_scope", doctrine)
        self.assertIn("map is empty", startup)
        self.assertIn("empty_no_inventory_scope", retrieval)
        self.assertIn("begin ORIENT", doctrine)
        self.assertIn("begin ORIENT", startup)

    def test_tutor_profile_field_names_match_emitter(self) -> None:
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        tutor_contract = (ROOT / ".agents/shared/commands/tutor-state.md").read_text()
        implementation = (ROOT / "src/tutor_state.py").read_text()
        for field in ("phase_controller", "active_target", "learner_evidence",
                      "knowledge_map", "context_expansion", "artifact_alignment"):
            with self.subTest(field=field):
                self.assertIn(field, tutor_contract + startup)
                self.assertIn(field, implementation)
        self.assertIn("tutor_state_v1", implementation)
        self.assertIn("ACTIVE_NODE_CAP", implementation)

    def test_turn_policy_line_is_self_sufficient(self) -> None:
        turn = (ROOT / ".agents/shared/commands/study-review-turn.md").read_text()
        for fragment in ("policy", "Hard constraints", "phase_override", "active misconception"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, turn)
        self.assertIn("deterministic recommendation", turn)

    def test_end_session_uses_typed_close_payload(self) -> None:
        end = (ROOT / ".agents/shared/commands/study-review-end.md").read_text()
        self.assertIn("close-session --stdin", end)
        self.assertIn('"stats"', end)
        self.assertIn("priority_inventory_ids", end)

    def test_shared_session_end_owns_order_and_gemini_adapter_stays_thin(self) -> None:
        gemini = (ROOT / ".gemini/commands/study-review.md").read_text()
        end = (ROOT / ".agents/shared/commands/study-review-end.md").read_text()
        self.assertIn("close-session", end)
        self.assertIn("Synthesis", end)
        self.assertIn("memory-curation.md", end)
        # The durable close must precede post-close Anki handling.
        self.assertLess(end.index("close-session"), end.index("After close"))
        self.assertIn("study-review-startup.md", gemini)
        self.assertLessEqual(len(gemini.split()), 120)
        # The TOML wrapper must not preload the orchestration index at startup.
        toml = (ROOT / ".gemini/commands/study-review.toml").read_text()
        self.assertNotIn("@{.agents/shared/commands/learning-session-contract.md}", toml)

    def test_concept_inventory_is_wired_into_startup_and_root(self) -> None:
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        root = (ROOT / "AGENTS.md").read_text()
        # Startup must run the deterministic inventory projection and read its surfaces.
        for fragment in ("start-session", "tutor_state", "active target"):
            with self.subTest(startup_fragment=fragment):
                self.assertIn(fragment.lower(), startup.lower())
        # The old vault landscape pass must be gone from startup.
        self.assertNotIn("vault_index.py landscape", startup)
        # Root must register the inventory as a separate datastore and its role.
        for fragment in ("data/concept_inventory.db", "src/concept_inventory.py",
                         "startup-recall --session", "knowledge_map"):
            with self.subTest(root_fragment=fragment):
                self.assertIn(fragment, root)

    def test_concept_inventory_cli_surface_matches_contract(self) -> None:
        impl = (ROOT / "src/concept_inventory.py").read_text()
        for command in ("build", "validate", "stats", "scope", "map-learner"):
            with self.subTest(command=command):
                self.assertIn(command, impl)
        # The mapping pass must open the learner memory DB read-only.
        self.assertIn("mode=ro", impl)

    def test_no_dead_brief_4b_references_in_contracts(self) -> None:
        for relative_path in (
            ".agents/shared/commands/memory-curation.md",
            ".agents/shared/commands/adaptive-teaching-doctrine.md",
        ):
            with self.subTest(path=relative_path):
                self.assertNotIn("brief 4b", (ROOT / relative_path).read_text())

    def test_phase3_mastery_intelligence_contracts(self) -> None:
        turn = (ROOT / ".agents/shared/commands/study-review-turn.md").read_text()
        retrieval = (ROOT / ".agents/shared/commands/memory-retrieval.md").read_text()
        doctrine = (ROOT / ".agents/shared/commands/adaptive-teaching-doctrine.md").read_text()
        impl = (ROOT / "src/study_memory.py").read_text()
        for fragment in ("reasoning_depth", "operation_demonstrated", "independence",
                         "changed-frame", "DEEPEN", "CONNECT"):
            with self.subTest(turn_fragment=fragment):
                self.assertIn(fragment, turn)
        for fragment in (
            "acgme_readiness",
            "escalation_directives",
            "orient_skip",
            "cognitive_op",
        ):
            with self.subTest(retrieval_fragment=fragment):
                self.assertIn(fragment, retrieval)
        self.assertIn("Mastery Velocity", doctrine)
        self.assertIn("probe_feedback", impl)
        self.assertIn("acgme_readiness", impl)
        self.assertIn("binding_match_count", impl)

    def test_phase2_node_recall_and_orient_menu_contracts(self) -> None:
        turn = (ROOT / ".agents/shared/commands/study-review-turn.md").read_text()
        end = (ROOT / ".agents/shared/commands/study-review-end.md").read_text()
        retrieval = (ROOT / ".agents/shared/commands/memory-retrieval.md").read_text()
        curation = (ROOT / ".agents/shared/commands/memory-curation.md").read_text()
        impl = (ROOT / "src/study_memory.py").read_text()
        tutor = (ROOT / ".agents/shared/commands/tutor-state.md").read_text()
        for fragment in ("node-recall", "active_nodes", "learner_evidence", "nearby_nodes"):
            with self.subTest(tutor_fragment=fragment):
                self.assertIn(fragment, tutor)
        for fragment in ("handoff skeleton", "priority inventory IDs", "improved IDs"):
            with self.subTest(end_fragment=fragment):
                self.assertIn(fragment.lower(), end.lower())
        self.assertIn("learner_surface", retrieval)
        self.assertIn("inventory_concept_id", curation)
        self.assertIn("node-recall", impl)
        self.assertIn("orient_menu", impl)
        self.assertIn("handoff_skeleton", impl)


if __name__ == "__main__":
    unittest.main()
