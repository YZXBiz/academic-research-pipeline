"""Tests for the §6.7.T2 DOI CrossRef build gate.

Covers two surfaces:
1. ``verify_dois_in_bibtex``: parses bibtex, verifies each entry's DOI in
   parallel, returns a list of ``DoiVerificationResult`` dicts.
2. ``compile_pdf_pandoc``: invokes the gate before tectonic; raises
   ``DOICrossRefError`` (REN001) on any unverified DOI in the default
   fail-closed mode; allows the build to proceed when the operator passes
   ``allow_unverified_dois=True``; emits one ``doi_gate_failure`` event per
   unverified DOI via the supplied ``EventLogger``.

All HTTP calls are mocked — no real CrossRef hits.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest


if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio


_BIB_THREE_ENTRIES = """\
@article{macqueen1967,
  author = {MacQueen, J. B.},
  title = {Some methods for classification},
  year = {1967},
  doi = {None},
}

@article{ester1996dbscan,
  author = {Ester, M. and others},
  title = {DBSCAN},
  year = {1996},
  doi = {10.5555/hallucinated.fake},
}

@article{viswanathan2023,
  author = {Viswanathan, V. and others},
  title = {LLMs Enable Few-Shot Clustering},
  year = {2023},
  doi = {10.48550/arXiv.2307.00524},
}
"""


async def _fake_verify(doi: str) -> str:
    if "hallucinated" in doi:
        return json.dumps({"doi": doi, "exists": False, "status": 404})
    return json.dumps({"doi": doi, "exists": True, "status": 200})


class TestVerifyDoisInBibtex:
    """Tests for ``tools/bibliography/doi.py::verify_dois_in_bibtex``."""

    async def test_returns_one_result_per_entry_with_a_doi(self) -> None:
        from academic_pipeline.tools.bibliography.doi import verify_dois_in_bibtex

        with patch(
            "academic_pipeline.tools.bibliography.doi.verify_doi",
            new=AsyncMock(side_effect=_fake_verify),
        ):
            results = await verify_dois_in_bibtex(_BIB_THREE_ENTRIES)

        # macqueen1967 has doi={None} → skipped (no_doi); ester + viswanathan
        # both have real DOI fields, so 2 results expected.
        assert len(results) == 2
        keys = {r["key"] for r in results}
        assert keys == {"ester1996dbscan", "viswanathan2023"}

    async def test_each_result_carries_doi_status_and_verified_flag(self) -> None:
        from academic_pipeline.tools.bibliography.doi import verify_dois_in_bibtex

        with patch(
            "academic_pipeline.tools.bibliography.doi.verify_doi",
            new=AsyncMock(side_effect=_fake_verify),
        ):
            results = await verify_dois_in_bibtex(_BIB_THREE_ENTRIES)

        by_key = {r["key"]: r for r in results}
        assert by_key["viswanathan2023"]["verified"] is True
        assert by_key["viswanathan2023"]["doi"] == "10.48550/arXiv.2307.00524"
        assert by_key["viswanathan2023"]["crossref_status"] == 200

        assert by_key["ester1996dbscan"]["verified"] is False
        assert by_key["ester1996dbscan"]["crossref_status"] == 404

    async def test_empty_bibtex_returns_empty_list(self) -> None:
        from academic_pipeline.tools.bibliography.doi import verify_dois_in_bibtex

        results = await verify_dois_in_bibtex("")
        assert results == []


class TestRenderingErrors:
    """REN error namespace per PRD §17."""

    def test_doi_crossref_failure_carries_ren001(self) -> None:
        from academic_pipeline.runtime.rendering_errors import DOICrossRefError

        err = DOICrossRefError(unverified_dois=["10.1/x", "10.2/y"])
        assert err.error_code == "REN001"
        assert "10.1/x" in str(err)
        assert "10.2/y" in str(err)


class TestCompilePdfPandocDoiGate:
    """Tests for the build-gate hook inside ``compile_pdf_pandoc``."""

    @pytest.fixture
    def bib_with_one_bad_doi(self) -> str:
        return (
            "@article{good,\n  doi = {10.48550/arXiv.2307.00524},\n}\n\n"
            "@article{bad,\n  doi = {10.5555/hallucinated.fake},\n}\n"
        )

    @pytest.fixture
    def bib_all_verified(self) -> str:
        return "@article{good,\n  doi = {10.48550/arXiv.2307.00524},\n}\n"

    async def test_default_fail_closed_raises_ren001_on_unverified(
        self, bib_with_one_bad_doi: str, tmp_path: Path
    ) -> None:
        from academic_pipeline.runtime.rendering_errors import DOICrossRefError
        from academic_pipeline.tools.rendering.latex_compiler import compile_pdf_pandoc

        with (
            patch(
                "academic_pipeline.tools.bibliography.doi.verify_doi",
                new=AsyncMock(side_effect=_fake_verify),
            ),
            pytest.raises(DOICrossRefError) as exc,
        ):
            await compile_pdf_pandoc(
                markdown="# t\n",
                bib_source=bib_with_one_bad_doi,
                output_dir=tmp_path,
            )

        assert exc.value.error_code == "REN001"
        assert "10.5555/hallucinated.fake" in str(exc.value)

    async def test_allow_unverified_dois_skips_abort(self, bib_with_one_bad_doi: str, tmp_path: Path) -> None:
        from academic_pipeline.tools.rendering.latex_compiler import compile_pdf_pandoc

        # Stub tectonic so we don't actually shell out to pandoc.
        async def fake_proc(*_args, **_kwargs):
            class P:
                returncode = 1  # pretend pandoc fails — we only care that the gate didn't abort first

                async def communicate(self):
                    return (b"stub", None)

            return P()

        with (
            patch(
                "academic_pipeline.tools.bibliography.doi.verify_doi",
                new=AsyncMock(side_effect=_fake_verify),
            ),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=fake_proc)),
        ):
            # Should NOT raise DOICrossRefError — gate was bypassed.
            result = await compile_pdf_pandoc(
                markdown="# t\n",
                bib_source=bib_with_one_bad_doi,
                output_dir=tmp_path,
                allow_unverified_dois=True,
            )
        # pandoc stubbed to fail → returns None, but importantly NO exception.
        assert result is None

    async def test_all_verified_passes_gate_proceeds_to_pandoc(self, bib_all_verified: str, tmp_path: Path) -> None:
        from academic_pipeline.tools.rendering.latex_compiler import compile_pdf_pandoc

        async def fake_proc(*_args, **_kwargs):
            class P:
                returncode = 1

                async def communicate(self):
                    return (b"stub", None)

            return P()

        with (
            patch(
                "academic_pipeline.tools.bibliography.doi.verify_doi",
                new=AsyncMock(side_effect=_fake_verify),
            ),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=fake_proc)),
        ):
            result = await compile_pdf_pandoc(
                markdown="# t\n",
                bib_source=bib_all_verified,
                output_dir=tmp_path,
            )
        # Gate passed; pandoc stub returned 1 → result None, but no exception.
        assert result is None

    async def test_no_bib_source_skips_gate_entirely(self, tmp_path: Path) -> None:
        from academic_pipeline.tools.rendering.latex_compiler import compile_pdf_pandoc

        async def fake_proc(*_args, **_kwargs):
            class P:
                returncode = 1

                async def communicate(self):
                    return (b"stub", None)

            return P()

        # verify_doi must NEVER be called when bib_source is empty.
        verify_mock = AsyncMock(side_effect=_fake_verify)
        with (
            patch("academic_pipeline.tools.bibliography.doi.verify_doi", new=verify_mock),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=fake_proc)),
        ):
            await compile_pdf_pandoc(
                markdown="# t\n",
                bib_source="",
                output_dir=tmp_path,
            )

        verify_mock.assert_not_called()


class TestDoiGateEventEmission:
    """The gate emits one ``doi_gate_failure`` event per unverified DOI."""

    async def test_unverified_doi_emits_doi_gate_failure_event(self, tmp_path: Path) -> None:
        from academic_pipeline.runtime.events import EventLogger
        from academic_pipeline.runtime.rendering_errors import DOICrossRefError
        from academic_pipeline.tools.rendering.latex_compiler import compile_pdf_pandoc

        logger = EventLogger(tmp_path)
        events_path = logger.path

        with (
            patch(
                "academic_pipeline.tools.bibliography.doi.verify_doi",
                new=AsyncMock(side_effect=_fake_verify),
            ),
            pytest.raises(DOICrossRefError),
        ):
            await compile_pdf_pandoc(
                markdown="# t\n",
                bib_source=(
                    "@article{good,\n  doi = {10.48550/arXiv.2307.00524},\n}\n\n"
                    "@article{bad,\n  doi = {10.5555/hallucinated.fake},\n}\n"
                ),
                output_dir=tmp_path,
                event_logger=logger,
            )

        # Read the events file; expect exactly one doi_gate_failure for the bad DOI.
        lines = [json.loads(ln) for ln in events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        gate_failures = [ln for ln in lines if ln.get("type") == "doi_gate_failure"]
        assert len(gate_failures) == 1
        ev = gate_failures[0]
        assert ev["doi"] == "10.5555/hallucinated.fake"
        assert ev["crossref_status"] == 404
        assert ev["blocking"] is True
        assert ev["error_code"] == "REN001"

    async def test_allow_unverified_marks_event_blocking_false(self, tmp_path: Path) -> None:
        from academic_pipeline.runtime.events import EventLogger
        from academic_pipeline.tools.rendering.latex_compiler import compile_pdf_pandoc

        logger = EventLogger(tmp_path)
        events_path = logger.path

        async def fake_proc(*_args, **_kwargs):
            class P:
                returncode = 1

                async def communicate(self):
                    return (b"", None)

            return P()

        with (
            patch(
                "academic_pipeline.tools.bibliography.doi.verify_doi",
                new=AsyncMock(side_effect=_fake_verify),
            ),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=fake_proc)),
        ):
            await compile_pdf_pandoc(
                markdown="# t\n",
                bib_source="@article{bad,\n  doi = {10.5555/hallucinated.fake},\n}\n",
                output_dir=tmp_path,
                event_logger=logger,
                allow_unverified_dois=True,
            )

        lines = [json.loads(ln) for ln in events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        gate_failures = [ln for ln in lines if ln.get("type") == "doi_gate_failure"]
        assert len(gate_failures) == 1
        assert gate_failures[0]["blocking"] is False
