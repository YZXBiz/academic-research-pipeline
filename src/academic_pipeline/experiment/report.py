# academic_pipeline/experiment/report.py
"""Deterministic HTML report generator for experiment results.

Reads from artifacts/ and figures/ directories. No LLM involved.
Inline CSS only, zero external dependencies.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_experiment_report(experiment_dir: Path) -> str:
    """Generate an HTML report from experiment artifacts.

    Args:
        experiment_dir: Path to output/<run_id>/02-experiment/

    Returns:
        HTML string. Also writes to experiment_dir/index.html.
    """
    artifacts = experiment_dir / "artifacts"
    figures_dir = experiment_dir / "figures"

    results = _load_json(artifacts / "results.json")
    plan = _load_json(artifacts / "experiment_plan.json")
    repro = _load_json(artifacts / "reproducibility.json")
    judge = _load_json(artifacts / "judge_verdict.json")
    dataset = _load_json(artifacts / "dataset_info.json")

    success = results is not None and bool(results.get("metrics"))
    status = "SUCCESS" if success else "FAILED"
    badge_color = "#28a745" if success else "#dc3545"

    figures_html = _render_figures(figures_dir)
    metrics_html = _render_metrics(results)
    stats_html = _render_statistical_tests(results)
    dataset_html = _render_dataset_card(dataset, plan)
    repro_html = _render_reproducibility(repro)
    judge_html = _render_judge(judge)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Experiment Report</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.6; }}
h1 {{ border-bottom: 2px solid #eee; padding-bottom: 10px; }}
h2 {{ color: #555; margin-top: 30px; }}
.badge {{ display: inline-block; padding: 4px 12px; border-radius: 4px; color: white; font-weight: bold; background: {badge_color}; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f5f5f5; }}
.card {{ background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; padding: 16px; margin: 10px 0; }}
.figure {{ text-align: center; margin: 20px 0; }}
.figure img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 4px; }}
pre {{ background: #f5f5f5; padding: 12px; border-radius: 4px; overflow-x: auto; }}
</style>
</head>
<body>
<h1>Experiment Report <span class="badge">{status}</span></h1>
{dataset_html}
{metrics_html}
{stats_html}
{figures_html}
{judge_html}
{repro_html}
</body>
</html>"""

    out_path = experiment_dir / "index.html"
    out_path.write_text(html)
    logger.info("Experiment report written to %s", out_path)
    return html


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _render_figures(figures_dir: Path) -> str:
    if not figures_dir or not figures_dir.exists():
        return "<h2>Figures</h2><p>No figures generated.</p>"
    pngs = sorted(figures_dir.glob("*.png"))
    if not pngs:
        return "<h2>Figures</h2><p>No figures generated.</p>"
    parts = ["<h2>Figures</h2>"]
    for p in pngs:
        b64 = base64.b64encode(p.read_bytes()).decode()
        caption = p.stem.replace("_", " ").replace("fig ", "").title()
        parts.append(
            f'<div class="figure"><img src="data:image/png;base64,{b64}" alt="{caption}">'
            f"<p><em>{caption}</em></p></div>"
        )
    return "\n".join(parts)


def _render_metrics(results: dict | None) -> str:
    if not results or not results.get("metrics"):
        return "<h2>Metrics</h2><p>No metrics available.</p>"
    metrics = results["metrics"]
    rows = ""
    if isinstance(metrics, dict):
        for k, v in metrics.items():
            if isinstance(v, dict):
                for mk, mv in v.items():
                    rows += f"<tr><td>{k}</td><td>{mk}</td><td>{mv}</td></tr>"
            else:
                rows += f"<tr><td colspan='2'>{k}</td><td>{v}</td></tr>"
    return f"<h2>Metrics</h2><table><tr><th>Model</th><th>Metric</th><th>Value</th></tr>{rows}</table>"


def _render_statistical_tests(results: dict | None) -> str:
    if not results or not results.get("statistical_tests"):
        return ""
    tests = results["statistical_tests"]
    rows = ""
    for name, data in tests.items():
        if isinstance(data, dict):
            rows += f"<tr><td>{name}</td><td>{data.get('test_name', '')}</td><td>{data.get('p_value', '')}</td><td>{'Yes' if data.get('significant') else 'No'}</td></tr>"
    return f"<h2>Statistical Tests</h2><table><tr><th>Comparison</th><th>Test</th><th>p-value</th><th>Significant</th></tr>{rows}</table>"


def _render_dataset_card(dataset: dict | None, plan: dict | None) -> str:
    if not dataset and not plan:
        return ""
    src = dataset or {}
    if not src and plan:
        ds_list = plan.get("dataset_sources", [])
        src = ds_list[0] if ds_list else {}
    return (
        '<div class="card"><h2>Dataset</h2>'
        f"<p><strong>{src.get('name', 'Unknown')}</strong></p>"
        f"<p>Source: {src.get('source', 'N/A')}</p>"
        f"<p>Shape: {src.get('expected_shape', 'N/A')}</p>"
        f"<p>Target: {src.get('target_column', 'N/A')}</p></div>"
    )


def _render_reproducibility(repro: dict | None) -> str:
    if not repro:
        return ""
    rows = "".join(f"<tr><td>{k}</td><td><pre>{json.dumps(v) if isinstance(v, (dict, list)) else v}</pre></td></tr>" for k, v in repro.items())
    return f"<h2>Reproducibility</h2><table>{rows}</table>"


def _render_judge(judge: dict | None) -> str:
    if not judge:
        return ""
    verdict = judge.get("verdict", "N/A")
    color = "#28a745" if verdict == "APPROVED" else "#ffc107"
    checklist = judge.get("checklist", {})
    items = "".join(
        f"<li>{'✓' if v else '✗'} {k}</li>" for k, v in checklist.items()
    )
    suggestions = judge.get("suggestions", [])
    sugg_html = "<ul>" + "".join(f"<li>{s}</li>" for s in suggestions) + "</ul>" if suggestions else ""
    return (
        f'<h2>Judge Verdict <span class="badge" style="background:{color}">{verdict}</span></h2>'
        f"<ul>{items}</ul>{sugg_html}"
    )
