"""Producer-side helpers: convert experiment results into NumericalProducts.

Lives in experiment/ (not traceability/) because the logic is experiment-specific —
walks the ExperimentResults shape produced by the experiment subgraph. The
traceability/ module only owns receiver-side logic (validation, substitution,
appendix rendering).

ExperimentResults.metrics shape:
    dict[method_name, dict[metric_label, float | MultiSeedMetric]]

Each scalar metric becomes one NumericalProduct with a composite label
``{method_name}__{metric_label}`` so labels remain unique across methods and
match the writer-side token regex ``[a-zA-Z_][a-zA-Z0-9_]*``.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from academic_pipeline.models.experiment import MultiSeedMetric
from academic_pipeline.models.numerical import NumericalProduct


if TYPE_CHECKING:
    from academic_pipeline.models.experiment import ExperimentResults


logger = logging.getLogger(__name__)

_LABEL_SAFE_PATTERN = re.compile(r"[^a-zA-Z0-9_]")


def _sanitize_label(raw: str) -> str:
    """Convert an arbitrary string into a token-safe label.

    Replaces any character that isn't ``[a-zA-Z0-9_]`` with ``_`` and prepends
    ``_`` if the result starts with a digit so the label matches NUM_TOKEN_PATTERN.
    """
    safe = _LABEL_SAFE_PATTERN.sub("_", raw)
    if safe and safe[0].isdigit():
        safe = "_" + safe
    return safe


def extract_numerical_products_from_result(
    result: ExperimentResults,
    run_id: str,
    source_step: str,
    *,
    code: str | None = None,
    code_filename: str | None = None,
) -> list[NumericalProduct]:
    """Walk an ``ExperimentResults.metrics`` map; emit one NumericalProduct per scalar.

    For nested ``metrics[method][metric] = value``:
      - float/int values become products with label ``{method}__{metric}``
      - MultiSeedMetric values use the ``.mean`` field as the value
      - booleans, strings, lists, None, and other non-numeric values are skipped

    The label is sanitized to match the writer-side regex
    ``[a-zA-Z_][a-zA-Z0-9_]*`` (dots, dashes, etc. become underscores).

    When ``code`` is supplied, walks the AST to find lines that wrote each
    metric, populating ``NumericalProduct.source_code_line`` as
    ``"<filename>:<lineno>"``. Looks up by composite label first (e.g.
    ``xgboost__auc``), then falls back to raw metric label (``auc``). When
    a label can't be resolved (dynamic key, parse error, or no match),
    ``source_code_line`` stays ``None`` and the renderer degrades gracefully.
    """
    line_map: dict[str, int] = {}
    if code is not None:
        try:
            from academic_pipeline.experiment.line_tracer import extract_metric_lines
            line_map = extract_metric_lines(code)
        except SyntaxError:
            logger.warning(
                "Could not parse experiment code for line tracing — "
                "source_code_line will be None for run_id=%s", run_id,
            )
            line_map = {}

    filename = code_filename or "analysis.py"

    products: list[NumericalProduct] = []
    metrics = result.metrics or {}
    for method_name, method_metrics in metrics.items():
        if not isinstance(method_metrics, dict):
            continue
        for metric_label, value in method_metrics.items():
            scalar: float | None = _coerce_scalar(value)
            if scalar is None:
                continue
            label = _sanitize_label(f"{method_name}__{metric_label}")

            # Resolve line: try composite first, fall back to raw metric label
            lineno: int | None = line_map.get(label) or line_map.get(metric_label)
            source_code_line = f"{filename}:{lineno}" if lineno else None

            products.append(NumericalProduct(
                label=label,
                value=str(scalar),
                unit=None,
                formula=f"computed in experiment script for method '{method_name}'",
                source_run_id=run_id,
                source_step=source_step,
                source_artifact=f"output/{run_id}/code/{filename}",
                source_code_line=source_code_line,
                context=f"Metric '{metric_label}' for method '{method_name}' from {source_step}",
            ))
    return products


def _coerce_scalar(value: object) -> float | None:
    """Return a numeric scalar for the value or None if not extractable.

    Booleans are rejected (bool is a subclass of int but is not a metric).
    MultiSeedMetric values return their ``.mean``. Strings and lists return None.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, MultiSeedMetric):
        return value.mean
    if isinstance(value, (int, float)):
        return float(value) if isinstance(value, int) else value
    return None
