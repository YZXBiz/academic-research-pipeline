"""Tests for PipelineConfig validators (coverage gaps)."""

from __future__ import annotations

import pytest

from academic_pipeline.config import PipelineConfig


class TestConfigValidators:
    def test_empty_default_model_raises(self):
        """default_model validator rejects empty/whitespace strings."""
        with pytest.raises(ValueError, match="default_model cannot be empty"):
            PipelineConfig(default_model="   ")

    def test_postgres_without_database_url_raises(self):
        """Postgres backend without database_url raises (lines 107, 129-132)."""
        with pytest.raises(ValueError, match="database_url is required"):
            PipelineConfig(checkpointer_backend="postgres", database_url="")

    def test_postgres_with_database_url_ok(self):
        """Postgres backend with database_url succeeds."""
        cfg = PipelineConfig(
            checkpointer_backend="postgres",
            database_url="postgresql://localhost/test",
        )
        assert cfg.checkpointer_backend == "postgres"


def test_evaluator_config_defaults():
    config = PipelineConfig()
    assert config.evaluator_models == [
        "openai:deepseek-v4-pro",
    ]
    assert config.max_node_iterations == 2
    assert config.node_quality_threshold == 7.0
    assert config.enable_node_evaluation is True


def test_compliance_check_config_default():
    config = PipelineConfig(anthropic_api_key="sk-test")
    assert config.enable_compliance_check is True


def test_pipeline_config_loads_from_default_yaml(monkeypatch):
    """configs/default.yaml values are picked up when env vars don't override.

    Uses max_integrity_fix_loops because it's set in default.yaml (=3) but
    NOT overridden in dev.yaml, so the YAML source resolves to default's value.
    """
    monkeypatch.delenv("MAX_INTEGRITY_FIX_LOOPS", raising=False)
    cfg = PipelineConfig()
    assert cfg.max_integrity_fix_loops == 3


def test_pipeline_config_env_overrides_yaml(monkeypatch):
    """Env vars beat YAML defaults."""
    monkeypatch.setenv("MAX_INTEGRITY_FIX_LOOPS", "7")
    cfg = PipelineConfig()
    assert cfg.max_integrity_fix_loops == 7


# PRD §6.12.T1 — Bundle SCI flag plumbing. The 8 canonical flags + 8 legacy escape hatches.
# Defaults stay at current (mostly false) state until each subsystem's Phase 2 wiring lands.

SCI_CANONICAL_FLAGS: dict[str, object] = {
    "traceability_mode": "off",
    # PRD §6.1.T1: chain_of_ideas_enabled flipped default-on in Phase 4
    # (Chain-of-Ideas + thesis extractor become canonical research path).
    "chain_of_ideas_enabled": True,
    "novelty_gate_enabled": False,
    "pointwise_novelty_enabled": False,
    "persona_reviewers_enabled": False,
    "cascaded_review_enabled": False,
    "exploration_breadth_enabled": False,
    # PRD §6.5.T1: ethics_checklist_enabled flipped default-on in Phase 4
    # (EthicsChecklistNode in integrity replaces legacy freeform path).
    "ethics_checklist_enabled": True,
}

SCI_LEGACY_FLAGS: tuple[str, ...] = (
    "legacy_traceability",
    "legacy_chain_of_ideas",
    # PRD §6.1.T1: legacy_knowledge_graph escape hatch — when true, the legacy
    # KnowledgeGraphNode runs alongside (or instead of) the canonical
    # ChainOfIdeasNode. Phase 4 wiring lives in §6.1.T2.
    "legacy_knowledge_graph",
    "legacy_novelty_gate",
    "legacy_pointwise_novelty",
    "legacy_persona_reviewers",
    "legacy_cascaded_review",
    "legacy_exploration_breadth",
    "legacy_ethics_checklist",
)


@pytest.mark.parametrize(("flag", "expected"), list(SCI_CANONICAL_FLAGS.items()))
def test_sci_canonical_flag_default(flag: str, expected: object):
    """All 8 SCI canonical flags exist and carry the documented default."""
    cfg = PipelineConfig(anthropic_api_key="sk-test")
    assert hasattr(cfg, flag), f"PipelineConfig missing canonical SCI flag {flag!r}"
    assert (
        getattr(cfg, flag) == expected
    ), f"{flag!r} default drifted: expected {expected!r}, got {getattr(cfg, flag)!r}"


@pytest.mark.parametrize("flag", SCI_LEGACY_FLAGS)
def test_sci_legacy_escape_hatch_default(flag: str):
    """Each canonical flag has a paired legacy_* escape hatch defaulting to False."""
    cfg = PipelineConfig(anthropic_api_key="sk-test")
    assert hasattr(cfg, flag), f"PipelineConfig missing legacy escape-hatch {flag!r}"
    assert getattr(cfg, flag) is False, f"{flag!r} should default to False (operator opts in to force legacy path)"


def test_sci_flags_overridable_via_init():
    """Init kwargs flip canonical + legacy flags independently."""
    cfg = PipelineConfig(
        anthropic_api_key="sk-test",
        ethics_checklist_enabled=True,
        legacy_ethics_checklist=True,
        traceability_mode="full",
        legacy_traceability=True,
    )
    assert cfg.ethics_checklist_enabled is True
    assert cfg.legacy_ethics_checklist is True
    assert cfg.traceability_mode == "full"
    assert cfg.legacy_traceability is True


# PRD §6.12.T5 — per-node quality threshold map (paired with §6.11.T4).


def test_node_quality_thresholds_defaults_empty():
    """Field exists and defaults to an empty dict (backward compat baseline)."""
    cfg = PipelineConfig(anthropic_api_key="sk-test")
    assert hasattr(cfg, "node_quality_thresholds")
    assert cfg.node_quality_thresholds == {}


def test_get_node_threshold_falls_back_to_global():
    """Missing per-node entry → fall back to node_quality_threshold global."""
    cfg = PipelineConfig(anthropic_api_key="sk-test", node_quality_threshold=6.5)
    assert cfg.get_node_threshold("draft_writer") == 6.5
    assert cfg.get_node_threshold("anything_else") == 6.5


def test_get_node_threshold_returns_per_node_value_when_set():
    """Per-node entry overrides the global default for that node only."""
    cfg = PipelineConfig(
        anthropic_api_key="sk-test",
        node_quality_threshold=7.0,
        node_quality_thresholds={"synthesis": 7.5, "draft_writer": 6.0},
    )
    assert cfg.get_node_threshold("synthesis") == 7.5
    assert cfg.get_node_threshold("draft_writer") == 6.0
    # unset node still falls back
    assert cfg.get_node_threshold("review_synth") == 7.0


def test_node_quality_thresholds_validates_range():
    """Per-node values are clamped to [0.0, 10.0] like the global threshold."""
    with pytest.raises(ValueError, match="node_quality_thresholds"):
        PipelineConfig(
            anthropic_api_key="sk-test",
            node_quality_thresholds={"draft_writer": 11.0},
        )
    with pytest.raises(ValueError, match="node_quality_thresholds"):
        PipelineConfig(
            anthropic_api_key="sk-test",
            node_quality_thresholds={"draft_writer": -0.1},
        )


# PRD §6.12.T8 — Skill packs documented + load cleanly.


def test_skills_dirs_resolves_to_existing_directory():
    """SKILLS_DIRS resolves to a real on-disk skills/ directory."""
    from pathlib import Path

    from academic_pipeline.config import SKILLS_DIRS

    assert SKILLS_DIRS, "SKILLS_DIRS must be non-empty"
    for d in SKILLS_DIRS:
        assert Path(d).is_dir(), f"SKILLS_DIRS entry does not exist on disk: {d!r}"


def test_both_skill_packs_load_via_skills_capability():
    """The autogluon and exa-research SKILL.md packs are both discoverable."""
    from pathlib import Path

    from academic_pipeline.config import SKILLS_DIRS

    skill_md_files = []
    for d in SKILLS_DIRS:
        skill_md_files.extend(Path(d).rglob("SKILL.md"))
    pack_names = {p.parent.name for p in skill_md_files}
    assert "autogluon" in pack_names, f"autogluon pack not discovered (found: {pack_names})"
    assert "exa-research" in pack_names, f"exa-research pack not discovered (found: {pack_names})"

    # Each pack's SKILL.md must have YAML frontmatter with `name` matching the directory.
    for skill_path in skill_md_files:
        text = skill_path.read_text()
        assert text.startswith("---\n"), f"{skill_path} missing YAML frontmatter delimiter"
        # Frontmatter ends at the second '---' line.
        end = text.index("\n---", 4)
        frontmatter = text[4:end]
        assert "name:" in frontmatter, f"{skill_path} frontmatter missing 'name:' field"
        assert "description:" in frontmatter, f"{skill_path} frontmatter missing 'description:' field"
