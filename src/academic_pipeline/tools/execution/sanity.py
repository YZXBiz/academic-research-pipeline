"""Post-execution sanity checks, plan-alignment verification, dataset URL probes.

Pure-Python validators that run after a script has been executed (or, in the
case of plan alignment, before execution). No subprocess, no Docker.
"""
from __future__ import annotations

import ast
import logging
import math
from typing import TYPE_CHECKING

from academic_pipeline.models.experiment import (
    DatasetSpec,
    DatasetVerificationResult,
    PlanAlignmentResult,
)


if TYPE_CHECKING:
    from academic_pipeline.models.experiment import ExperimentPlan

logger = logging.getLogger(__name__)


def sanity_check_results(results: dict) -> list[str]:
    """Deterministic sanity checks on experiment results.

    Flags:
    - All methods reporting identical metrics
    - Accuracy > 0.99 (suspiciously high)
    - NaN or Inf metric values
    - Negative values for accuracy/f1/roc_auc/precision/recall
    """
    issues: list[str] = []
    metrics = results.get("metrics", {})
    if not metrics:
        issues.append("No metrics found in results")
        return issues

    # Check individual metric values
    for method, method_metrics in metrics.items():
        if not isinstance(method_metrics, dict):
            continue
        for metric_name, value in method_metrics.items():
            if isinstance(value, float):
                if math.isnan(value):
                    issues.append(f"NaN metric: {method}.{metric_name}")
                elif math.isinf(value):
                    issues.append(f"Infinite metric: {method}.{metric_name}")
                elif (
                    value < 0
                    and metric_name
                    in (
                        "accuracy",
                        "f1",
                        "f1_macro",
                        "f1_weighted",
                        "roc_auc",
                        "precision",
                        "recall",
                    )
                ):
                    issues.append(
                        f"Negative metric: {method}.{metric_name} = {value}"
                    )

    # Check for suspiciously high accuracy
    for method, method_metrics in metrics.items():
        if not isinstance(method_metrics, dict):
            continue
        acc = method_metrics.get("accuracy")
        if acc is not None and isinstance(acc, (int, float)) and acc > 0.99:
            issues.append(
                f"Suspiciously high accuracy for {method}: {acc:.4f} (possible data leakage)"
            )

    # Check for identical metrics across all methods
    if len(metrics) >= 2:
        all_values = list(metrics.values())
        if all(v == all_values[0] for v in all_values[1:]):
            issues.append("All methods report identical metrics (possible bug)")

    return issues


def verify_plan_alignment(
    code: str, plan: ExperimentPlan
) -> PlanAlignmentResult:
    """Check that generated code implements what the experiment plan specifies."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return PlanAlignmentResult(
            aligned=False,
            missing_methods=[
                m.implementation
                for m in plan.baseline_methods + plan.proposed_methods
            ],
        )

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name)
                if alias.asname:
                    imported_names.add(alias.asname)
        if isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.add(node.module)
            for alias in node.names or []:
                imported_names.add(alias.name)
                if alias.asname:
                    imported_names.add(alias.asname)

    code_lower = code.lower()

    missing_methods: list[str] = []
    for method in plan.baseline_methods + plan.proposed_methods:
        impl = method.implementation
        class_name = impl.split("(")[0].strip()
        if class_name not in imported_names and class_name not in code:
            missing_methods.append(class_name)

    metric_aliases = {
        "accuracy": ["accuracy", "accuracy_score"],
        "f1": ["f1_score", "f1"],
        "f1_macro": ["f1_score", "f1_macro", "f1"],
        "f1_weighted": ["f1_score", "f1_weighted", "f1"],
        "roc_auc": ["roc_auc_score", "roc_auc"],
        "precision": ["precision_score", "precision"],
        "recall": ["recall_score", "recall"],
        "rmse": ["mean_squared_error", "rmse"],
    }
    missing_metrics: list[str] = []
    for metric in plan.evaluation_metrics:
        aliases = metric_aliases.get(metric, [metric])
        if not any(a in code for a in aliases):
            missing_metrics.append(metric)

    missing_datasets: list[str] = [
        ds.name
        for ds in plan.dataset_sources
        if ds.name.lower() not in code_lower and ds.download_instruction not in code
    ]

    missing_figures: list[str] = [
        fig for fig in plan.required_figures if fig not in code
    ]

    cv_terms = [
        "cross_val_score",
        "KFold",
        "StratifiedKFold",
        "RepeatedKFold",
        "cross_validate",
    ]
    missing_cv = not any(term in code for term in cv_terms)

    stat_terms = ["wilcoxon", "ttest_rel", "mannwhitneyu", "friedmanchisquare"]
    missing_stats = not any(term in code for term in stat_terms)

    aligned = (
        not missing_methods
        and not missing_metrics
        and not missing_datasets
        and not missing_figures
        and not missing_cv
        and not missing_stats
    )

    return PlanAlignmentResult(
        aligned=aligned,
        missing_methods=missing_methods,
        missing_metrics=missing_metrics,
        missing_datasets=missing_datasets,
        missing_figures=missing_figures,
        missing_statistical_tests=missing_stats,
        missing_cross_validation=missing_cv,
    )


# ---------------------------------------------------------------------------
# Dataset URL verification + email alert
# ---------------------------------------------------------------------------

PACKAGE_SOURCES = frozenset({"huggingface"})


def _check_url_reachable(url: str, timeout: int = 10) -> bool:
    """Check if a URL is reachable. Try HEAD first, fall back to GET."""
    import requests as _requests

    try:
        resp = _requests.head(url, timeout=timeout, allow_redirects=True)
        if resp.status_code < 400:
            return True
        if resp.status_code in (405, 403):
            resp = _requests.get(url, stream=True, timeout=timeout, allow_redirects=True)
            resp.close()
            return resp.status_code < 400
        return False
    except Exception:
        return False


def verify_dataset_urls(datasets: list[DatasetSpec]) -> DatasetVerificationResult:
    """Verify that all datasets in the plan are reachable."""
    if not datasets:
        return DatasetVerificationResult(
            all_verified=False, failed_datasets=["No datasets provided"]
        )
    failed: list[str] = []
    verified: list[str] = []
    for ds in datasets:
        if ds.source in PACKAGE_SOURCES:
            verified.append(ds.name)
            continue
        if ds.source == "url":
            url = ds.download_instruction
            if _check_url_reachable(url):
                verified.append(ds.name)
            else:
                failed.append(ds.name)
        else:
            # Unknown source type — assume it's OK (e.g. kaggle, openml)
            verified.append(ds.name)
    return DatasetVerificationResult(
        all_verified=len(failed) == 0,
        failed_datasets=failed,
        verified_datasets=verified,
    )


async def send_dataset_alert(
    topic: str, missing_datasets: list[str], config: object
) -> None:
    """Send email alert when pipeline needs a dataset. Best-effort."""
    smtp_server = getattr(config, "experiment_smtp_server", "")
    alert_email = getattr(config, "experiment_alert_email", "")
    alert_sender = getattr(config, "experiment_alert_sender", "")
    smtp_port = getattr(config, "experiment_smtp_port", 25)
    if not smtp_server or not alert_email:
        logger.info("No SMTP config — skipping dataset alert email")
        return
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart()
    msg["From"] = alert_sender
    msg["To"] = alert_email
    msg["Subject"] = f"[Pipeline] Dataset needed: {topic[:50]}"
    body = (
        "<h2>Pipeline paused — dataset needed</h2>"
        f"<p><b>Topic:</b> {topic}</p>"
        "<p><b>Issues:</b></p><ul>"
        + "".join(f"<li>{d}</li>" for d in missing_datasets)
        + "</ul>"
        "<p>Provide dataset via <code>EXPERIMENT_DATASET_PATH</code> "
        "in .env and resume with <code>--thread-id</code>.</p>"
    )
    msg.attach(MIMEText(body, "html"))
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.send_message(msg)
        logger.info("Dataset alert email sent to %s", alert_email)
    except Exception as e:
        logger.warning("Failed to send dataset alert email: %s", e)
