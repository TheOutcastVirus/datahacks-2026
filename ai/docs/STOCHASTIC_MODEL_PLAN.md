# Stochastic SLA Model Plan

## Objective

Extend the long-horizon La Jolla sea-level projection so the autoregressive residual model does not collapse to a fixed point after the observed record ends. The deterministic model in `ai/code/simple_dnn_full_history_wide_projection.py` gives a plausible median path, but it cannot generate realistic inter-annual variability on its own. The stochastic variant should produce an ensemble of future trajectories with uncertainty bands while preserving the existing linear sea-level-rise backbone.

This is no longer a greenfield plan. `ai/code/simple_dnn_stochastic.py` already exists and runs end-to-end. The work now is to harden it, calibrate it, add the missing dashboard layer, and document the remaining risks honestly.

## Current Status

Implemented now:
- `ai/code/simple_dnn_stochastic.py`
- `ai/outputs/plots/simple_dnn_stochastic.png`
- `ai/data/processed/models/sla_prediction_timeseries_stochastic.csv`

Still missing:
- `ai/code/dashboard_stochastic.py`
- `ai/outputs/plots/sla_dashboard_stochastic.html`
- any test or regression check around calibration and CSV schema

## Current Design

The current stochastic model keeps the same feature frame and forecast framing as the deterministic wide-projection model:
- input window: 12 months
- forecast horizon per step: 6 months
- rollout horizon: 50 years
- training split: target dates before `2010-01-01` for train, from `2010-01-01` onward for validation
- features per month:
  - `sla_ma12_detrended`
  - `temp_wide_anomaly`
  - `temp_wide_roll_6`
  - `temp_wide_roll_12`

Architecture:
- dense trunk with 2 hidden layers of width 32 and ReLU activations
- one head predicts `mu`
- one head predicts `log_sigma`
- `log_sigma` is clamped to `[-6, 2]`
- training loss is Gaussian negative log-likelihood on the normalized residual-delta target

Inference:
- run 200 Monte Carlo rollouts
- at each rollout step sample `delta_n = mu + exp(log_sigma) * z`
- denormalize the sampled delta
- reconstruct the new residual state from the sampled delta plus the last residual anchor
- add the historical linear sea-level trend back afterward
- add month-of-year climatology back afterward to get projected MSL

## Latest Run Snapshot

Latest local run in this repo:
- command: `ai\.venv\Scripts\python.exe ai\simple_dnn_stochastic.py`
- run date: April 18, 2026

Observed diagnostics from that run:
- feature frame: 727 months, `1950-02` to `2021-05`
- train windows: 585
- validation windows: 125
- train residual-delta std: `0.0265 m`
- validation RMSE of `mu` on residual-delta: `0.0232 m`
- validation RMSE of `mu` on absolute trend: `0.0232 m`
- validation average predicted sigma: `0.0128 m`
- validation 90% coverage: `0.568`
- minimum 5-year residual std during rollout: `0.0153 m`
- median 50-year MSL rise: `+0.1300 m`
- 5-95% range of final 50-year rise: `[+0.0600, +0.1898] m`

Interpretation:
- the model succeeds at preventing fixed-point collapse
- the median forecast is competitive as a long-horizon residual generator
- the uncertainty estimates are under-dispersed or miscalibrated, because 90% coverage at `0.568` is far below the target band

## Gap Against Intended Acceptance Criteria

Accepted now:
- `simple_dnn_stochastic.py` runs end-to-end
- PNG and CSV are written successfully
- rollout residual variability stays well above the no-collapse floor

Not accepted yet:
- validation 90% coverage target of `0.80` to `0.95` is not met
- `dashboard_stochastic.py` has not been built
- `sla_dashboard_stochastic.html` is not generated

## Phase Plan

## Phase 1: Stabilize And Calibrate The Probabilistic Head

Goal:
- bring interval coverage into a credible range without destroying the useful median path

Primary work:
- inspect whether the current sigma head is systematically too small on validation
- compare train and validation sigma distributions
- log calibration diagnostics beyond one scalar coverage number:
  - 50% coverage
  - 80% coverage
  - 90% coverage
  - average interval width
  - standardized residual histogram or summary
- test whether the problem is mostly scale miscalibration or full distribution mismatch

Priority experiments:
1. Add post-hoc temperature scaling on `sigma` using the validation split or a calibration subset carved from training.
2. Add a minimum sigma floor in raw units at inference and compare coverage / sharpness.
3. Reduce training instability from the late-epoch sigma oscillation now visible in the logs.
4. Compare the current Gaussian NLL against a heteroscedastic Huber-style objective or a fixed-variance-plus-residual-sampling baseline.

Success criteria for this phase:
- 90% validation coverage in the `0.80` to `0.95` band
- average sigma no longer obviously smaller than realized validation errors
- median forecast RMSE remains in the current ballpark instead of regressing sharply

## Phase 2: Build The Missing Dashboard

Goal:
- expose the ensemble fan interactively, parallel to the existing deterministic `ai/code/dashboard.py`

Required file:
- `ai/code/dashboard_stochastic.py`

Required output:
- `ai/outputs/plots/sla_dashboard_stochastic.html`

Dashboard contents:
- panel 1: observed MSL plus stochastic median and 5-95 band
- panel 2: observed deseasonalized SLA plus 12-month moving average and stochastic trend fan
- panel 3: linear trend baseline plus stochastic trend median with 25-75 and 5-95 bands
- bottom range slider
- unified x hover
- explicit observation-end marker

Implementation note:
- the stochastic CSV already includes the percentile columns needed for this
- the dashboard should read the existing schema rather than recomputing anything

## Phase 3: Tighten The Output Contract

Goal:
- make the stochastic artifacts safe to reuse in downstream reporting and dashboards

Tasks:
- lock the CSV schema in the plan and in code comments
- confirm the current extra trend quantile columns stay intentional:
  - `pred_trend_p05`
  - `pred_trend_p25`
  - `pred_trend_p75`
  - `pred_trend_p95`
- add a lightweight verification script or assertions for:
  - monotonic time index
  - expected percentile ordering
  - no future rows missing median predictions
  - observed-only columns remaining null in future rows where appropriate

## Phase 4: Improve Rollout Realism

Goal:
- make the long-horizon ensemble variability more physically defensible

Current limitation:
- future temperature features are zero-filled, which means the only future variability comes from the sampled residual process itself

Candidate upgrades:
- sample future residuals conditioned on a weakly persistent latent state instead of pure one-step Gaussian draws
- add correlated noise across rollout steps instead of independent monthly shocks
- model residual innovations rather than direct deltas if that gives cleaner temporal structure
- test a residual bootstrap baseline against the learned Gaussian head

This phase is lower priority than calibration and the dashboard. The current blocker is not lack of wiggle; it is unreliable uncertainty calibration.

## Implementation Constraints

Keep consistent with the existing repo patterns:
- use `project_paths.py` for path handling
- reuse `build_feature_frame()` and `linear_trend_at()` from `ai/code/simple_dnn_full_history_wide_projection.py`
- do not fork the feature engineering unless a specific experiment requires it
- keep derived tables under `ai/data/processed/models/` and figures under `ai/outputs/plots/`
- seed both NumPy and Torch for reproducibility

## Risks

Main technical risks:
- the sigma head may be learning aleatoric uncertainty poorly because the model class is too small or the target distribution is not close to Gaussian
- using the same validation window both for model selection and any post-hoc calibration can overstate confidence in the fix
- zero-filled future exogenous features may still understate long-range variability even after calibration
- a sharper ensemble can look visually better while remaining statistically wrong, so diagnostics have to drive decisions

## Concrete Next Actions

1. Add coverage and interval-width diagnostics directly to `ai/code/simple_dnn_stochastic.py`.
2. Implement one calibration pass for sigma scaling and rerun the stochastic script.
3. Build `ai/code/dashboard_stochastic.py` against the current stochastic CSV schema.
4. Regenerate `ai/outputs/plots/sla_dashboard_stochastic.html`.
5. Update `ai/docs/PROJECT_REPORT.md` only after the stochastic calibration story is good enough to state cleanly.

## Definition Of Done

This stochastic extension is complete when all of the following are true:
- `ai/code/simple_dnn_stochastic.py` runs cleanly from the repo environment
- `ai/data/processed/models/sla_prediction_timeseries_stochastic.csv` and `ai/outputs/plots/simple_dnn_stochastic.png` regenerate successfully
- validation 90% coverage lands in the planned target range
- rollout residual variability remains above the anti-collapse floor across the full 50-year horizon
- `ai/code/dashboard_stochastic.py` writes `ai/outputs/plots/sla_dashboard_stochastic.html`
- the plan and report reflect the actual observed metrics, not aspirational ones


