# ha-stroomanalyse

Exports Home Assistant energy statistics from `home-assistant_v2.db` to a CSV file that you can upload to the [JeroenNL stroomanalyse](https://jeroen.nl).

The output has the columns `DatumTijd,Import,Export,Opwek`, with **one row per hour**. Each value is the energy in kWh used, delivered, or produced during that hour. The values are calculated from the cumulative `sum` in Home Assistant's long-term `statistics` table. Hourly data is used because Home Assistant only keeps 5-minute data for about 10 days.

- If you pass more than one statistic_id for a column, their values are added together for each hour. This also lets you combine a replaced sensor with its successor.
- Hours without data are written as `0`. Negative steps, such as meter corrections, are treated as `0`.
- `DatumTijd` is in system local time, formatted like `25-08-2024 0:00:00`.

## Usage

```powershell
uv run ha-stroomanalyse home-assistant_v2.db `
    --import-ids sensor.energy_consumption_tarif_1 sensor.energy_consumption_tarif_2 `
    --export-ids sensor.energy_production_tarif_1 sensor.energy_production_tarif_2 `
    --opwek-ids sensor.solaredge_lifetime_energy sensor.solaredge_se4000h_energie `
    --start 2025-01-01 --end 2025-12-31 -o stroom-2025.csv
```

| Argument | Description |
|---|---|
| `DATABASE` | Path to the Home Assistant SQLite database (required) |
| `--import-ids`, `--export-ids`, `--opwek-ids` | One or more statistic_ids for each column (required) |
| `-o`, `--output` | Output CSV path (default: `output.csv` in the current directory) |
| `--start`, `--end` | Optional range in local time (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`), inclusive. A date-only `--end` includes the whole day. If you leave these out, all data is exported. |

## Development

```powershell
uv run pytest
```
