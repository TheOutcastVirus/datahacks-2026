# Sojs Annual Projection Track

## Purpose

This document is the canonical reference for the Portland annual projection workflow in Sojs.

It exists to keep the long-horizon annual-average projection method separate from the monthly reconstruction/export workflow in `predict_monthly.py`.

The annual track answers a different question from the monthly path:

- the monthly path reconstructs and exports supported monthly values under explicit predictor-availability regimes
- the annual path projects the next century of Portland annual-average sea level using an extracted historical annual trend coupled to noise learned from the fitted annual model

## Scope

Current scope is intentionally narrow:

- station: Portland only
- target: annual-average relative sea level
- cadence: calendar-year annual means
- horizon: next century by default
- projection style: trend plus trained annual-model noise

Current scope explicitly excludes:

- Rockland annual projections
- Bar Harbor annual projections
- direct use of Argo as a required annual predictor
- direct use of historical GRACE as a required annual predictor
- monthly-to-future physical-driver scenario extrapolation inside the annual script

## File Map

The annual track is implemented by four scripts:

1. `land_motion.py`
   - writes the Portland land-motion metadata artifact
2. `annual_projection_data.py`
   - annualizes the retained monthly Sojs stack
   - joins annual and winter DJF NAO features
   - attaches land-motion metadata
3. `annual_projection_model.py`
   - fits the annual model ladder
   - runs rolling 5-year and 10-year backtests
   - runs the final contiguous 10-year tail holdout
   - saves the selected annual model and fitted metadata
4. `project_annual.py`
   - loads the selected annual model JSON
   - extracts the historical annual trend from retained training data
   - estimates the trained residual-noise structure from the fitted annual model
   - simulates century-scale annual-average trajectories
   - writes summary paths and uncertainty bands

## Inputs

### Source datasets

The annual training table is built from:

- `data/normalized/sojs_active_monthly_normalized.nc`
- `data/nao/nao_monthly.nc`
- `data/land_motion/portland_land_motion.nc`

### Why these inputs were chosen

The annual path favors predictors with longer historical annual support:

- Portland annual means provide the target
- NAO provides the longest retained annual climate-driver family
- Copernicus SLA adds shorter-window annual ocean-context information
- Greenland mass adds shorter-window annual cryosphere context
- land motion is handled explicitly as deterministic metadata in target space

Argo and historical GRACE are not required annual predictors because their overlap is too short to be the backbone of a century-scale annual-average projection workflow.

## Annual Training Table

### Output files

`annual_projection_data.py` writes:

- `data/annual/sojs_portland_annual_training.csv`
- `data/annual/sojs_portland_annual_training.nc`
- `plots/annual/portland_annual_coverage.png`

### Coverage rules

Calendar-year annual means require at least `9` valid months for a series to be accepted in a given year.

The annual table carries `months_present_<var>` diagnostics so the projection path can distinguish between:

- true annual support
- sparse annual support
- complete absence of a predictor in a year

### Column schema

The current annual training table contains:

- `year`
- `months_present_portland_msl_m`
- `portland_msl_m`
- `months_present_copernicus_sla_gom_m`
- `copernicus_sla_gom_m`
- `months_present_greenland_mass_gt`
- `greenland_mass_gt`
- `portland_msl_m_anomaly`
- `months_present_nao_annual_mean`
- `nao_annual_mean`
- `months_present_nao_winter_djf`
- `nao_winter_djf`
- `nao_annual_mean_prev_year`
- `nao_winter_djf_prev_year`
- `months_present_nao_annual_mean_prev_year`
- `months_present_nao_winter_djf_prev_year`
- `gia_metadata_mm_yr`
- `gia_sigma_mm_yr`
- `vlm_mm_yr`
- `vlm_sigma_mm_yr`
- `relative_land_motion_mm_yr`
- `relative_land_motion_sigma_mm_yr`
- `land_motion_kind`
- `land_motion_source`
- `land_motion_adjustment_m`
- `portland_target_adjusted_m`

### Column roles

The most important annual-table fields are:

- `portland_msl_m`
  - observed annual-average Portland relative sea level
- `portland_msl_m_anomaly`
  - annual Portland anomaly relative to the retained Portland annual mean
- `portland_target_adjusted_m`
  - annual Portland anomaly after deterministic land-motion adjustment
  - this is the model target used by the annual model ladder
- `nao_annual_mean`
  - annual mean NAO
- `nao_winter_djf`
  - winter DJF NAO aligned to winter year
- `nao_annual_mean_prev_year`
  - previous-year annual NAO lag
- `nao_winter_djf_prev_year`
  - previous winter DJF NAO lag
- `land_motion_adjustment_m`
  - deterministic annual target-space adjustment derived from the Portland land-motion artifact

### Current retained coverage

On the current Sojs artifacts:

- annual table span: `1912` to `2026`
- Portland annual target support: `113` years
- annual mean NAO support: `76` years
- winter DJF NAO support: `77` years
- Copernicus annual SLA support: `32` years
- Greenland annual support: `19` years

Those support differences explain why the selected annual model is NAO-based rather than SLA- or Greenland-based on the current retained data volume.

## Land Motion

### Why land motion is explicit

The annual path does not silently pretend that fixed literature GIA is the entire land-motion story.

Instead, `land_motion.py` publishes an explicit single-site artifact for Portland with:

- GIA metadata rate and uncertainty
- VLM placeholder rate and uncertainty
- combined relative land-motion rate and uncertainty
- source metadata
- land-motion type metadata

### Land-motion role in modeling

Land motion is not learned as a predictor.

Instead:

1. a deterministic annual land-motion adjustment is constructed
2. that adjustment is removed from Portland annual anomalies to form the model target
3. land motion is added back after projection when reconstructing annual absolute values

This design reduces the risk of overfitting a short annual predictor record with noisy land-motion terms.

## Annual Model Ladder

### Candidate models

`annual_projection_model.py` fits the following ladder:

- `baseline_trend`
- `trend_plus_nao`
- `trend_plus_nao_plus_sla`
- `trend_plus_nao_plus_sla_plus_greenland`
- `trend_plus_nao_plus_sla_plus_greenland_ridge`

### Selection rule

The selected model is chosen from the eligible annual projection models by backtest performance, while keeping `baseline_trend` as the baseline comparison.

The current selected model is:

- `trend_plus_nao`

### Why `trend_plus_nao` wins right now

On the retained annual table:

- NAO has the longest useful annual support after Portland
- Copernicus SLA is much shorter
- Greenland mass is shorter still
- the shortest-window annual models do not generalize as well in rolling holdouts

### Backtest design

The annual model ladder is validated with:

- rolling-origin 5-year holdouts
- rolling-origin 10-year holdouts
- final contiguous 10-year tail holdout

The backtest output file is:

- `data/annual/sojs_portland_annual_backtest.csv`

Its columns are:

- `model`
- `evaluation`
- `horizon_years`
- `split_index`
- `train_start_year`
- `train_end_year`
- `test_start_year`
- `test_end_year`
- `train_years`
- `test_years`
- `ridge_lambda`
- `rmse_m`
- `mae_m`
- `bias_m`
- `trend_error_m_per_year`
- `interval_coverage_80`

### Current backtest summary

The current annual model summary is written to:

- `plots/annual/sojs_annual_model_summary.md`

Current ladder result:

| Model | Years | Start | End | Mean RMSE 5y | Mean RMSE 10y | Tail RMSE 10y | Mean 80% coverage |
|-------|------:|------:|----:|-------------:|--------------:|--------------:|------------------:|
| `trend_plus_nao` | 74 | 1951 | 2024 | 0.03746 | 0.04121 | 0.03665 | 0.633 |
| `trend_plus_nao_plus_sla` | 31 | 1994 | 2024 | 0.04856 | 0.05012 | 0.07682 | 0.262 |
| `baseline_trend` | 113 | 1912 | 2024 | 0.04871 | 0.05369 | 0.04122 | 0.478 |
| `trend_plus_nao_plus_sla_plus_greenland_ridge` | 18 | 2003 | 2024 | 0.05125 | n/a | n/a | 0.000 |
| `trend_plus_nao_plus_sla_plus_greenland` | 18 | 2003 | 2024 | 0.09307 | n/a | n/a | 0.000 |

The key result is:

- `trend_plus_nao` beats `baseline_trend` on rolling 5-year holdouts

That is the main justification for carrying this annual method forward.

## Saved Annual Model

### Output file

`annual_projection_model.py` saves:

- `data/annual/sojs_portland_annual_model.json`

### Why the JSON exists

The JSON is the bridge between annual model fitting and annual projection.

It stores not just the selected coefficients, but also the metadata required to reconstruct:

- target-space trend
- trained residual noise
- bootstrap uncertainty in the fitted trend component
- land-motion adjustment metadata
- baseline absolute reconstruction level

### JSON keys

The current JSON includes:

- `model_name`
- `predictors`
- `use_ridge`
- `ridge_lambda`
- `origin_year`
- `coefficients`
- `predictor_means`
- `predictor_stds`
- `residual_sigma_m`
- `target_baseline_m`
- `relative_land_motion_mm_yr`
- `relative_land_motion_sigma_mm_yr`
- `land_motion_reference_year`
- `land_motion_reference_mean_m`
- `land_motion_kind`
- `land_motion_source`
- `train_years`
- `training_target_adjusted_m`
- `training_fitted_adjusted_m`
- `training_residuals_m`
- `observed_target_trend_slope_m_per_year`
- `observed_target_trend_intercept_m`
- `bootstrap_coefficients`

### Why the stored residuals matter

The century projection does not just extrapolate a line.

It uses:

- the extracted annual target trend
- the residual structure from the fitted annual model

That means the stored residuals are part of the projection method itself, not just diagnostic leftovers.

## Century Projection Method

### Output files

`project_annual.py` writes:

- `data/projections/sojs_portland_annual_projections.csv`
- `data/projections/sojs_portland_annual_projections.nc`
- `plots/projections/portland_annual_projection.png`
- `plots/projections/sojs_annual_projection_summary.md`

### Default settings

The current default century projection uses:

- horizon: `100` years
- simulation count: `4000`
- summary paths:
  - `low`
  - `baseline`
  - `high`

### What the script actually does

`project_annual.py` works in adjusted-target space first, then reconstructs annual absolute values.

The method is:

1. load the selected annual model JSON
2. read the stored observed annual target trend
3. sample bootstrap coefficient sets to represent trend uncertainty
4. estimate residual-noise structure from the training residuals
5. fit a simple AR(1)-style persistence term from those residuals
6. simulate future annual adjusted-target noise paths
7. add the deterministic annual trend component to each simulated noise path
8. add back deterministic land motion
9. add back the Portland annual baseline level
10. summarize the simulated annual-average absolute paths into:
   - `low`
   - `baseline`
   - `high`
   - an 80% interval

### Summary-path interpretation

The summary paths are not separate physical scenarios with different exogenous drivers.

They are summaries of the simulated distribution:

- `low`
  - 25th percentile of simulated annual absolute values
- `baseline`
  - simulation mean
- `high`
  - 75th percentile of simulated annual absolute values

The uncertainty band is wider than the gap between those summary paths because it uses an 80% interval from the full simulated distribution.

### Projection output schema

The current projection CSV contains:

- `scenario`
- `year`
- `predicted_m`
- `predicted_median_m`
- `predicted_lower_80_m`
- `predicted_upper_80_m`
- `total_sigma_m`

Field meanings:

- `scenario`
  - summary path label: `low`, `baseline`, or `high`
- `predicted_m`
  - summary-path annual absolute value for that year
- `predicted_median_m`
  - simulated annual median across all paths
- `predicted_lower_80_m`
  - lower edge of the 80% simulated interval
- `predicted_upper_80_m`
  - upper edge of the 80% simulated interval
- `total_sigma_m`
  - standard deviation of the simulated annual absolute distribution for that year

## Current Century Projection

### Current projection span

The current generated projection spans:

- `2027` to `2126`

### Current projection diagnostics

From the current generated summary:

- projection model noise source: `trend_plus_nao`
- simulation count: `4000`
- adjusted-target trend slope: `0.002863 m/year`
- learned residual AR(1) coefficient: `0.589`
- training residual sigma: `0.03140 m`

### Current end-of-horizon values

For `2126`, the generated annual-average summary values are:

| Summary path | Projected sea level (m) | 80% lower (m) | 80% upper (m) |
|-------------|-------------------------:|--------------:|--------------:|
| `low` | 0.2485 | 0.2235 | 0.3292 |
| `baseline` | 0.2763 | 0.2235 | 0.3292 |
| `high` | 0.3031 | 0.2235 | 0.3292 |

These are annual-average values under the retained Sojs annual method. They should not be read as externally forced climate scenarios.

## Interpretation

### What this annual projection is

This projection is:

- a century-scale annual-average projection
- based on Portland historical annual behavior
- informed by the selected annual model's trained residual structure
- explicit about deterministic land-motion handling

### What this annual projection is not

This projection is not:

- a monthly projection
- a physically closed sea-level budget
- a climate-scenario ensemble driven by explicit future forcing pathways
- a station-general result for all of coastal Maine

## Limitations

The main limitations are:

- Portland-only annual scope
- annual model selection is still constrained by uneven predictor coverage
- the selected projection is NAO-based because the longer annual record dominates, not because the shorter families are physically irrelevant
- land motion is still first-pass deterministic metadata
- the century projection depends on the historical annual trend continuing in a useful way
- residual-noise simulation is intentionally simple and should not be overinterpreted as a full process model

## Rerun Steps

To regenerate the full annual workflow:

```powershell
& .\.venv\Scripts\python.exe land_motion.py
& .\.venv\Scripts\python.exe annual_projection_data.py
& .\.venv\Scripts\python.exe annual_projection_model.py
& .\.venv\Scripts\python.exe project_annual.py
```

## Related Docs

For surrounding context, see:

- `docs/data_collection.md`
- `docs/modeling_and_projection.md`
- `plan.md`
