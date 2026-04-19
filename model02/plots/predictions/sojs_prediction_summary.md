# Sojs Monthly Prediction Summary

**Final model:** `ols_with_argo_ridge`
**Scope:** Portland and Bar Harbor only. Rockland is intentionally excluded.
**Uncertainty:** station-specific Phase 4 cross-validation RMSE carried forward as a constant +/- 1 sigma band.

## Regime windows

- `constrained_reconstruction`: 2004-07 to 2004-07
- `pure_extrapolation`: 2004-08 to 2005-02
- `constrained_reconstruction`: 2005-03 to 2005-03
- `pure_extrapolation`: 2005-04 to 2010-09
- `constrained_reconstruction`: 2010-10 to 2010-10
- `pure_extrapolation`: 2010-11 to 2011-06
- `constrained_reconstruction`: 2011-07 to 2011-07
- `pure_extrapolation`: 2011-08 to 2011-12
- `constrained_reconstruction`: 2012-01 to 2012-02
- `pure_extrapolation`: 2012-03 to 2013-04
- `constrained_reconstruction`: 2013-05 to 2013-07
- `pure_extrapolation`: 2013-08 to 2013-09
- `constrained_reconstruction`: 2013-10 to 2014-01
- `pure_extrapolation`: 2014-02 to 2014-04
- `constrained_reconstruction`: 2014-05 to 2014-06
- `pure_extrapolation`: 2014-07 to 2014-07
- `constrained_reconstruction`: 2014-08 to 2014-11
- `pure_extrapolation`: 2014-12 to 2014-12
- `constrained_reconstruction`: 2015-01 to 2015-04
- `pure_extrapolation`: 2015-05 to 2015-06
- `constrained_reconstruction`: 2015-07 to 2015-09
- `pure_extrapolation`: 2015-10 to 2015-11
- `constrained_reconstruction`: 2015-12 to 2016-03
- `pure_extrapolation`: 2016-04 to 2016-04
- `constrained_reconstruction`: 2016-05 to 2016-08
- `pure_extrapolation`: 2016-09 to 2016-10
- `constrained_reconstruction`: 2016-11 to 2017-01
- `pure_extrapolation`: 2017-02 to 2017-03
- `constrained_reconstruction`: 2017-04 to 2017-06
- `pure_extrapolation`: 2017-07 to 2018-05
- `validated_continuation`: 2018-06 to 2018-07
- `pure_extrapolation`: 2018-08 to 2018-09
- `validated_continuation`: 2018-10 to 2021-11
- `pure_extrapolation`: 2021-12 to 2021-12
- `validated_continuation`: 2022-01 to 2024-09
- `pure_extrapolation`: 2024-10 to 2024-10
- `validated_continuation`: 2024-11 to 2024-12
- `pure_extrapolation`: 2025-01 to 2026-03

## Observed-period validation

| Station | Regime | Months | RMSE (m) | MAE (m) | Bias (m) | R^2 |
|---------|--------|--------|----------|---------|----------|-----|
| Bar Harbor | constrained_reconstruction | 40 | 0.01777 | 0.01414 | -0.00000 | 0.8608 |
| Bar Harbor | pure_extrapolation | 129 | 0.04491 | 0.03225 | 0.00789 | 0.2119 |
| Bar Harbor | validated_continuation | 74 | 0.03186 | 0.02617 | -0.01480 | 0.6145 |
| Portland | constrained_reconstruction | 40 | 0.02299 | 0.01884 | -0.00000 | 0.8188 |
| Portland | pure_extrapolation | 131 | 0.06068 | 0.04544 | 0.00726 | 0.0745 |
| Portland | validated_continuation | 75 | 0.06897 | 0.05775 | 0.05696 | -0.4452 |

## Notes

- Regime A is observationally constrained by the full validated predictor stack.
- Regime B keeps Argo in the final model and swaps in GRACE-FO as the same-family ocean-mass continuation.
- Regime C is explicitly extrapolative and should not be interpreted as a model-constrained closure estimate.