"""Bibliography tools — citation formatting, DOI verification, search APIs."""
from __future__ import annotations

from academic_pipeline.tools.bibliography.bibtex import (
    generate_bibtex_entry,
    generate_bibtex_file,
)
from academic_pipeline.tools.bibliography.citations import (
    CitationMetadata,
    convert_citation_style,
    format_citation,
    validate_citation,
)
from academic_pipeline.tools.bibliography.doi import (
    check_retraction,
    resolve_doi_metadata,
    verify_doi,
)
from academic_pipeline.tools.bibliography.exa import (
    web_fetch_exa,
    web_search_exa,
)
from academic_pipeline.tools.bibliography.semantic_scholar import (
    batch_verify_s2,
    get_s2_paper_details,
    search_s2_by_title,
)

__all__ = [
    "CitationMetadata",
    "batch_verify_s2",
    "check_retraction",
    "convert_citation_style",
    "format_citation",
    "generate_bibtex_entry",
    "generate_bibtex_file",
    "get_s2_paper_details",
    "resolve_doi_metadata",
    "search_s2_by_title",
    "validate_citation",
    "verify_doi",
    "web_fetch_exa",
    "web_search_exa",
]
