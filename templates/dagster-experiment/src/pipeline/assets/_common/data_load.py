"""Materialize raw_<file> tables in DuckDB from dataset.source.

Supports huggingface://, file://, http(s)://. CSV / parquet auto-detected by extension.

NOTE: `from __future__ import annotations` is intentionally omitted. Dagster's
@asset decorator inspects parameter annotations at runtime and does identity
comparisons (e.g. context arg must BE AssetExecutionContext, not the string
"AssetExecutionContext"). PEP 563 deferred annotations break that check."""
from pathlib import Path

from dagster import AssetExecutionContext, MetadataValue, asset
from dagster_duckdb import DuckDBResource
from huggingface_hub import hf_hub_download

from pipeline.resources import ConfigResource, workspace_dir


@asset(group_name="_common")
def raw_data(
    context: AssetExecutionContext,
    app_config: ConfigResource,
    duckdb: DuckDBResource,
) -> dict[str, int]:
    """For each file in dataset.files, materialize a `raw_<stem>` DuckDB table.

    Returns: {table_name: row_count} for downstream observability."""
    cfg = app_config.get().dataset
    out: dict[str, int] = {}
    with duckdb.get_connection() as con:
        for filename in cfg.files:
            local_path = _resolve(cfg.source, filename)
            stem = Path(filename).stem.replace("-", "_")
            table = f"raw_{stem}"
            ext = Path(filename).suffix.lower()
            if ext == ".csv":
                # sample_size=-1 scans the WHOLE file for type detection. The default
                # 20480-row sample mis-infers any column whose first values look like
                # one type but later rows have a wider range (e.g. rossmann's
                # StateHoliday: BIGINT in early rows, "a"/"b"/"c" later). null_padding
                # tolerates short rows. Both options keep all data — no silent NULLing
                # of unparseable values, which would mask real CSV corruption.
                con.sql(
                    f"CREATE OR REPLACE TABLE {table} AS "
                    f"SELECT * FROM read_csv_auto('{local_path}', "
                    f"sample_size=-1, null_padding=true)"
                )
            elif ext in (".parquet", ".pq"):
                con.sql(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_parquet('{local_path}')")
            else:
                raise ValueError(f"Unsupported file extension: {ext} (file={filename})")
            n = con.sql(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            out[table] = n
            context.log.info("materialized %s with %d rows from %s", table, n, local_path)
    context.add_output_metadata({k: MetadataValue.int(v) for k, v in out.items()})
    return out


def _resolve(source: str, filename: str) -> str:
    if source.startswith("huggingface://"):
        repo = source.removeprefix("huggingface://")
        return hf_hub_download(repo_id=repo, filename=filename, repo_type="dataset")
    if source.startswith("file://"):
        return str(Path(source.removeprefix("file://")) / filename)
    if source.startswith(("http://", "https://")):
        return f"{source.rstrip('/')}/{filename}"  # DuckDB read_csv_auto handles URLs
    # treat as local path
    p = Path(source) / filename
    if not p.exists():
        # support absolute file paths in tests/fixtures
        candidate = Path(filename)
        if candidate.is_absolute() and candidate.exists():
            return str(candidate)
    return str(p)
