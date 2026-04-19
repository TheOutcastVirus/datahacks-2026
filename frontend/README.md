# SAWJESS Frontend

The frontend is a static-build-friendly Next.js app for the SAWJESS sea-level visualization demo. Runtime pages read the checked-in curve artifact at `frontend/data/sea-level/california-demo-default.json`; Databricks is only used during data refresh.

## Local development

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Tests

```bash
cd frontend
npm test
```

## Sea-level data refresh

1. Run the Databricks pipeline in [databricks/README.md](../databricks/README.md).
2. Export the curve artifact from the repo root:

```bash
DATABRICKS_HOST=...
DATABRICKS_TOKEN=...
DATABRICKS_WAREHOUSE_ID=...
node scripts/export-sea-level-curve.mjs
```

The export script validates that:

- years are strictly increasing
- `2026` exists and has `riseFrom2026Meters = 0`
- every year from `2026` through `2100` is present
- non-extrapolated rows after `2026` are non-negative and non-decreasing
