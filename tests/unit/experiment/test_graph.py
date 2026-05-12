# tests/test_experiment_graph.py
"""Tests for experiment subgraph graph and nodes."""
from __future__ import annotations

from academic_pipeline.experiment.graph import (
    AnalysisNode,
    ExperimentDesignNode,
    InteractiveMLNode,
    JudgeNode,
    build_experiment_graph,
)


def test_build_experiment_graph():
    graph = build_experiment_graph()
    assert graph.name == "experiment"

def test_node_classes_exist():
    assert ExperimentDesignNode is not None
    assert InteractiveMLNode is not None
    assert JudgeNode is not None
    assert AnalysisNode is not None


class TestStripMarkdownFences:
    """ConfigWriterNode must strip ```yaml fences from LLM output before
    writing config.yaml. Without this, the workspace's yaml.safe_load
    raises ScannerError on the first backtick character.
    """

    def test_strips_yaml_fence(self) -> None:
        from academic_pipeline.experiment.graph import _strip_markdown_fences

        wrapped = "```yaml\nschema_version: 1\ndataset:\n  source: hf\n```"
        assert _strip_markdown_fences(wrapped) == "schema_version: 1\ndataset:\n  source: hf"

    def test_strips_yml_fence(self) -> None:
        from academic_pipeline.experiment.graph import _strip_markdown_fences

        assert _strip_markdown_fences("```yml\nfoo: 1\n```") == "foo: 1"

    def test_strips_bare_triple_backtick_fence(self) -> None:
        from academic_pipeline.experiment.graph import _strip_markdown_fences

        assert _strip_markdown_fences("```\nfoo: 1\n```") == "foo: 1"

    def test_passthrough_when_no_fence(self) -> None:
        from academic_pipeline.experiment.graph import _strip_markdown_fences

        plain = "schema_version: 1\ndataset:\n  source: hf"
        assert _strip_markdown_fences(plain) == plain

    def test_preserves_inner_backticks(self) -> None:
        """Backticks in YAML values (e.g. SQL with \\` quoting) must survive."""
        from academic_pipeline.experiment.graph import _strip_markdown_fences

        wrapped = "```yaml\nsql: |\n  SELECT `col` FROM t\n```"
        assert _strip_markdown_fences(wrapped) == "sql: |\n  SELECT `col` FROM t"

    def test_yaml_safe_load_succeeds_after_strip(self) -> None:
        """End-to-end: stripped output must parse cleanly."""
        import yaml

        from academic_pipeline.experiment.graph import _strip_markdown_fences

        wrapped = "```yaml\ndataset:\n  source: hf\n  files: [a.csv]\n```"
        parsed = yaml.safe_load(_strip_markdown_fences(wrapped))
        assert parsed == {"dataset": {"source": "hf", "files": ["a.csv"]}}
