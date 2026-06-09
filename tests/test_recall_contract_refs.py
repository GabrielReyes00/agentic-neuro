from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RecallContractReferenceTests(unittest.TestCase):
    def test_cross_agent_study_review_adapters_require_startup_recall(self) -> None:
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
                self.assertIn(".agents/shared/commands/study-review-turn.md", text)
                self.assertIn(".agents/shared/commands/study-review-end.md", text)
                self.assertNotIn("Read and follow `.agents/shared/commands/study-review.md`", text)
                self.assertIn("startup-recall", text)
                self.assertIn("planning_brief", text)
                self.assertNotIn("vault intelligence", text.lower())

    def test_shared_learning_startup_contract_uses_orchestrated_recall(self) -> None:
        paths = (
            ".agents/shared/commands/learning-session-contract.md",
            ".agents/shared/commands/memory-operations.md",
            ".agents/shared/commands/memory-retrieval.md",
            ".agents/shared/commands/study-review-startup.md",
        )
        stale_startup_fragments = (
            'summary --topic "<doc topic>" --limit 8 --scaffold-limit 2 --include-curated --include-model --brief-only',
            "summary --limit 12 --scaffold-limit 0 --include-curated --include-model --brief-only",
        )
        for relative_path in paths:
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn("startup-recall", text)
                for fragment in stale_startup_fragments:
                    self.assertNotIn(fragment, text)

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

        for fragment in (
            "planning_brief.anki_overlay",
            "Anki never clears SQLite misconceptions",
            "avoid fresh-card direct quizzes",
        ):
            with self.subTest(startup_fragment=fragment):
                self.assertIn(fragment, startup)

        for fragment in (
            "Use --match-claim-state-id",
            "Anki Enqueue",
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
        root = (ROOT / "AGENTS.md").read_text()
        self.assertIn("Startup is silent", study_review)
        self.assertIn("Do not narrate contract loading", study_review)
        self.assertIn("Do not load Anki card-quality", study_review)
        self.assertIn("do not run audit expansion before the first question", study_review)
        self.assertIn("Ask one question and stop", study_review)
        self.assertIn("Use `handoff.next_action` privately", study_review)
        self.assertIn("Do not quote `handoff.summary`", study_review)
        self.assertNotIn("open with a one-sentence recap", study_review)
        self.assertNotIn("brief returning-session recap", study_review)
        self.assertNotIn("recap/question pattern", study_review)
        self.assertIn("For `study-review` startup", root)
        self.assertIn("Do not announce the workflow or send progress updates during this pre-question phase unless blocked", root)
        self.assertIn("one clinical question", root)
        self.assertIn("Do not narrate `handoff.summary`", root)
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
                adapter = adapter_text.lower()
                self.assertIn("Startup is silent", adapter_text)
                self.assertIn("Do not", adapter_text)
                self.assertIn("intermediary progress updates", adapter_text)
                self.assertIn("one clinical question", adapter_text)
                self.assertIn("Do not narrate `handoff.summary`", adapter_text)
                self.assertNotIn("recap/calibration question", adapter_text)
                self.assertNotIn("vault intelligence", adapter)

        retrieval = (ROOT / ".agents/shared/commands/memory-retrieval.md").read_text()
        self.assertIn("no pre-question audit command", retrieval)
        self.assertIn("deferred_high_signal_counts", retrieval)
        self.assertIn("compacted-evidence counts retained for awareness", retrieval)
        self.assertIn("fallback.audit_profile_available", retrieval)
        self.assertIn("Use `handoff.next_action` as private question-design input", retrieval)
        self.assertIn("Treat `handoff.summary` as audit/debug context only", retrieval)
        self.assertIn("narrate `handoff.summary`", retrieval)
        self.assertNotIn("fallback.full_evidence_command", retrieval)

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
        self.assertIn("study-review-vault-repair.md", turn)
        self.assertIn("study-review-end.md", turn)
        self.assertIn("vault_retriever.py recall", vault)
        self.assertIn("end-session", end)
        self.assertIn("anki_queue.py flush", end)

    def test_root_agent_instructions_share_startup_recall_invariant(self) -> None:
        for relative_path in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn("startup-recall", text)
                self.assertIn("Raw `summary`", text)

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
            "AGENTS.md",
            ".agents/shared/commands/service-log.md",
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
                self.assertIn("brain-dump", text)
                for fragment in stale_fragments:
                    self.assertNotIn(fragment, text)

    def test_service_log_contract_routes_through_brain_dump_with_service_memory(self) -> None:
        contract = (ROOT / ".agents/shared/commands/service-log.md").read_text()
        implementation = (ROOT / "src/study_memory.py").read_text()
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
        self.assertIn(".agents/shared/commands/brain-dump.md", contract)
        self.assertIn("service", implementation)

    def test_brain_dump_contract_owns_service_memory_and_candidates(self) -> None:
        contract = (ROOT / ".agents/shared/commands/brain-dump.md").read_text()
        for fragment in (
            "brain-dump-candidate-add",
            "--brain-dump-candidate-id",
            "startup-recall --lens service",
            "Neurosurgery::Service Learning",
            "Do you want to complete a quick Socratic lesson on these items?",
        ):
            with self.subTest(contract_fragment=fragment):
                self.assertIn(fragment, contract)

    def test_root_agent_instructions_route_service_log_through_brain_dump(self) -> None:
        for relative_path in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn("service-log", text)
                self.assertIn("brain-dump", text)

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
            "quick-answer",
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
        self.assertIn("Do not query vault intelligence at startup", startup)
        # The approved startup map pass is the deterministic concept-inventory
        # projection, distinct from banned semantic vault recall. Guard both: it
        # must be present and must not reintroduce semantic recall at startup.
        self.assertIn("startup-recall", startup)
        self.assertIn("--session", startup)
        self.assertIn("knowledge_map", startup)
        self.assertNotIn("vault_retriever.py", startup)

    def test_study_review_contracts_carry_deterministic_policy_invariant(self) -> None:
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        turn = (ROOT / ".agents/shared/commands/study-review-turn.md").read_text()
        doctrine = (ROOT / ".agents/shared/commands/adaptive-teaching-doctrine.md").read_text()
        # The mode/phase is deterministic and the five named modes plus the two
        # interrupts must be addressable from the contracts.
        for fragment in ("knowledge_map", "sequential_teaching_plan",
                         "ORIENT", "DEEPEN", "CONNECT", "interrupts.remediate", "interrupts.consolidate"):
            with self.subTest(startup_fragment=fragment):
                self.assertIn(fragment, startup)
        self.assertIn("policy=", turn)
        self.assertIn("inventory-concept-id", turn)
        for fragment in ("ORIENT", "DEEPEN", "CONNECT", "REMEDIATE", "CONSOLIDATE",
                         "never pick the macro phase yourself", "interrupts"):
            with self.subTest(doctrine_fragment=fragment):
                self.assertIn(fragment, doctrine)
        # The graph-leads/model-completes principle (brief 4b) must be instructed.
        self.assertIn("skeleton, not a ceiling", doctrine.lower())
        self.assertIn("model_proposed", doctrine)
        # The interpretation contract must document the new planning_brief surfaces.
        retrieval = (ROOT / ".agents/shared/commands/memory-retrieval.md").read_text()
        for fragment in ("knowledge_map", "sequential_teaching_plan",
                         "interrupts.remediate", "interrupts.consolidate", "exposure_status"):
            with self.subTest(retrieval_policy_fragment=fragment):
                self.assertIn(fragment, retrieval)

    def test_core_workflows_reference_vault_intelligence(self) -> None:
        paths = (
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            ".agents/shared/commands/learning-session-contract.md",
            ".agents/shared/commands/memory-retrieval.md",
            ".agents/shared/commands/consult.md",
            ".agents/shared/commands/quick-answer.md",
            ".agents/shared/commands/study-material.md",
            ".agents/shared/commands/generate-report.md",
            ".agents/shared/commands/intraoperative-guide.md",
            ".agents/shared/commands/grand-rounds.md",
            ".agents/shared/commands/brain-dump.md",
            "plugins/agentic-neuro/commands/consult.md",
            "plugins/agentic-neuro/commands/intraoperative-guide.md",
            "plugins/agentic-neuro/commands/quick-answer.md",
            "plugins/agentic-neuro/commands/study-material.md",
        )
        for relative_path in paths:
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn("vault-intelligence.md", text)
        for relative_path in (
            ".agents/shared/commands/consult.md",
            ".agents/shared/commands/quick-answer.md",
            ".agents/shared/commands/study-material.md",
            ".agents/shared/commands/generate-report.md",
            ".agents/shared/commands/intraoperative-guide.md",
            ".agents/shared/commands/grand-rounds.md",
            ".agents/shared/commands/brain-dump.md",
        ):
            with self.subTest(tool_path=relative_path):
                self.assertIn("vault_retriever.py", (ROOT / relative_path).read_text())
        for relative_path in (
            ".agents/shared/commands/consult.md",
            ".agents/shared/commands/quick-answer.md",
            ".agents/shared/commands/study-material.md",
            ".agents/shared/commands/generate-report.md",
            ".agents/shared/commands/intraoperative-guide.md",
            ".agents/shared/commands/grand-rounds.md",
            ".agents/shared/commands/brain-dump.md",
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
        self.assertIn("tutor voice, teaching modes", root)
        self.assertIn("repetition avoidance", root)

    def test_session_synthesis_is_not_logged_as_claim_state(self) -> None:
        study_review_turn = (ROOT / ".agents/shared/commands/study-review-turn.md").read_text()
        study_review_end = (ROOT / ".agents/shared/commands/study-review-end.md").read_text()
        memory_ops = (ROOT / ".agents/shared/commands/memory-operations.md").read_text()
        learning_contract = (ROOT / ".agents/shared/commands/learning-session-contract.md").read_text()
        curation = (ROOT / ".agents/shared/commands/memory-curation.md").read_text()

        self.assertIn("Never log a tracked claim for a synthesis/self-assessment prompt", study_review_turn)
        self.assertIn("This is not a tracked claim", study_review_end)
        self.assertIn("Never log a tracked concept for a session-synthesis", memory_ops)
        self.assertIn("Metacognitive synthesis prompts shape the session handoff rather than tracked claim state", learning_contract)
        self.assertNotIn("session synthesis self-assessment", study_review_turn)
        self.assertIn("as rows in `data/study_memory.db`", curation)
        self.assertIn("memory is not compressed into Python source files", curation)

    def test_legacy_study_review_contract_is_absent(self) -> None:
        self.assertFalse((ROOT / ".agents/shared/commands/study-review.md").exists())

    def test_postures_are_subordinate_to_deterministic_policy(self) -> None:
        doctrine = (ROOT / ".agents/shared/commands/adaptive-teaching-doctrine.md").read_text()
        root = (ROOT / "AGENTS.md").read_text()
        self.assertIn("Postures are subordinate to the deterministic policy", doctrine)
        self.assertIn("the user picks the posture, the policy picks the phase", doctrine)
        self.assertIn("posture subordinate to the deterministic teaching policy", root)

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
        # Startup and turn defer to the doctrine's precedence section.
        self.assertIn("Signal Precedence", startup)
        self.assertIn("Signal Precedence", turn)
        self.assertIn("the plan and interrupts win", startup)

    def test_empty_plan_rule_is_deterministic(self) -> None:
        doctrine = (ROOT / ".agents/shared/commands/adaptive-teaching-doctrine.md").read_text()
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        retrieval = (ROOT / ".agents/shared/commands/memory-retrieval.md").read_text()
        for text, label in ((doctrine, "doctrine"), (startup, "startup"), (retrieval, "retrieval")):
            with self.subTest(contract=label):
                self.assertIn("empty_no_inventory_scope", text)
        self.assertIn("ORIENT by definition", doctrine)
        self.assertIn("ORIENT by definition", startup)

    def test_doc_profile_field_names_match_emitter(self) -> None:
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        retrieval = (ROOT / ".agents/shared/commands/memory-retrieval.md").read_text()
        implementation = (ROOT / "src/study_memory.py").read_text()
        # Doc-mode startup must name the compact brief's real field.
        self.assertIn("teaching_priorities", startup)
        self.assertIn("there is no separate `open_first` list in doc mode", startup)
        for field in ("teaching_priorities", "knowledge_map_status", "knowledge_map_omitted",
                      "target_concepts_omitted", "socratic_choice_directives"):
            with self.subTest(field=field):
                self.assertIn(field, retrieval)
                self.assertIn(field, implementation)
        # memory-retrieval.md owns the planning_brief schema.
        self.assertIn("canonical owner of the `planning_brief` JSON schema", retrieval)
        self.assertNotIn("carried verbatim (no cap, no truncation)", retrieval)

    def test_turn_policy_line_is_self_sufficient(self) -> None:
        turn = (ROOT / ".agents/shared/commands/study-review-turn.md").read_text()
        for fragment in ("target_concepts", "pedagogical_directives", "socratic_choice_directives",
                         "policy_status", "keep the current phase"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, turn)
        self.assertIn("never invent a phase change yourself", turn)

    def test_end_session_recipes_agree_on_stats_json(self) -> None:
        end = (ROOT / ".agents/shared/commands/study-review-end.md").read_text()
        memory_ops = (ROOT / ".agents/shared/commands/memory-operations.md").read_text()
        self.assertIn("--stats-json", end)
        self.assertIn("--stats-json", memory_ops)

    def test_gemini_adapter_runs_full_session_end_in_order(self) -> None:
        gemini = (ROOT / ".gemini/commands/study-review.md").read_text()
        self.assertIn("end-session", gemini)
        self.assertIn("Synthesis challenge", gemini)
        self.assertIn("memory-curation.md", gemini)
        # end-session must come before the Anki queue work.
        self.assertLess(gemini.index("end-session"), gemini.index("anki_queue.py review"))
        # The TOML wrapper must not preload the orchestration index at startup.
        toml = (ROOT / ".gemini/commands/study-review.toml").read_text()
        self.assertNotIn("@{.agents/shared/commands/learning-session-contract.md}", toml)

    def test_concept_inventory_is_wired_into_startup_and_root(self) -> None:
        startup = (ROOT / ".agents/shared/commands/study-review-startup.md").read_text()
        root = (ROOT / "AGENTS.md").read_text()
        # Startup must run the deterministic inventory projection and read its surfaces.
        for fragment in ("startup-recall", "knowledge_map",
                         "sequential_teaching_plan", "skeleton, not a ceiling"):
            with self.subTest(startup_fragment=fragment):
                self.assertIn(fragment, startup)
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


if __name__ == "__main__":
    unittest.main()
