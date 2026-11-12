import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from ha_stroomanalyse.export import UnknownStatisticError, export


def _parse_local(value: str) -> tuple[datetime, bool]:
    """Parse an ISO date/datetime as naive (system local) time; also report if it was date-only."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date/datetime: {value!r}") from exc
    if parsed.tzinfo is not None:
        raise argparse.ArgumentTypeError(f"timezone not allowed, use local time: {value!r}")
    return parsed, len(value.strip()) == 10


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ha-stroomanalyse",
        description="Export Home Assistant energy statistics to an hourly CSV for the JeroenNL stroomanalyse.",
    )
    parser.add_argument("database", type=Path, help="path to home-assistant_v2.db")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path.cwd() / "output.csv",
        help="output CSV path (default: ./output.csv)",
    )
    parser.add_argument("--import-ids", nargs="+", required=True, metavar="ID",
                        help="statistic_id(s) summed into the Import column")
    parser.add_argument("--export-ids", nargs="+", required=True, metavar="ID",
                        help="statistic_id(s) summed into the Export column")
    parser.add_argument("--opwek-ids", nargs="+", required=True, metavar="ID",
                        help="statistic_id(s) summed into the Opwek column")
    parser.add_argument("--start", type=_parse_local,
                        help="first hour to include, local time (YYYY-MM-DD or YYYY-MM-DDTHH:MM)")
    parser.add_argument("--end", type=_parse_local,
                        help="last hour to include, local time; a date includes that whole day")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    start = args.start[0] if args.start else None
    end, end_inclusive = None, True
    if args.end:
        end, date_only = args.end
        if date_only:
            end, end_inclusive = end + timedelta(days=1), False
    if start and end and (end < start or (end == start and not end_inclusive)):
        parser.error("--end must not be before --start")

    try:
        rows = export(
            args.database, args.output, args.import_ids, args.export_ids, args.opwek_ids,
            start=start, end=end, end_inclusive=end_inclusive,
        )
    except (FileNotFoundError, UnknownStatisticError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {rows} rows to {args.output}")
    return 0
