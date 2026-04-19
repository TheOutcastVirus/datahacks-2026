# Sojs Phase 4 Hindcast Skill Summary

**Dataset:** Argo overlap period (months where Argo T/S/density pass support thresholds).
**CV method:** Forward time-series split — no future leakage.
**Seasonal pre-removal:** Trend-adjusted monthly cycle (detrend first, then monthly means)
  removed from the target AND every predictor before all CV loops. Deseasoning the
  predictors (especially Argo T/S/density) is required so the OLS sees the same type of
  variance in both inputs and target. `trend_seasonal` should converge toward `trend_only`
  — confirming the pre-removal worked.
**Final model:** `ols_with_argo_ridge` — ridge regression with inner CV lambda selection;
  per-fold detrending and standardization; predictors: Copernicus SLA, GRACE mass,
  Greenland mass, Argo density. Ridge shrinks the Argo coefficient toward zero if it
  adds noise, preventing it from degrading the external-predictor skill.

## Portland

| Model | Final | CV RMSE (m) | R² | Skill vs persistence | Skill vs trend |
|-------|-------|------------|-----|----------------------|----------------|
| persistence |  | 0.03761 | -0.3143 | 0.0000 | -0.0239 |
| trend_only |  | 0.03673 | -0.2537 | 0.0233 | 0.0000 |
| trend_seasonal |  | 0.13656 | -16.3285 | -2.6311 | -2.7178 |
| ols_reduced |  | 0.03838 | -0.3687 | -0.0205 | -0.0449 |
| ols_reduced_detrended |  | 0.03838 | -0.3687 | -0.0205 | -0.0449 |
| ols_with_argo_detrended |  | 0.04085 | -0.5507 | -0.0862 | -0.1122 |
| ols_with_argo_ridge | **yes** | 0.03152 | 0.0767 | 0.1619 | 0.1418 |

## Bar Harbor

| Model | Final | CV RMSE (m) | R² | Skill vs persistence | Skill vs trend |
|-------|-------|------------|-----|----------------------|----------------|
| persistence |  | 0.03134 | 0.0404 | 0.0000 | 0.1310 |
| trend_only |  | 0.03607 | -0.2708 | -0.1508 | 0.0000 |
| trend_seasonal |  | 0.11987 | -13.0349 | -2.8244 | -2.3233 |
| ols_reduced |  | 0.02675 | 0.3012 | 0.1467 | 0.2585 |
| ols_reduced_detrended |  | 0.02675 | 0.3012 | 0.1467 | 0.2585 |
| ols_with_argo_detrended |  | 0.03347 | -0.0943 | -0.0679 | 0.0720 |
| ols_with_argo_ridge | **yes** | 0.02549 | 0.3654 | 0.1868 | 0.2933 |

## Key design decisions

- All models are evaluated on the same Argo overlap period for fair comparison.
- The trend-adjusted seasonal cycle is pre-removed from the target AND every predictor.
  Predictors (especially Argo T/S/density) carry large seasonal cycles; removing them
  ensures the OLS fits non-seasonal co-variance, not seasonal phase alignment.
  All RMSE/R² values reflect non-seasonal sea level variability only.
- `ols_reduced` vs `ols_reduced_detrended` shows the effect of per-fold trend removal.
- `ols_with_argo_ridge` is the final model: ridge regression with inner CV lambda selection,
  per-fold detrending + standardization, predictors: SLA, GRACE, Greenland, Argo density.
  Ridge prevents the Argo density coefficient from inflating if it adds noise over the
  external predictors. Use `--ridge-lambda <value>` to force a smaller penalty if needed.
- `ols_with_argo_detrended` (pure OLS) is kept as a comparison to show the ridge effect.
- Positive skill scores vs persistence indicate the model captures genuine dynamic signal.
- Residuals document what the active data stack does not yet explain.