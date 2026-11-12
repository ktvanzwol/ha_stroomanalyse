"""Export Home Assistant energy statistics to a JeroenNL stroomanalyse CSV."""

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

import polars as pl

COLUMNS = ("Import", "Export", "Opwek")
HOUR = 3600


class UnknownStatisticError(ValueError):
    def __init__(self, missing: Sequence[str]) -> None:
        super().__init__(f"Unknown statistic_id(s): {', '.join(missing)}")
        self.missing = list(missing)


def _connect(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise FileNotFoundError(f"Database not found: {database}")
    return sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)


def read_statistics(database: Path, statistic_ids: Sequence[str]) -> pl.DataFrame:
    """Read hourly `sum` values for the given statistic_ids from the long-term statistics table."""
    placeholders = ", ".join("?" for _ in statistic_ids)
    query = f"""
        SELECT m.statistic_id, CAST(s.start_ts AS INTEGER) AS start_ts, s.sum
        FROM statistics s
        JOIN statistics_meta m ON m.id = s.metadata_id
        WHERE m.statistic_id IN ({placeholders}) AND s.sum IS NOT NULL
        ORDER BY m.statistic_id, s.start_ts
    """
    with _connect(database) as conn:
        found = {
            row[0]
            for row in conn.execute(
                f"SELECT statistic_id FROM statistics_meta WHERE statistic_id IN ({placeholders})",
                list(statistic_ids),
            )
        }
        missing = [sid for sid in statistic_ids if sid not in found]
        if missing:
            raise UnknownStatisticError(missing)
        return pl.read_database(
            query,
            connection=conn,
            execute_options={"parameters": list(statistic_ids)},
            schema_overrides={"statistic_id": pl.String, "start_ts": pl.Int64, "sum": pl.Float64},
        )


def hourly_usage(
    statistics: pl.DataFrame,
    columns: Mapping[str, Sequence[str]],
    start_ts: float | None = None,
    end_ts: float | None = None,
    end_inclusive: bool = True,
) -> pl.DataFrame:
    """Turn cumulative `sum` statistics into per-hour totals per output column.

    Returns a frame with `start_ts` (UTC epoch seconds, full hourly grid) and one
    Float64 column per key in `columns`. Multiple statistic_ids per column are summed.
    """
    mapping = pl.DataFrame(
        [(sid, col) for col, ids in columns.items() for sid in ids],
        schema={"statistic_id": pl.String, "column": pl.String},
        orient="row",
    )
    deltas = (
        statistics.sort("statistic_id", "start_ts")
        .with_columns(delta=pl.col("sum").diff().over("statistic_id").clip(lower_bound=0))
        .drop_nulls("delta")
    )
    if start_ts is not None:
        deltas = deltas.filter(pl.col("start_ts") >= start_ts)
    if end_ts is not None:
        deltas = deltas.filter(
            pl.col("start_ts") <= end_ts if end_inclusive else pl.col("start_ts") < end_ts
        )

    totals = (
        deltas.join(mapping, on="statistic_id")
        .group_by("start_ts", "column")
        .agg(pl.col("delta").sum())
        .pivot(on="column", index="start_ts", values="delta")
    )
    if totals.is_empty():
        return pl.DataFrame(schema={"start_ts": pl.Int64, **{col: pl.Float64 for col in columns}})

    grid = pl.DataFrame(
        {"start_ts": pl.int_range(totals["start_ts"].min(), totals["start_ts"].max() + 1, HOUR, eager=True)}
    )
    for col in columns:
        if col not in totals.columns:
            totals = totals.with_columns(pl.lit(0.0).alias(col))
    return (
        grid.join(totals, on="start_ts", how="left")
        .select("start_ts", *[pl.col(col).fill_null(0.0) for col in columns])
        .sort("start_ts")
    )


def format_local(ts: int) -> str:
    """Format a UTC epoch as system local time like `25-08-2024 0:00:00`."""
    d = datetime.fromtimestamp(ts)
    return f"{d:%d-%m-%Y} {d.hour}:{d:%M:%S}"


def to_jeroen_csv(usage: pl.DataFrame) -> pl.DataFrame:
    return usage.select(
        pl.Series("DatumTijd", [format_local(ts) for ts in usage["start_ts"]], dtype=pl.String),
        *COLUMNS,
    )


def export(
    database: Path,
    output: Path,
    import_ids: Sequence[str],
    export_ids: Sequence[str],
    opwek_ids: Sequence[str],
    start: datetime | None = None,
    end: datetime | None = None,
    end_inclusive: bool = True,
) -> int:
    """Write the CSV and return the number of data rows written."""
    columns = {"Import": list(import_ids), "Export": list(export_ids), "Opwek": list(opwek_ids)}
    all_ids = list(dict.fromkeys(sid for ids in columns.values() for sid in ids))
    usage = hourly_usage(
        read_statistics(database, all_ids),
        columns,
        start_ts=start.timestamp() if start else None,
        end_ts=end.timestamp() if end else None,
        end_inclusive=end_inclusive,
    )
    result = to_jeroen_csv(usage)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.write_csv(output)
    return result.height
