# Sojs Annual Model Summary

**Selected annual projection model:** `trend_plus_nao`
**Target:** Portland annual mean relative sea level with deterministic land-motion adjustment applied in target space.
**Prediction interval:** 80% Gaussian band using in-sample residual sigma for backtest coverage.

## Model ladder summary

| Model | Years | Start | End | Mean RMSE 5y | Mean RMSE 10y | Tail RMSE 10y | Mean 80% coverage |
|-------|------:|------:|----:|-------------:|--------------:|--------------:|------------------:|
| trend_plus_nao | 74 | 1951 | 2024 | 0.03746 | 0.04121 | 0.03665 | 0.633 |
| trend_plus_nao_plus_sla | 31 | 1994 | 2024 | 0.04856 | 0.05012 | 0.07682 | 0.262 |
| baseline_trend | 113 | 1912 | 2024 | 0.04871 | 0.05369 | 0.04122 | 0.478 |
| trend_plus_nao_plus_sla_plus_greenland_ridge | 18 | 2003 | 2024 | 0.05125 | nan | nan | 0.000 |
| trend_plus_nao_plus_sla_plus_greenland | 18 | 2003 | 2024 | 0.09307 | nan | nan | 0.000 |

## Readout

- Trend-only beaten on rolling 5-year holdouts: yes
- Trend-only 5-year mean RMSE: 0.04871
- Selected-model 5-year mean RMSE: 0.03746
- Rolling-origin evaluation includes both 5-year and 10-year holdouts plus a final contiguous 10-year tail holdout.
- NAO joins provide the long historical annual driver family. Copernicus SLA and Greenland mass only enter where their annual coverage supports them.