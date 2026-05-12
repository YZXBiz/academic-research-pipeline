"""Tests for the async LaTeX compiler tool wrapping tectonic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from academic_pipeline.tools.rendering.latex_compiler import (
    _copy_acl_assets,
    compile_latex,
    compile_pdf_pandoc,
    write_latex_files,
)


pytestmark = pytest.mark.anyio


class TestWriteLatexFiles:
    """Tests for write_latex_files."""

    def test_writes_tex_and_bib(self, tmp_path: object) -> None:
        """Both files written, content matches."""
        from pathlib import Path

        out = Path(str(tmp_path)) / "build"
        write_latex_files("\\documentclass{article}", "@article{key,}", out)
        assert (out / "paper.tex").read_text(encoding="utf-8") == "\\documentclass{article}"
        assert (out / "references.bib").read_text(encoding="utf-8") == "@article{key,}"

    def test_writes_tex_without_bib(self, tmp_path: object) -> None:
        """Only .tex written when bib_source is empty."""
        from pathlib import Path

        out = Path(str(tmp_path)) / "build"
        write_latex_files("\\documentclass{article}", "", out)
        assert (out / "paper.tex").exists()
        assert not (out / "references.bib").exists()


class TestCompileLatex:
    """Tests for compile_latex (tectonic is always mocked)."""

    @patch("academic_pipeline.tools.rendering.latex_compiler._run_tectonic")
    async def test_successful_compilation(self, mock_run: object, tmp_path: object) -> None:
        """Successful tectonic run returns path to paper.pdf."""
        from pathlib import Path
        from unittest.mock import AsyncMock

        mock = AsyncMock(return_value=(0, ""))
        mock_run.side_effect = mock.side_effect  # type: ignore[union-attr]
        mock_run.return_value = mock.return_value  # type: ignore[union-attr]

        out = Path(str(tmp_path)) / "build"

        # _run_tectonic is mocked, so we need to create the PDF ourselves
        async def fake_tectonic(working_dir: Path) -> tuple[int, str]:
            (working_dir / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
            return 0, ""

        mock_run.side_effect = fake_tectonic  # type: ignore[union-attr]

        result = await compile_latex("\\documentclass{article}", "", out)
        assert result is not None
        assert result.name == "paper.pdf"
        assert result.exists()

    @patch("academic_pipeline.tools.rendering.latex_compiler._run_tectonic")
    async def test_compilation_failure_returns_none(self, mock_run: object, tmp_path: object) -> None:
        """Failed tectonic run returns None."""
        from pathlib import Path
        from unittest.mock import AsyncMock

        mock = AsyncMock(return_value=(1, "! LaTeX Error: File not found."))
        mock_run.side_effect = mock.side_effect  # type: ignore[union-attr]
        mock_run.return_value = mock.return_value  # type: ignore[union-attr]

        out = Path(str(tmp_path)) / "build"
        result = await compile_latex("\\documentclass{article}", "", out)
        assert result is None


class TestCopyAclAssets:
    """``_copy_acl_assets`` must populate build_dir with everything tectonic + pandoc need."""

    def test_copies_required_files_into_build_dir(self, tmp_path: Path) -> None:
        build = tmp_path / "build"
        build.mkdir()
        _copy_acl_assets(build)
        # ACL style + bib style are needed by tectonic for \usepackage{acl}
        # and \bibliographystyle{acl_natbib}.
        assert (build / "acl.sty").exists(), "acl.sty must be copied for \\usepackage{acl}"
        assert (build / "acl_natbib.bst").exists(), "acl_natbib.bst needed for natbib references"
        # Pandoc resolves these relative to its cwd.
        assert (build / "acl-header.tex").exists(), "header injected via --include-in-header"
        assert (build / "longtable-to-table-star.lua").exists(), "lua filter copied"


class TestCompilePdfPandocCmd:
    """Verify the pandoc command shape — ACL house style, NOT IEEEtran."""

    @staticmethod
    def _patched_subprocess(returncode: int = 0):
        """Build an AsyncMock that captures the pandoc argv and writes a fake PDF."""
        recorded: dict[str, list[str]] = {"argv": []}

        async def fake_create_subprocess_exec(*args, **kwargs):
            recorded["argv"] = list(args)
            cwd = kwargs.get("cwd")
            if returncode == 0 and cwd is not None:
                (Path(cwd) / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
            proc = MagicMock()
            proc.returncode = returncode
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        return fake_create_subprocess_exec, recorded

    @patch("academic_pipeline.tools.rendering.latex_compiler.asyncio.create_subprocess_exec")
    async def test_cmd_uses_acl_class_not_ieeetran(self, mock_exec: MagicMock, tmp_path: Path) -> None:
        fake, recorded = self._patched_subprocess()
        mock_exec.side_effect = fake

        out = tmp_path / "build"
        await compile_pdf_pandoc("# Hi\n\nbody", "", out)

        argv = recorded["argv"]
        # ACL style: article + 11pt, NOT IEEEtran journal/onecolumn.
        assert "documentclass=article" in argv
        assert "classoption=11pt" in argv
        assert "documentclass=IEEEtran" not in argv
        assert not any("journal,onecolumn" in a for a in argv)
        assert not any("fontsize=10pt" in a for a in argv)

    @patch("academic_pipeline.tools.rendering.latex_compiler.asyncio.create_subprocess_exec")
    async def test_cmd_includes_lua_filter_and_acl_header(
        self, mock_exec: MagicMock, tmp_path: Path,
    ) -> None:
        fake, recorded = self._patched_subprocess()
        mock_exec.side_effect = fake

        out = tmp_path / "build"
        await compile_pdf_pandoc("# Hi\n\nbody", "", out)

        argv = recorded["argv"]
        assert "--lua-filter=longtable-to-table-star.lua" in argv
        assert "--include-in-header=acl-header.tex" in argv
        assert "--number-sections" in argv

    @patch("academic_pipeline.tools.rendering.latex_compiler.asyncio.create_subprocess_exec")
    async def test_cmd_adds_natbib_only_when_bib_present(
        self, mock_exec: MagicMock, tmp_path: Path,
    ) -> None:
        fake, recorded = self._patched_subprocess()
        mock_exec.side_effect = fake

        out = tmp_path / "build"
        await compile_pdf_pandoc("# Hi\n\nbody", "@article{x, title={X}}", out)

        argv = recorded["argv"]
        assert "--natbib" in argv
        assert "--bibliography=references.bib" in argv
        # MUST NOT pass biblio-style: acl.sty:195 sets it internally and a
        # duplicate \bibstyle{} crashes bibtex.
        assert not any("biblio-style" in a for a in argv)

    @patch("academic_pipeline.tools.rendering.latex_compiler.asyncio.create_subprocess_exec")
    async def test_cmd_omits_natbib_when_no_bib(
        self, mock_exec: MagicMock, tmp_path: Path,
    ) -> None:
        """Without a bib file, --natbib would emit \\bibliography{references}
        that tectonic can't resolve. Skip the flag."""
        fake, recorded = self._patched_subprocess()
        mock_exec.side_effect = fake

        out = tmp_path / "build"
        await compile_pdf_pandoc("# Hi\n\nbody", "", out)

        argv = recorded["argv"]
        assert "--natbib" not in argv
        assert not any("bibliography=" in a for a in argv)

    @patch("academic_pipeline.tools.rendering.latex_compiler.asyncio.create_subprocess_exec")
    async def test_assets_copied_into_build_dir_before_pandoc(
        self, mock_exec: MagicMock, tmp_path: Path,
    ) -> None:
        fake, recorded = self._patched_subprocess()
        mock_exec.side_effect = fake

        out = tmp_path / "build"
        result = await compile_pdf_pandoc("# Hi\n\nbody", "@x{a,}", out)

        assert result is not None
        # Pandoc resolves --include-in-header / --lua-filter relative to
        # cwd, so these MUST exist in the build dir at compile time.
        assert (out / "acl.sty").exists()
        assert (out / "acl_natbib.bst").exists()
        assert (out / "acl-header.tex").exists()
        assert (out / "longtable-to-table-star.lua").exists()
        assert (out / "paper.md").read_text(encoding="utf-8") == "# Hi\n\nbody"
        assert (out / "references.bib").read_text(encoding="utf-8") == "@x{a,}"
