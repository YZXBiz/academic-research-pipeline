"""Result object returned by Pipeline methods."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_PHASE_ARTIFACTS: dict[str, list[tuple[str, str]]] = {
    "01-research": [
        ("rq_brief", "md"),
        ("methodology_blueprint", "json"),
        ("bibliography", "md"),
        # PRD §6.1.T7 — knowledge_graph artifact removed (model + node deleted).
        ("synthesis", "md"),
    ],
    "02-writing": [
        ("paper_outline", "json"),
        ("argument_blueprint", "json"),
        ("paper_draft", "md"),
        ("figure_package", "json"),
        ("style_profile", "json"),
        ("score_history", "json"),
    ],
    "03-integrity": [
        ("integrity_report", "json"),
        ("compliance_reports", "json"),
    ],
    "04-review": [
        ("review_report", "json"),
        ("revision_roadmap", "md"),
    ],
    "05-final": [
        ("material_passport", "json"),
    ],
}

_SENSITIVE_PREFIXES = ("/etc", "/usr", "/bin", "/sbin", "/var", "/boot", "/proc", "/sys", "/dev")


def _reject_sensitive_path(path: Path) -> None:
    """Raise ValueError if path falls under a system-sensitive directory."""
    path_str = str(path)
    for prefix in _SENSITIVE_PREFIXES:
        if path_str == prefix or path_str.startswith(prefix + "/"):
            raise ValueError(f"Refusing to write artifacts to sensitive path: {path}")


class PipelineResult:
    """Wraps the raw state dict with convenient property access."""

    def __init__(self, state: dict[str, Any]) -> None:
        """Initialize with the raw pipeline state dictionary.

        Args:
            state: The pipeline state dict produced by graph execution.
        """
        self._state = state

    @property
    def paper_draft(self) -> str | dict[str, Any] | None:
        """Return the paper draft content."""
        return self._state.get("paper_draft")

    @property
    def research_question(self) -> str | dict[str, Any] | None:
        """Return the research question brief."""
        return self._state.get("rq_brief")

    @property
    def bibliography(self) -> str | dict[str, Any] | None:
        """Return the bibliography."""
        return self._state.get("bibliography")

    @property
    def synthesis(self) -> str | dict[str, Any] | None:
        """Return the research synthesis."""
        return self._state.get("synthesis")

    @property
    def review_report(self) -> dict[str, Any] | None:
        """Return the editorial review report."""
        return self._state.get("review_report")

    @property
    def integrity_report(self) -> dict[str, Any] | None:
        """Return the integrity verification report."""
        return self._state.get("integrity_report")

    @property
    def revision_roadmap(self) -> str | dict[str, Any] | None:
        """Return the revision roadmap."""
        return self._state.get("revision_roadmap")

    @property
    def status(self) -> str:
        """Return the pipeline execution status."""
        return self._state.get("pipeline_status", "unknown")

    @property
    def error(self) -> str | None:
        """Return the error message if the pipeline failed, else None."""
        return self._state.get("error")

    @property
    def latex_source(self) -> str | None:
        """Return the LaTeX source content."""
        return self._state.get("latex_source") or None

    @property
    def bib_source(self) -> str | None:
        """Return the BibTeX bibliography content."""
        return self._state.get("bib_source") or None

    @property
    def output_format(self) -> str:
        """Return the output format (markdown or latex)."""
        return self._state.get("output_format", "markdown")

    @property
    def raw(self) -> dict[str, Any]:
        """Access the full raw state dictionary."""
        return self._state

    def save(self, output_dir: str | Path) -> Path:
        """Save all pipeline artifacts to disk.

        Writes markdown for text artifacts and JSON for structured data.
        Skips artifacts that are None/empty.

        Args:
            output_dir: Directory path where artifacts will be written. Created (with parents) if it does not exist.

        Returns:
            The resolved Path of the output directory.

        Raises:
            ValueError: If output_dir resolves to a system-sensitive location.
        """
        out = Path(output_dir).resolve()
        _reject_sensitive_path(out)
        out.mkdir(parents=True, exist_ok=True)

        # Save artifacts organized by phase
        for phase_dir, artifacts in _PHASE_ARTIFACTS.items():
            for key, fmt in artifacts:
                val = self._state.get(key)
                if not val:
                    continue
                artifact_path = out / phase_dir / "artifacts"
                artifact_path.mkdir(parents=True, exist_ok=True)
                if fmt == "json":
                    if hasattr(val, "model_dump"):
                        (artifact_path / f"{key}.json").write_text(val.model_dump_json(indent=2), encoding="utf-8")
                    elif isinstance(val, dict | list):
                        (artifact_path / f"{key}.json").write_text(
                            json.dumps(val, indent=2, default=str), encoding="utf-8"
                        )
                else:
                    from academic_pipeline.models.writing import PaperDraft

                    if isinstance(val, PaperDraft):
                        from academic_pipeline.runtime.paper_renderer import render_markdown

                        # Pass figure_package so the saved paper_draft.md
                        # artifact contains rendered tables and figure refs
                        # — same shape as the markdown LatexCompilerNode
                        # ships to pandoc. Without this, paper_draft.md
                        # was missing all results tables even though the
                        # PDF rendered them correctly.
                        figure_package = self._state.get("figure_package")
                        text = render_markdown(val, figure_package=figure_package)
                    elif hasattr(val, "model_dump_json"):
                        text = val.model_dump_json(indent=2)
                    elif isinstance(val, str):
                        text = val
                    else:
                        text = json.dumps(val, indent=2, default=str)
                    (artifact_path / f"{key}.md").write_text(text, encoding="utf-8")

        # Run config — reproducibility
        from datetime import UTC, datetime

        run_config = {
            "topic": self._state.get("topic", ""),
            "run_id": self._state.get("run_id", ""),
            "pipeline_status": self._state.get("pipeline_status", ""),
            "current_stage": str(self._state.get("current_stage", "")),
            "saved_at": datetime.now(UTC).isoformat(),
        }
        (out / "run_config.json").write_text(json.dumps(run_config, indent=2), encoding="utf-8")

        # Messages — full agent conversation audit trail
        messages = self._state.get("messages", [])
        if messages:
            (out / "messages.json").write_text(json.dumps(messages, indent=2, default=str), encoding="utf-8")

        # LaTeX artifacts + PDF
        latex_source = self._state.get("latex_source", "")
        if latex_source:
            latex_dir = out / "02-writing" / "artifacts"
            latex_dir.mkdir(parents=True, exist_ok=True)
            (latex_dir / "paper.tex").write_text(latex_source, encoding="utf-8")

        bib_source = self._state.get("bib_source", "")
        if bib_source:
            latex_dir = out / "02-writing" / "artifacts"
            latex_dir.mkdir(parents=True, exist_ok=True)
            (latex_dir / "references.bib").write_text(bib_source, encoding="utf-8")

        pdf_bytes = self._state.get("pdf_bytes", b"")
        if pdf_bytes:
            pdf_dir = out / "02-writing" / "artifacts"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            (pdf_dir / "paper.pdf").write_bytes(pdf_bytes)

        return out

    def __repr__(self) -> str:
        return f"PipelineResult(status={self.status!r}, topic={self._state.get('topic', 'N/A')!r})"
