"""apply_pub_style must be re-exported from pipeline.__init__ so generated
figures.py modules can import it as `from pipeline import apply_pub_style`
instead of the underscored module path."""
from __future__ import annotations

from pathlib import Path


def test_pipeline_init_reexports_apply_pub_style() -> None:
    init_path = (
        Path(__file__).resolve().parents[3]
        / "templates" / "dagster-experiment" / "src" / "pipeline" / "__init__.py"
    )
    src = init_path.read_text(encoding="utf-8")
    assert "apply_pub_style" in src, (
        "templates/dagster-experiment/src/pipeline/__init__.py must re-export "
        "apply_pub_style so generated figures.py @asset modules can do "
        "`from pipeline import apply_pub_style` cleanly."
    )
    assert "_publication_style" in src, (
        "Re-export must source from the _publication_style module."
    )
    # Truststore inject must still come first (SSL-injection-before-anything-else
    # invariant). The re-export must come AFTER `truststore.inject_into_ssl()`.
    truststore_idx = src.find("truststore.inject_into_ssl()")
    pubstyle_idx = src.find("_publication_style")
    assert truststore_idx > 0, "truststore.inject_into_ssl() call missing"
    assert pubstyle_idx > truststore_idx, (
        "Re-export of _publication_style must come AFTER truststore.inject_into_ssl() "
        "to preserve the SSL-injection-first invariant."
    )
