# Sojs Modeling And Projection Notes

## Scope

This document captures the modeling and projection work completed in Sojs after the retained active datasets were normalized onto a shared monthly timeline.

It covers:

- the validated Phase 4 hindcast workflow
- the shared-model refactor done to support projections
- the monthly prediction/export pipeline
- the separate annual projection pipeline
- regime definitions
- validation outcomes
- current interpretation limits

## 1. Phase 4 Hindcast

### Purpose

The Phase 4 hindcast answers a narrower question than full budget closure:

- can the retained Sojs active stack support a coherent monthly hindcast workflow
- how much local monthly variability does it explain
- what remains unresolved in the residual

### Stations in scope

- Portland
- Bar Harbor

Rockland is not included in the validated monthly modeling window because the retained modern overlap excludes a modern Rockland target series.

### Overlap window used for model validation

- Start: `2004-07-01`
- End: `2017-06-01`
- Samples per modeled station: `40`

This window is defined by the months where the cleaned Argo monthly context series survive the support filters and the retained modern predictors are simultaneously available.

### Final model kept by Sojs

- `ols_with_argo_ridge`

Predictors used by the final model:

- `copernicus_sla_gom_m_zscore`
- `grace_hist_lwe_thickness_gom_m_zscore`
- `greenland_mass_gt_zscore`
- `argo_density_shelf_0_200dbar_kg_m3_zscore`

### Why density is the retained Argo predictor

The Argo part of the final model keeps density only.

Reason:

- density already encodes both temperature and salinity physically
- including temperature, salinity, and density together produced near-collinear predictor columns on the short overlap window
- that short-window collinearity inflated coefficient variance and degraded out-of-sample stability

### Validation design

- trend-adjusted seasonal cycle is removed from both target and predictors before cross-validation
- forward time-series splits are used to avoid future leakage
- multiple baselines are retained for comparison:
  - persistence
  - trend only
  - trend plus seasonal harmonics
  - reduced OLS variants
  - detrended OLS with Argo
  - detrended ridge with Argo

### Main hindcast outcome

The retained active Sojs stack is good enough to support limited monthly prediction work for Portland and Bar Harbor, but not a single uninterrupted model run from `2004` forward. The predictor stack has real month-level gaps and the historical GRACE branch ends in `2017`.

## 2. Shared-Model Refactor

### Why the refactor was needed

The original hindcast script fit the final model only inside the evaluation path. That was enough for Phase 4 diagnostics, but not enough for a clean monthly prediction/export pipeline.

To avoid duplicating the same transforms in a separate script, the hindcast code was refactored so the validated final-model fit could be reused directly.

### What was added

In `hindcast_model.py`:

- `FinalModelFit`
  - stores fitted target transforms
  - stores fitted predictor transforms
  - stores ridge coefficients and penalty
  - stores station baseline and GIA reference metadata needed for reconstruction
- `fit_station_final_model(...)`
  - fits the validated final model once
  - returns the reusable fit object
- `predict_with_final_model(...)`
  - applies the stored transforms to new monthly predictor data
- `extrapolate_target_with_final_model(...)`
  - provides the explicit trend-plus-seasonal fallback used for extrapolative months

### Regression check performed

After the refactor:

- `python hindcast_model.py` was rerun
- the original Phase 4 hindcast workflow still completed successfully

## 3. Monthly Projection Strategy Implemented

### Core rule

Sojs does not treat the monthly prediction path as one uninterrupted physical model from `2004` into the future.

Instead, outputs are labeled by regime so downstream users can see whether a given month is:

- observationally constrained by the full retained predictor stack
- supported by a same-family continuation
- or only an extrapolation

### Regime A: constrained reconstruction

Definition:

- months where all validated final-model predictors are present together:
  - Copernicus SLA
  - historical GRACE ocean mass
  - Greenland mass
  - cleaned Argo density

Interpretation:

- best-supported monthly reconstruction regime in the current Sojs stack

### Regime B: validated continuation

Definition:

- months after the historical GRACE branch where the same-family GRACE-FO continuation is available together with the other required predictors

Implementation decision used here:

- GRACE-FO continuation source:
  - `data/grace/grace_ocean_mass_monthly.nc`
- The GRACE-FO grid is reduced to the same Gulf of Maine area-mean mass series used by the historical GRACE workflow.
- The continuation series is standardized to the historical GRACE mean and standard deviation before being inserted into the final-model predictor slot.

Interpretation:

- still a reduced-scope product
- more defensible than silently forward-filling the historical GRACE predictor
- still requires separate validation before strong interpretation

### Regime C: pure extrapolation

Definition:

- months where the full predictor stack is unavailable

Implementation:

- uses the fitted target trend plus fitted monthly seasonal cycle only

Interpretation:

- explicitly extrapolative
- not a model-constrained closure estimate
- useful only as a clearly labeled fallback envelope/path

## 4. Monthly Export Pipeline

### Script

- `predict_monthly.py`

### What the script does

1. Loads the normalized monthly dataset.
2. Loads and reduces the GRACE-FO continuation product.
3. Builds a monthly predictor frame over the available timeline.
4. Labels each month by regime.
5. Reuses the validated final model for each published station.
6. Reconstructs absolute sea level by adding back:
   - the GIA component
   - the station baseline
7. Carries station-specific Phase 4 CV RMSE forward as a constant `+/- 1 sigma` uncertainty band.
8. Exports monthly station products and annual mean summaries.
9. Generates station plots and a prediction summary.

### Published stations

- Portland
- Bar Harbor

### Explicitly not published

- Rockland

Reason:

- the current Sojs retained-modern-overlap definition does not validate a monthly Rockland target window

### Export products

- `data/predictions/sojs_monthly_predictions.csv`
- `data/predictions/sojs_monthly_predictions.nc`
- `data/predictions/sojs_annual_prediction_summary.csv`
- `data/predictions/sojs_prediction_validation_summary.csv`
- `plots/predictions/portland_monthly_prediction.png`
- `plots/predictions/bar_harbor_monthly_prediction.png`
- `plots/predictions/sojs_prediction_summary.md`

## 5. Output Span

- Monthly predictions currently span `2004-07-01` through `2026-03-01`.
- Observed station data available for direct comparison currently span through `2024-12-01`.

The month-to-month regime coverage is not continuous because the retained predictors, especially cleaned Argo support, still contain real gaps.

## 6. Validation Results

### Constrained reconstruction

Observed overlap:

- `2004-07-01` through `2017-06-01`

Bar Harbor:

- RMSE: `0.017775 m`
- MAE: `0.014140 m`
- Bias: approximately `0 m`
- R^2: `0.8608`

Portland:

- RMSE: `0.022987 m`
- MAE: `0.018838 m`
- Bias: approximately `0 m`
- R^2: `0.8188`

Interpretation:

- the validated Phase 4 final model is useful on the constrained overlap window for both published stations

### Validated continuation

Observed overlap in practice:

- `2018-06-01` through `2024-12-01`
- with gaps where the full continuation-era predictor stack is unavailable

Bar Harbor:

- RMSE: `0.031862 m`
- MAE: `0.026165 m`
- Bias: `-0.014800 m`
- R^2: `0.6145`

Portland:

- RMSE: `0.068973 m`
- MAE: `0.057750 m`
- Bias: `0.056957 m`
- R^2: `-0.4452`

Interpretation:

- Bar Harbor continuation is materially better than a blind extrapolation and is at least defensible as a limited validated continuation path.
- Portland continuation is weak in the current retained predictor stack and should not be treated as a strong predictive success.

### Pure extrapolation

Because the extrapolative regime is included in the export product for continuity, it also overlaps some observed months where the full predictor stack is missing.

Observed-period extrapolation skill is weak relative to the constrained-reconstruction regime:

- Bar Harbor:
  - RMSE `0.044905 m`
  - R^2 `0.2119`
- Portland:
  - RMSE `0.060685 m`
  - R^2 `0.0745`

Interpretation:

- this regime should remain clearly labeled as extrapolative support only

## 7. Interpretation Guardrails

Current Sojs monthly outputs should be read as:

- reduced-scope
- observationally constrained where retained predictors exist
- structurally limited by missing atmospheric and land-motion drivers
- not valid for Rockland under the current setup

Additional caution:

- the continuation path is not equally strong across stations
- Portland continuation should be revalidated before being used in any more ambitious projection claims
- future scenario work still requires explicit scenario or predictor assumptions and should not be presented as if it were fully constrained by the retained active observations

## 8. Separate Annual Projection Track

### Why the annual path is separate

`predict_monthly.py` remains the monthly reconstruction/export path. It is useful for constrained monthly reconstruction and regime-aware continuation work, but it is not the right engine for long-horizon projection.

The annual path is separate because:

- the NAO record is much longer than the monthly full-overlap window
- annual aggregation reduces some of the monthly overlap sparsity
- deterministic land-motion metadata can be handled explicitly in annual target space
- a century-scale annual-average method can be built directly from the retained annual trend and trained residual structure without pretending the monthly regime logic should be extrapolated unchanged

### Annual data assembly

`annual_projection_data.py` builds:

- `data/annual/sojs_portland_annual_training.csv`
- `data/annual/sojs_portland_annual_training.nc`
- `plots/annual/portland_annual_coverage.png`

Key annual design rules:

- calendar-year means require at least `9` valid months
- `months_present_<var>` diagnostics are carried for the retained target and predictors
- annual joins include:
  - Portland annual mean sea level
  - Copernicus Gulf of Maine SLA annual mean
  - Greenland mass annual mean
  - annual mean NAO
  - winter DJF NAO
  - previous-year NAO lags
  - deterministic land-motion metadata
- Argo and historical GRACE are intentionally not required annual predictors

### Annual model ladder and backtests

`annual_projection_model.py` fits the following ladder:

- `baseline_trend`
- `trend_plus_nao`
- `trend_plus_nao_plus_sla`
- `trend_plus_nao_plus_sla_plus_greenland`
- `trend_plus_nao_plus_sla_plus_greenland_ridge`

Backtests include:

- rolling-origin 5-year holdouts
- rolling-origin 10-year holdouts
- final contiguous 10-year tail holdout

Current result on the retained Sojs annual table:

- `trend_plus_nao` is the selected annual projection model
- it beats `baseline_trend` on rolling 5-year holdouts
- the shorter SLA and Greenland windows are still useful comparison ladders, but they do not yet beat the longer NAO-based annual fit on the current data volume

### Annual century projections

`project_annual.py` now consumes the fitted annual model, extracts the retained historical annual trend, couples it to the fitted annual-model noise, and writes:

- `data/projections/sojs_portland_annual_projections.csv`
- `data/projections/sojs_portland_annual_projections.nc`
- `plots/projections/portland_annual_projection.png`
- `plots/projections/sojs_annual_projection_summary.md`

The annual summary structure is:

- `baseline`
- `low`
- `high`

The century projection uncertainty widens with lead time using three components:

- extracted annual trend uncertainty from bootstrap/refit spread
- trained residual-noise variability from the selected annual model
- deterministic land-motion reconstruction added back to the simulated adjusted target path

The canonical method reference for the annual path now lives in `docs/annual_projection.md`. That file documents:

- annual training-table schema
- annual backtest schema
- saved-model JSON contents
- century projection algorithm
- current retained metrics and end-of-horizon values

### Land-motion handling in the annual path

`land_motion.py` publishes a Portland-only artifact used by the annual path. It retains:

- GIA metadata rate and uncertainty
- explicit VLM placeholder rate and uncertainty
- combined relative land-motion rate and uncertainty

This stays in deterministic target reconstruction space. It is not treated as a learned annual predictor.

## 9. Rerun Commands

### Hindcast

```powershell
& .\.venv\Scripts\python.exe hindcast_model.py
```

### Monthly prediction export

```powershell
& .\.venv\Scripts\python.exe predict_monthly.py
```

### Annual training table

```powershell
& .\.venv\Scripts\python.exe land_motion.py
& .\.venv\Scripts\python.exe annual_projection_data.py
```

### Annual model and projections

```powershell
& .\.venv\Scripts\python.exe annual_projection_model.py
& .\.venv\Scripts\python.exe project_annual.py
```
