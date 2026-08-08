from pathlib import Path

from src.operative_guide_validator import (
    _current_evidence_source_present,
    _current_evidence_required,
    _current_outcomes_source_present,
)


ROOT = Path(__file__).resolve().parents[1]
RAG_CONTRACT = ".agents/shared/commands/rag-routing.md"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_rag_contract_declares_all_production_tiers_and_serializers():
    text = _read(RAG_CONTRACT)
    lower = text.lower()

    for required in (
        ".agents/shared/commands/mini-rag.md",
        "mini-batch",
        "lance_retriever.py compare",
        "lance_retriever.py batch",
        "--card-json",
    ):
        assert required in text
    assert "current primary sources" in lower


def test_agent_profiles_share_one_rag_authority():
    for relative_path in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        assert RAG_CONTRACT in _read(relative_path)


def test_rag_workflows_reference_the_shared_router():
    workflows = (
        ".agents/shared/commands/consult.md",
        ".agents/shared/commands/shift-debrief.md",
        ".agents/shared/commands/study-material.md",
        ".agents/shared/commands/study-review-turn.md",
        ".agents/shared/commands/journal-club.md",
        ".agents/shared/commands/grand-rounds-case.md",
        ".agents/shared/commands/generate-report.md",
        ".agents/shared/commands/generate-report-research-plan.md",
        ".agents/shared/commands/generate-report-research.md",
        ".agents/shared/commands/intraoperative-guide.md",
        ".agents/shared/commands/intraoperative-guide-decomposition.md",
        ".agents/shared/commands/intraoperative-guide-research.md",
        ".agents/shared/commands/intraoperative-guide-gap-repair.md",
    )
    for relative_path in workflows:
        assert RAG_CONTRACT in _read(relative_path), relative_path


def test_all_agent_command_surfaces_stay_thin_and_reach_shared_workflows():
    surfaces = (
        (
            ".agents/codex/skills/intraoperative-guide/SKILL.md",
            ".agents/shared/commands/intraoperative-guide.md",
        ),
        (
            ".claude/commands/intraoperative-guide.md",
            ".agents/shared/commands/intraoperative-guide.md",
        ),
        (
            ".gemini/commands/intraoperative-guide.md",
            ".agents/shared/commands/intraoperative-guide.md",
        ),
        (
            "plugins/agentic-neuro/commands/intraoperative-guide.md",
            ".agents/shared/commands/intraoperative-guide.md",
        ),
        (
            ".agents/codex/skills/generate-report/SKILL.md",
            ".agents/shared/commands/generate-report.md",
        ),
        (
            ".claude/commands/generate-report.md",
            ".agents/shared/commands/generate-report.md",
        ),
        (
            ".gemini/commands/generate-report.md",
            ".agents/shared/commands/generate-report.md",
        ),
        (
            "plugins/agentic-neuro/commands/generate-report.md",
            ".agents/shared/commands/generate-report.md",
        ),
    )
    for relative_path, shared in surfaces:
        text = _read(relative_path)
        assert shared in text
        assert len(text.split()) <= 120
        workflow = Path(relative_path).stem
        if workflow == "SKILL":
            workflow = Path(relative_path).parent.name
        assert f".agents/shared/runtime/{workflow}.json" in text
        assert ".agents/shared/workflow-registry.json" not in text


def test_stale_serial_rag_rules_are_removed():
    checked = (
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        ".agents/shared/commands/intraoperative-guide.md",
        ".agents/shared/commands/intraoperative-guide-research.md",
        ".agents/shared/commands/intraoperative-guide-gap-repair.md",
    )
    stale = (
        "serial RAG",
        "one focused serial",
        "30-45 seconds is expected",
        "30–45 seconds is expected",
        "queries_without_frontier",
        "queries_with_frontier",
    )
    for relative_path in checked:
        text = _read(relative_path)
        for fragment in stale:
            assert fragment not in text, (relative_path, fragment)


def test_current_outcomes_gate_accepts_legacy_verdicts_without_overriding_new_schema():
    assert _current_evidence_source_present(
        {"current_evidence_source_present": True}
    )
    assert not _current_evidence_source_present(
        {
            "current_evidence_source_present": False,
            "current_outcomes_source_present": True,
        }
    )
    assert _current_outcomes_source_present(
        {"current_outcomes_source_present": True}
    )
    assert _current_outcomes_source_present(
        {"frontier_outcomes_query_present": True}
    )
    assert not _current_outcomes_source_present(
        {
            "current_outcomes_source_present": False,
            "frontier_outcomes_query_present": True,
        }
    )


def test_current_evidence_gate_is_decision_sensitive_with_legacy_fallback():
    assert not _current_evidence_required(
        {"complexity": "complex", "current_evidence_required": False}
    )
    assert _current_evidence_required(
        {"complexity": "simple", "current_evidence_required": True}
    )
    assert _current_evidence_required({"complexity": "complex"})
