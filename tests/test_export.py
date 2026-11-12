import sqlite3
from datetime import datetime

import polars as pl
import pytest

from ha_stroomanalyse.cli import main

BASE = int(datetime(2025, 6, 1, 0, 0).timestamp())
H = 3600


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "ha.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE statistics_meta (id INTEGER PRIMARY KEY, statistic_id TEXT);
        CREATE TABLE statistics (metadata_id INTEGER, start_ts FLOAT, sum FLOAT);
        """
    )
    sums = {
        "imp_1": [10.0, 10.5, 11.0, 11.0, 12.0],
        "imp_2": [5.0, 5.25, 5.25, 5.5, 5.5],
        "exp_1": [1.0, 1.0, 1.0, 2.0, 2.0],
        # meter correction: a decreasing sum must not produce a negative value
        "exp_2": [3.0, 3.0, 2.5, 2.5, 2.75],
    }
    for meta_id, (sid, values) in enumerate(sums.items(), start=1):
        conn.execute("INSERT INTO statistics_meta VALUES (?, ?)", (meta_id, sid))
        conn.executemany(
            "INSERT INTO statistics VALUES (?, ?, ?)",
            [(meta_id, BASE + i * H, v) for i, v in enumerate(values)],
        )
    # Opwek sensor replaced: old one stops at hour 2, new one starts at hour 2 and skips hour 3.
    conn.execute("INSERT INTO statistics_meta VALUES (5, 'pv_old'), (6, 'pv_new')")
    conn.executemany(
        "INSERT INTO statistics VALUES (?, ?, ?)",
        [(5, BASE, 100.0), (5, BASE + H, 100.5), (5, BASE + 2 * H, 101.0),
         (6, BASE + 2 * H, 0.01), (6, BASE + 4 * H, 1.01)],
    )
    conn.commit()
    conn.close()
    return path


def run(database, tmp_path, *extra):
    output = tmp_path / "out.csv"
    code = main([
        str(database), "-o", str(output),
        "--import-ids", "imp_1", "imp_2",
        "--export-ids", "exp_1", "exp_2",
        "--opwek-ids", "pv_old", "pv_new",
        *extra,
    ])
    assert code == 0
    return pl.read_csv(output)


def label(hour):
    d = datetime.fromtimestamp(BASE + hour * H)
    return f"{d:%d-%m-%Y} {d.hour}:{d:%M:%S}"


def test_sums_ids_per_hour(database, tmp_path):
    df = run(database, tmp_path)
    assert df.columns == ["DatumTijd", "Import", "Export", "Opwek"]
    assert df["DatumTijd"].to_list() == [label(h) for h in range(1, 5)]
    assert df["Import"].to_list() == [0.75, 0.5, 0.25, 1.0]
    assert df["Export"].to_list() == [0.0, 0.0, 1.0, 0.25]
    # hour 3 has no Opwek rows: filled with 0; pv_new's first row only serves as baseline
    assert df["Opwek"].to_list() == [0.5, 0.5, 0.0, 1.0]


def test_date_range_is_local_and_inclusive(database, tmp_path):
    start = datetime.fromtimestamp(BASE + 2 * H).strftime("%Y-%m-%dT%H:%M")
    end = datetime.fromtimestamp(BASE + 3 * H).strftime("%Y-%m-%dT%H:%M")
    df = run(database, tmp_path, "--start", start, "--end", end)
    assert df["DatumTijd"].to_list() == [label(2), label(3)]
    assert df["Import"].to_list() == [0.5, 0.25]


def test_date_only_end_covers_whole_day(database, tmp_path):
    day = datetime.fromtimestamp(BASE).date().isoformat()
    df = run(database, tmp_path, "--start", day, "--end", day)
    assert df.height == 4


def test_unknown_statistic_id(database, tmp_path, capsys):
    code = main([str(database), "-o", str(tmp_path / "o.csv"), "--import-ids", "nope",
                 "--export-ids", "exp_1", "--opwek-ids", "pv_old"])
    assert code == 1
    assert "nope" in capsys.readouterr().err


def test_ids_are_required(database):
    with pytest.raises(SystemExit):
        main([str(database), "--import-ids", "imp_1", "--export-ids", "exp_1"])
