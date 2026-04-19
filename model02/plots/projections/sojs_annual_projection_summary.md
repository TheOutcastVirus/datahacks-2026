# Sojs Annual Projection Summary

**Projection model noise source:** `trend_plus_nao`
**Projection years:** 2027 to 2126
**Projection method:** extracted historical trend plus trained noise simulation (`4000` paths).
**Summary paths:** low = 25th percentile, baseline = simulation mean, high = 75th percentile.

## End-of-horizon readout

| Summary path | Final year | Projected sea level (m) | 80% lower (m) | 80% upper (m) |
|--------------|-----------:|------------------------:|--------------:|--------------:|
| low | 2126 | 0.2485 | 0.2235 | 0.3292 |
| baseline | 2126 | 0.2763 | 0.2235 | 0.3292 |
| high | 2126 | 0.3031 | 0.2235 | 0.3292 |

## Notes

- Historical trend slope used in adjusted-target space: 0.002863 m/year.
- Learned noise AR(1) coefficient: 0.589.
- Training noise sigma from model residuals: 0.03140 m.
- Land motion is added back deterministically after simulating the adjusted annual target path.
- The projection is annual-average only and extends the next century from the retained historical trend rather than extrapolating exogenous driver scenarios.