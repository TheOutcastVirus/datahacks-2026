# AI Workspace

Organized project layout:

- `code/`: Python scripts for data prep, exploration, modeling, and dashboards
- `data/raw/`: downloaded source archives, CSVs, PDFs, and extracted vendor data
- `data/processed/`: derived NetCDFs, normalized tables, and forecast CSVs
- `docs/`: reports, plans, dataset notes, and plot write-up
- `outputs/plots/`: generated figures and HTML dashboards
- `.venv/`: local Python environment

Shared paths live in `code/project_paths.py`, so scripts should use that module instead of assuming a flat `ai/` directory.
