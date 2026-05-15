"""Dagster experiment workspace package init.

Injects truststore into ssl as the FIRST runtime action so any
subsequent HTTPS call (huggingface_hub, MLflow) trusts the system
trust store. Without this, corporate SSL inspection proxies' MITM
certs are rejected and httpx auto-closes the client mid-handshake —
which Dagster's multiprocess executor surfaces only as an opaque
"Steps failed: ['raw_data']" with no actionable stderr.
"""

import truststore

truststore.inject_into_ssl()


# Re-export the publication-quality matplotlib style helper for generated
# figures.py @asset modules. They can `from pipeline import apply_pub_style,
# column_width_inches, page_width_inches` without reaching into the
# underscored module path.
from pipeline._publication_style import (  # noqa: E402  (must come after truststore inject)
    PUB_STYLE,
    apply_pub_style,
    column_width_inches,
    page_width_inches,
)

# Also re-export the most-needed runtime symbols. run-0515-1340 surfaced a
# repeat agent error: the spec shows `from pipeline import apply_pub_style,
# column_width_inches` (figures example) and `from pipeline.resources import
# workspace_dir` (results.json example) separately, and the agent merges
# them into `from pipeline import apply_pub_style, column_width_inches,
# workspace_dir`, which then fails at module load time with
# `ImportError: cannot import name 'workspace_dir' from 'pipeline'`.
# Re-exporting at the package root closes that footgun rather than relying
# on prompt discipline.
from pipeline.resources import ConfigResource, workspace_dir  # noqa: E402

__all__ = [
    "PUB_STYLE",
    "ConfigResource",
    "apply_pub_style",
    "column_width_inches",
    "page_width_inches",
    "workspace_dir",
]
