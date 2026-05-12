"""Tests for the §6.7.T3 authors.yaml gate.

Covers:
1. ``runtime/authors_yaml.py::load_authors_yaml`` returns a list of
   ``AuthorsYamlEntry`` objects from a valid file (schema per OQ13:
   ``[{name, affiliation, email, orcid?}]``).
2. Raises ``AuthorsYamlMissing`` (REN002) when the file does not exist.
3. Raises ``AuthorsYamlMissing`` when YAML is malformed or schema-invalid.
4. ``runtime/rendering_errors.py::AuthorsYamlMissing`` carries error_code
   ``REN002`` per PRD §17.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from pathlib import Path


class TestRenderingErrorsRen002:
    def test_authors_yaml_missing_carries_ren002(self) -> None:
        from academic_pipeline.runtime.rendering_errors import AuthorsYamlMissing

        err = AuthorsYamlMissing(searched_paths=["/repo/authors.yaml"])
        assert err.error_code == "REN002"
        assert "/repo/authors.yaml" in str(err)


class TestLoadAuthorsYaml:
    """``load_authors_yaml(path)`` shapes."""

    def test_returns_entries_for_valid_file(self, tmp_path: Path) -> None:
        from academic_pipeline.runtime.authors_yaml import (
            AuthorsYamlEntry,
            load_authors_yaml,
        )

        f = tmp_path / "authors.yaml"
        f.write_text(
            "- name: Jackson Yang\n"
            "  affiliation: Example Institute\n"
            "  email: jackson@example.com\n"
            "  orcid: 0000-0001-2345-6789\n"
            "- name: Co Author\n"
            "  affiliation: Some Lab\n",
            encoding="utf-8",
        )
        entries = load_authors_yaml(f)
        assert len(entries) == 2
        assert isinstance(entries[0], AuthorsYamlEntry)
        assert entries[0].name == "Jackson Yang"
        assert entries[0].affiliation == "Example Institute"
        assert entries[0].email == "jackson@example.com"
        assert entries[0].orcid == "0000-0001-2345-6789"
        # orcid is optional — second entry has none.
        assert entries[1].orcid is None

    def test_missing_file_raises_ren002(self, tmp_path: Path) -> None:
        from academic_pipeline.runtime.authors_yaml import load_authors_yaml
        from academic_pipeline.runtime.rendering_errors import AuthorsYamlMissing

        with pytest.raises(AuthorsYamlMissing) as exc:
            load_authors_yaml(tmp_path / "missing.yaml")
        assert exc.value.error_code == "REN002"

    def test_top_level_dict_form_also_accepted(self, tmp_path: Path) -> None:
        """Spec allows ``authors:`` mapping form too — the broader plan uses it."""
        from academic_pipeline.runtime.authors_yaml import load_authors_yaml

        f = tmp_path / "authors.yaml"
        f.write_text(
            "authors:\n" "  - name: Solo Author\n" "    affiliation: Solo Lab\n",
            encoding="utf-8",
        )
        entries = load_authors_yaml(f)
        assert len(entries) == 1
        assert entries[0].name == "Solo Author"

    def test_malformed_yaml_raises_ren002(self, tmp_path: Path) -> None:
        from academic_pipeline.runtime.authors_yaml import load_authors_yaml
        from academic_pipeline.runtime.rendering_errors import AuthorsYamlMissing

        f = tmp_path / "authors.yaml"
        # Top-level scalar is not a list/dict-with-authors.
        f.write_text("not-a-list", encoding="utf-8")
        with pytest.raises(AuthorsYamlMissing) as exc:
            load_authors_yaml(f)
        assert exc.value.error_code == "REN002"

    def test_missing_required_name_raises_ren002(self, tmp_path: Path) -> None:
        from academic_pipeline.runtime.authors_yaml import load_authors_yaml
        from academic_pipeline.runtime.rendering_errors import AuthorsYamlMissing

        f = tmp_path / "authors.yaml"
        f.write_text(
            "- affiliation: Lab Without Author\n",
            encoding="utf-8",
        )
        with pytest.raises(AuthorsYamlMissing) as exc:
            load_authors_yaml(f)
        assert exc.value.error_code == "REN002"

    def test_empty_authors_list_raises_ren002(self, tmp_path: Path) -> None:
        from academic_pipeline.runtime.authors_yaml import load_authors_yaml
        from academic_pipeline.runtime.rendering_errors import AuthorsYamlMissing

        f = tmp_path / "authors.yaml"
        f.write_text("[]", encoding="utf-8")
        with pytest.raises(AuthorsYamlMissing) as exc:
            load_authors_yaml(f)
        assert exc.value.error_code == "REN002"


class TestResolveAuthorsYamlPath:
    """``resolve_authors_yaml_path(*candidates)`` walks resolution order."""

    def test_returns_first_existing_candidate(self, tmp_path: Path) -> None:
        from academic_pipeline.runtime.authors_yaml import resolve_authors_yaml_path

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "authors.yaml").write_text("[]", encoding="utf-8")

        # run_dir has no file; repo_root does. Resolver returns repo_root path.
        resolved = resolve_authors_yaml_path(run_dir, repo_root)
        assert resolved == repo_root / "authors.yaml"

    def test_prefers_run_dir_over_repo_root(self, tmp_path: Path) -> None:
        from academic_pipeline.runtime.authors_yaml import resolve_authors_yaml_path

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "authors.yaml").write_text("[]", encoding="utf-8")
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "authors.yaml").write_text("[]", encoding="utf-8")

        assert resolve_authors_yaml_path(run_dir, repo_root) == run_dir / "authors.yaml"

    def test_returns_none_when_no_candidate_exists(self, tmp_path: Path) -> None:
        from academic_pipeline.runtime.authors_yaml import resolve_authors_yaml_path

        assert resolve_authors_yaml_path(tmp_path / "a", tmp_path / "b") is None
