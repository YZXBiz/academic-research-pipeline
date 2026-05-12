"""Pydantic domain models, organized per pipeline phase.

Subdomains:
- shared:     types used across multiple subgraphs (Author, Source, Reference, Evaluator*)
- research:   research-phase models (Bibliography, Synthesis, Methodology, Ethics, ...)
- writing:    writing-phase models (PaperDraft, Section, Figure, Table, Style*, ...)
- review:     review-phase models (PeerReview*, Editorial*, Revision*)
- integrity:  integrity-phase models (Compliance*, Phase{A-E}, IntegrityReport, MaterialPassport)
- experiment: experiment-phase models (Experiment*, Dataset*, Figure{Artifact,Review})
"""

from __future__ import annotations

from academic_pipeline.models.shared import *  # noqa: F401, F403
from academic_pipeline.models.research import *  # noqa: F401, F403
from academic_pipeline.models.writing import *  # noqa: F401, F403
from academic_pipeline.models.review import *  # noqa: F401, F403
from academic_pipeline.models.integrity import *  # noqa: F401, F403
from academic_pipeline.models.experiment import *  # noqa: F401, F403
