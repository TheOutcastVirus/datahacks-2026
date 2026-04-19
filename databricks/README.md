# SAWJESS Databricks Sea-Level Pipeline

This directory contains the Databricks-side refresh path for the shared SAWJESS sea-level curve. The frontend never calls Databricks at runtime; it reads the checked-in JSON artifact at `frontend/data/sea-level/california-demo-default.json`.

## Objects

- Catalog: `main`
- Schema: `sawjess`
- Raw volume: `/Volumes/main/sawjess/raw/sea_level/`
- Bronze table: `main.sawjess.sea_level_bronze_monthly`
- Silver table: `main.sawjess.sea_level_silver_monthly`
- Gold table: `main.sawjess.sea_level_gold_yearly`
- Export view: `main.sawjess.sea_level_demo_curve`

## Raw input

The pipeline accepts a CSV with monthly rows and these source columns:

- `time` or `timestamp`
- `predicted_msl` or `predicted_MSL`
- `predicted_trend`
- optional `predicted_residual`
- optional `seasonal_climatology`
- optional `observed_msl`

Formula rule:

- If `predicted_msl` is present, treat it as absolute MSL.
- Only fall back to `predicted_trend + seasonal_climatology` when absolute MSL is absent.
- Do not add `predicted_msl + predicted_trend`.

## Run the Databricks job

1. Upload the raw CSV into `/Volumes/main/sawjess/raw/sea_level/`.
2. Run `databricks/sea_level_pipeline.py` as a Databricks Python job or notebook task.
3. Confirm that `main.sawjess.sea_level_demo_curve` contains one row per year from `2026` through the last modeled year plus extrapolated rows through `2100`.

## Export the frontend artifact

From the repo root:

```bash
DATABRICKS_HOST=...
DATABRICKS_TOKEN=...
DATABRICKS_WAREHOUSE_ID=...
node scripts/export-sea-level-curve.mjs
```

Optional overrides:

- `DATABRICKS_CATALOG`
- `DATABRICKS_SCHEMA`
- `DATABRICKS_VIEW`
- `SEA_LEVEL_EXPORT_QUERY`
- `SEA_LEVEL_SOURCE_LABEL`
- `SEA_LEVEL_SOURCE_REGION_LABEL`
- `SEA_LEVEL_SOURCE_STATION_ID`

For offline iteration, `SEA_LEVEL_EXPORT_INPUT_JSON` can point at a local JSON file containing either a `records` array or raw Databricks-style rows.
