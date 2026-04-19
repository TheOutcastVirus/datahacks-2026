# Sojs Annual Projection Implementation Plan

Use a separate annual projection track and keep `predict_monthly.py` as the monthly reconstruction/export path. The clean rollout is six steps.

## 1. Build the annual training table

Create `annual_projection_data.py` that reads `data/normalized/sojs_active_monthly_normalized.nc`, aggregates to calendar-year means, and writes:

- `data/annual/sojs_portland_annual_training.csv`
- `data/annual/sojs_portland_annual_training.nc`
- `plots/annual/portland_annual_coverage.png`

Include these columns at minimum:

- `year`
- `portland_msl_m`
- `portland_msl_m_anomaly` if derivable cleanly
- `copernicus_sla_gom_m`
- `greenland_mass_gt`
- `nao_annual_mean`
- `nao_winter_djf`
- `gia_metadata_mm_yr`
- placeholder land-motion columns such as `vlm_mm_yr`, `vlm_sigma_mm_yr`, `land_motion_source`

Rules:

- Require at least 9 valid months for a yearly mean.
- Carry `months_present_<var>` columns for every predictor and target.
- Do not include Argo or historical GRACE as required annual predictors in the projection table.

## 2. Add the first annual driver family: NAO

`nao_index.py` already exists, so use it as the first atmospheric/climate family. Add a join step in `annual_projection_data.py` that derives:

- annual mean NAO
- winter DJF NAO
- optional lagged versions: previous-year annual NAO, previous winter NAO

Acceptance criterion:

- NAO-based annual features join cleanly to Portland for a long historical window, ideally most of the 20th century onward.

## 3. Add one land-motion refinement source

Implement a new ingestion path such as `land_motion.py` and a normalized artifact:

- `data/land_motion/portland_land_motion.nc`
- `plots/land_motion/portland_land_motion_summary.csv`

Keep scope narrow for the first pass:

- one site-level or nearest-grid estimate for Portland
- one mean rate and one uncertainty
- explicit metadata about whether it is GIA-only, VLM-only, or combined relative land motion

Use it first as deterministic metadata in the target adjustment, not as a noisy learned predictor. The point is to stop pretending fixed literature GIA is the whole land-motion story.

## 4. Fit a separate annual model

Create `annual_projection_model.py`. Do not reuse `hindcast_model.py` directly; reuse only low-level utility ideas if helpful.

Model ladder:

- `baseline_trend`
- `trend_plus_nao`
- `trend_plus_nao_plus_sla`
- `trend_plus_nao_plus_sla_plus_greenland`
- optional ridge version if annual predictors become collinear

Recommended target:

- annual Portland relative sea level, with land-motion adjustment handled explicitly and consistently

Recommended design:

- fit on annual means only
- no Argo requirement
- no historical GRACE requirement
- optional lag terms for NAO and SLA
- standardize predictors inside train folds only

## 5. Backtest for long-horizon behavior

Add rolling-origin validation in `annual_projection_model.py` instead of the short monthly split logic in `hindcast_model.py`.

Required backtests:

- 5-year holdout horizon
- 10-year holdout horizon
- rolling-origin forecast evaluation
- final contiguous tail holdout, for example last 10 years

Report:

- RMSE
- MAE
- bias
- trend error over holdout
- interval coverage for prediction bands

Outputs:

- `data/annual/sojs_portland_annual_backtest.csv`
- `plots/annual/portland_annual_backtest.png`
- `plots/annual/sojs_annual_model_summary.md`

## 6. Publish annual scenario projections

Create `project_annual.py` that consumes a fitted annual model plus explicit scenario inputs and writes:

- `data/projections/sojs_portland_annual_projections.csv`
- `data/projections/sojs_portland_annual_projections.nc`
- `plots/projections/portland_annual_projection.png`
- `plots/projections/sojs_annual_projection_summary.md`

Scenario structure:

- `baseline`
- `low`
- `high`

Uncertainty should widen with lead time using three components:

- model residual variance
- parameter uncertainty from backtesting or bootstrap/refit spread
- scenario spread from exogenous inputs

## Repo changes

Add these files:

- `annual_projection_data.py`
- `annual_projection_model.py`
- `project_annual.py`
- `land_motion.py`
- `docs/annual_projection.md`

Update these files:

- `plan.md`
- `docs/data_collection.md`
- `docs/modeling_and_projection.md`

## Execution order

1. Implement `annual_projection_data.py`.
2. Wire in NAO-derived annual features.
3. Add the land-motion artifact and metadata.
4. Fit and backtest the annual model.
5. Generate scenario-based annual projections.
6. Update docs to make the monthly vs annual split explicit.

## Definition of done

This annual projection track is ready when:

- Portland has a long-record annual training table with explicit feature coverage diagnostics.
- The annual model beats a trend-only baseline on rolling holdouts.
- Projections are scenario-driven, not blind extrapolations.
- Uncertainty bands widen with lead time.
- `predict_monthly.py` remains limited to reconstruction/export and is not used as the long-horizon projection engine.
