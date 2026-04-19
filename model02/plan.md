# Sojs Maine Coastal Sea Level Prediction Plan
## Penobscot Bay · Muscongus Bay · Rockland Harbor

> **Goal:** Build a regional sea-level prediction workflow for coastal Maine, focused on Penobscot Bay, Muscongus Bay, and Rockland Harbor, using a narrower and explicit data stack than the original full research concept.

> **Scope update (April 2026):** Sojs has completed data collection for NOAA CO-OPS tide gauges, Copernicus Marine Gulf of Maine SLA/ADT, PO.DAAC historical GRACE ocean mass, the PO.DAAC Greenland mass time series, CPC monthly NAO, a cleaned Argo monthly shelf-context cube, and a first-pass Portland land-motion metadata artifact. Those are the active datasets in scope. Other candidate sources from the original concept remain optional future extensions and are not current project dependencies.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Study Area](#2-study-area)
3. [Active Data Stack](#3-active-data-stack)
4. [Deferred Data Sources](#4-deferred-data-sources)
5. [Preprocessing and QC](#5-preprocessing-and-qc)
6. [Feature Assembly](#6-feature-assembly)
7. [Modeling Strategy](#7-modeling-strategy)
8. [Budget Closure](#8-budget-closure)
9. [Projection Strategy](#9-projection-strategy)
10. [Uncertainty](#10-uncertainty)
11. [Validation](#11-validation)
12. [Deliverables](#12-deliverables)
13. [Tools and Runtime](#13-tools-and-runtime)
14. [Timeline](#14-timeline)

---

## 1. Project Overview

### 1.1 Working equation

Relative sea level at a Maine coastal point is still framed as:

```text
ΔRSL = ΔSL_thermo + ΔSL_halo + ΔSL_mass + ΔGIA + ΔVLM_local + ΔSL_dynamic
```

That framing remains useful, but the implemented Sojs workflow does **not** currently have all terms directly observed. The active plan is therefore:

- use the collected datasets to establish a defensible observed baseline
- quantify the overlap between tide gauges, altimetry, and mass-related terms
- determine which terms can be estimated directly from the active data stack
- defer unsupported terms until additional datasets are explicitly added

### 1.2 Current modeling posture

The original plan assumed a much broader forcing inventory, including floats, NERACOOS, NAO, ERA5, AMOC, GIA grids, and InSAR. Only a subset of that broader concept is implemented today, so Sojs should still proceed as a reduced-scope observational modeling effort first, rather than pretending the full budget is already supported.

### 1.3 Target outputs

- station-level historical diagnostics centered on Rockland, Portland, and Bar Harbor
- a reconciled monthly analysis dataset built from the retained active sources
- monthly reconstruction-ready model inputs for relative sea-level analysis
- monthly reconstruction/export products for stations that have validated modern overlap support
- a separate annual training, backtest, and scenario-projection track for Portland
- projections only after the reduced-stack model is stable, validated, and honest about predictor availability

---

## 2. Study Area

### 2.1 Geographic bounds

```text
Primary study domain:
  Latitude:  43.5°N - 44.5°N
  Longitude: 69.8°W - 68.8°W

Extended Gulf of Maine forcing domain:
  Latitude:  41°N - 48°N
  Longitude: 72°W - 64°W
```

### 2.2 Key stations

| Location | Role | NOAA Station ID |
|----------|------|-----------------|
| Rockland Harbor | Primary target station | 8415490 |
| Portland, ME | Long-term reference | 8418150 |
| Bar Harbor, ME | Northern reference | 8413320 |

Eastport remains a possible future reference station, but it is not part of the current retained CO-OPS stack.

---

## 3. Active Data Stack

This section reflects what Sojs actually collected and normalized. Operational details live in `docs/data_collection.md`.

### 3.1 NOAA CO-OPS tide gauges

**Status:** Active and complete

**Retained stations:**
- Rockland
- Portland
- Bar Harbor

**What was produced:**
- one NetCDF file per retained station in `data/coops`
- time-series and comparison plots in `plots/coops`
- summary CSV diagnostics

**Current use in plan:**
- anchor historical relative sea-level behavior
- station-to-station comparison
- candidate model targets

### 3.2 Copernicus Marine SLA and ADT

**Status:** Active and complete

**Retained variables:**
- `sla`
- `adt`

**Domain:**
- Gulf of Maine regional subset

**What was produced:**
- normalized NetCDF in `data/copernicusmarine`
- mean maps, standard deviation maps, area-mean time series, and summary CSV in `plots/copernicusmarine`

**Current use in plan:**
- regional open-ocean and shelf sea-level context
- comparison against tide-gauge variability
- candidate dynamic/altimetric reference series

### 3.3 Historical GRACE ocean mass

**Status:** Active and complete

**Collection used:**
- `TELLUS_GRAC_L3_CSR_RL06_OCN_v04`

**What was produced:**
- combined NetCDF in `data/grace_grac_ocn`
- Gulf of Maine diagnostics in `plots/grace_grac_ocn`

**Current use in plan:**
- mass-related contribution context over the historical overlap period
- broad budget-reconciliation term

### 3.4 Greenland mass time series

**Status:** Active and complete

**Collection used:**
- `GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4`

**What was produced:**
- NetCDF time series in `data/greenland_mass`
- monthly and annual summaries in `plots/greenland_mass`

**Current use in plan:**
- Greenland mass-loss context
- long-term fingerprint-related interpretation
- external forcing/reference series, not yet a direct station-scale predictor by itself

### 3.5 Argo NW Atlantic shelf context

**Status:** Active and complete

**Retained variables:**
- monthly temperature
- monthly salinity
- monthly density
- monthly support diagnostics

**Domain:**
- NW Atlantic shelf context cube with cleaned monthly shelf-context reductions used in the normalized join

**What was produced:**
- monthly NetCDF cube in `data/sojs_argo_monthly_density_1950_present.nc`
- derived shelf-context joined variables in `data/normalized`
- diagnostics and plots in `plots/argo`

**Current use in plan:**
- ocean-interior thermohaline context
- candidate steric-related predictor family
- joined monthly feature context with explicit support filtering before normalization

### 3.6 CPC monthly NAO

**Status:** Active and complete

**What was produced:**
- monthly NAO artifacts in `data/nao`
- annual and winter DJF diagnostics in `plots/nao`

**Current use in plan:**
- first annual climate-driver family
- annual mean and winter DJF joins for the Portland annual projection track

### 3.7 Portland land-motion metadata

**Status:** Active first pass

**What was produced:**
- deterministic Portland metadata artifact in `data/land_motion`
- Portland summary CSV in `plots/land_motion`

**Current use in plan:**
- explicit deterministic target adjustment in the annual model and projection path
- clear separation between GIA metadata, placeholder VLM, and combined relative land motion

---

## 4. Deferred Data Sources

These were part of the original concept but were **not** collected in the current Sojs workflow. They are optional future expansions, not hidden assumptions:

- proprietary float archive
- NERACOOS buoys
- RAPID / AMOC transport products
- ERA5 atmospheric reanalysis
- gridded GIA products
- InSAR vertical land motion
- World Ocean Atlas climatology
- PSMSL extension workflow
- coastal altimetry retracking products

If any of these are brought back in, they should be added intentionally and documented as a scope change in both `plan.md` and `docs/data_collection.md`.

---

## 5. Preprocessing and QC

### 5.1 Required preprocessing

- align retained datasets to a common monthly time base
- harmonize units and metadata
- define overlap windows across tide gauges, altimetry, and mass products
- clean Argo monthly context series with explicit support thresholds before joining
- identify variables used for modeling versus diagnostics-only

### 5.2 QC priorities

- confirm station coverage and gaps for the three retained CO-OPS stations
- verify Copernicus coastal-grid limitations are handled explicitly
- verify GRACE coverage windows before using mass terms in overlap analyses
- keep Greenland mass as a large-scale explanatory series, not a direct local measurement
- retain Argo context only where regional support passes explicit minimum sample and grid-cell thresholds

### 5.3 Data exclusion rules

Before feature assembly, Sojs should explicitly label each retained dataset as one of:

- `model_input`
- `reference_context`
- `diagnostic_only`

This avoids the current ambiguity where collected data is assumed to be used just because it exists on disk.

---

## 6. Feature Assembly

### 6.1 Reduced active feature set

The first Sojs feature matrix should be built only from the active collected stack:

- tide-gauge monthly mean levels
- regional Copernicus `sla` / `adt` summaries
- historical GRACE mass summaries over overlapping periods
- Greenland mass anomaly summaries
- cleaned Argo monthly temperature / salinity / density shelf-context summaries

### 6.2 Station framing

Initial analysis should center on:

- Portland for the longest historical context
- Rockland as the primary target station
- Bar Harbor as a northern comparison station

### 6.3 Fixed metadata allowed

Approximate literature-based GIA rates may still be used as fixed metadata if needed, but Sojs should not claim to have ingested a gridded GIA product unless that workflow is actually implemented.

---

## 7. Modeling Strategy

### 7.1 Near-term strategy

Do not assume the original full multi-source architecture is justified yet. The current modeling path should be:

1. Build a reduced observational baseline model.
2. Test whether the retained data stack has predictive value for station-scale sea level.
3. Add deferred datasets only if they are required to close a demonstrated gap.

### 7.2 Candidate model layers

- baseline trend and seasonal decomposition
- reduced multivariate monthly model using active predictors
- separate annual model ladder for Portland long-horizon behavior
- optional station-specific residual modeling if the reduced stack shows signal

### 7.3 What is explicitly deferred

- LSTM or deep sequence models
- AMOC-driven process modeling
- float-derived OHC architecture
- buoy-resolved thermosteric and halosteric decomposition

### 7.4 Current active final model

Phase 4 established a current active monthly model for the supported Argo-overlap window:

- final model: `ols_with_argo_ridge`
- validated stations: Portland and Bar Harbor
- predictors: Copernicus Gulf of Maine SLA, historical GRACE ocean mass, Greenland mass, and Argo shelf-density context
- preprocessing: GIA metadata adjustment, trend-adjusted deseasoning, per-fold detrending, and within-fold standardization
- Rockland is **not** in the active training window because the retained CO-OPS record ends in 1987 and has zero months in the modern overlap dataset

Those ideas may still be worthwhile later, but they are not justified as current requirements.

---

## 8. Budget Closure

### 8.1 Current budget goal

The budget-closure exercise should be framed as a **reduced observational reconciliation**, not a complete physical closure.

### 8.2 Initial closure terms

Expected initial comparison:

```text
Observed gauge variation
≈ regional altimetric context
+ broad mass-related context
- fixed GIA metadata adjustment
+ residual
```

### 8.3 Required outputs

- Portland reduced-budget check
- Rockland reduced-budget check
- Bar Harbor reduced-budget check
- explicit residual series and written interpretation of what is still missing

---

## 9. Projection Strategy

### 9.1 Active split between monthly and annual work

- The monthly Phase 4 hindcast supports limited monthly reconstruction/export work for Portland and Bar Harbor because `ols_with_argo_ridge` beats both persistence and trend baselines on the supported Argo-overlap months.
- `predict_monthly.py` remains the monthly reconstruction/export path. It is not the long-horizon projection engine.
- Long-horizon projection work now uses a separate Portland annual track:
  - `annual_projection_data.py`
  - `annual_projection_model.py`
  - `project_annual.py`
- This split is deliberate because the monthly predictor stack has regime changes and sparse overlap, while the annual path can exploit the longer NAO record.
- Rockland remains outside the validated monthly modeling window until a modern target series is added deliberately.

### 9.2 Prediction regimes

Sojs should treat long-horizon monthly prediction as three linked regimes instead of one uninterrupted model:

- **Regime A - constrained reconstruction:** Use the validated final model only on months where the observed predictor stack is actually present together: Copernicus SLA, historical GRACE ocean mass, Greenland mass, and cleaned Argo density.
- **Regime B - present-day continuation:** For months after the historical GRACE ocean-mass series ends, do not silently forward-fill or extrapolate that predictor. Either ingest a same-family continuation series or retrain and revalidate a post-2017-compatible Argo-required variant before publishing 2018+ estimates.
- **Regime C - true future extrapolation:** If future predictor values are unavailable, publish only trend or scenario envelopes and label them explicitly as extrapolations rather than model-constrained predictions.

### 9.3 Monthly long-horizon build plan

This implementation pass is complete:

1. `predict_monthly.py` consumes the normalized monthly dataset plus the final-model fit logic.
2. Monthly absolute sea level is reconstructed from target space plus the station baseline.
3. Station-level monthly predictions and annual mean summaries are exported as CSV and NetCDF products.
4. Every output month carries a regime label.
5. Station-specific Phase 4 CV RMSE is carried forward as the monthly uncertainty band.
6. Argo remains in the published final monthly model.

### 9.4 Annual projection track

The annual path is now separate and Portland-specific:

1. `annual_projection_data.py` builds the Portland annual training table from annualized monthly data plus NAO and land-motion metadata.
2. `annual_projection_model.py` fits an annual model ladder and backtests 5-year, 10-year, and tail holdouts.
3. `project_annual.py` publishes century-scale annual mean projections from the extracted annual trend plus trained model noise.
4. The annual table intentionally excludes Argo and historical GRACE as required annual predictors.
5. Land motion is handled as deterministic metadata in the target adjustment rather than as a noisy learned predictor.
6. `docs/annual_projection.md` is the canonical method and schema reference for this track.

### 9.5 Guardrails for scope and interpretation

If monthly/yearly outputs are produced from the current stack, they should be labeled clearly as:

- reduced-scope
- observationally constrained where observed predictors exist
- structurally limited by missing direct atmospheric and land-motion drivers
- not valid for Rockland unless a modern target record is added

### 9.6 Future enhancement path

If projection skill is inadequate, then Sojs should add deferred sources in this order:

1. one atmospheric/climate driver family
2. one ocean interior / steric data family
3. one land-motion refinement source

That sequence is more defensible than reactivating the entire original list at once.

---

## 10. Uncertainty

### 10.1 Current uncertainty sources

- tide-gauge record length and station coverage differences
- coastal limitations of gridded altimetry
- sparse overlap between retained datasets
- incomplete physical budget due to deferred sources
- projection structural uncertainty if future scenarios are attempted

### 10.2 Reporting rule

Sojs should distinguish between:

- observational uncertainty in retained data
- structural uncertainty from missing processes
- scenario uncertainty in any future projection work

---

## 11. Validation

### 11.1 Immediate validation tasks

- compare active predictors against Portland, Rockland, and Bar Harbor monthly means
- test whether the reduced feature matrix outperforms simple trend or persistence baselines
- document periods where the active stack clearly fails to explain local variability
- validate any post-2017 continuation variant separately before merging it into the monthly long-horizon export path
- verify the annual Portland model continues to beat a trend-only baseline on rolling holdouts before publishing more ambitious annual scenarios

### 11.2 Success criterion

The first milestone is not “solve the full Maine sea-level budget.” The first milestone is:

- show that the retained active data stack can support a coherent hindcast workflow
- quantify what it explains
- quantify what remains unresolved

---

## 12. Deliverables

### 12.1 Data products

- normalized NetCDF outputs for all retained datasets
- summary CSV diagnostics for each retained workflow
- synchronized documentation in `docs/data_collection.md`

### 12.2 Analysis products

- station comparison figures
- overlap-period diagnostics across tide gauges, altimetry, and mass terms
- reduced-budget closure figures

### 12.3 Modeling products

- reduced feature matrix
- baseline hindcast results
- monthly prediction exports for validated stations
- annual means derived from the monthly prediction exports where monthly products exist
- Portland annual training, backtest, and scenario-projection products from the separate annual track
- projections only if the reduced-stack validation justifies them and the predictor regime is explicit

---

## 13. Tools and Runtime

### 13.1 Core libraries in current use

```bash
pip install requests pandas
pip install xarray netcdf4 h5py
pip install numpy matplotlib
pip install copernicusmarine
```

### 13.2 Special runtime note

`podaac-data-subscriber` is part of the active PO.DAAC workflow, but it is not installed in the project `.venv` because the repo environment is Python `3.14.2`. Sojs currently uses a separate local Python `3.12` runtime for the subscriber executable.

### 13.3 Current storage posture

The active Sojs data footprint is materially smaller than the original full-plan estimate because large deferred collections such as Argo, NERACOOS, ERA5, WOA, and InSAR were not downloaded.

---

## 14. Timeline

### Phase 1 - Completed data collection
- [x] Implement NOAA CO-OPS workflow
- [x] Implement Copernicus Marine workflow
- [x] Implement PO.DAAC GRACE ocean-mass workflow
- [x] Implement PO.DAAC Greenland mass workflow
- [x] Document collection steps and resolved errors

### Phase 2 - Active data reconciliation
- [x] Align all retained datasets to a shared monthly timeline
- [x] Decide which retained variables are model inputs versus diagnostics-only
- [x] Produce overlap tables for Portland, Rockland, and Bar Harbor
- [x] Finalize the reduced active feature set

### Phase 3 - Reduced-budget analysis
- [x] Build the first reduced observational budget
- [x] Quantify residuals for the retained stations
- [x] Identify which missing processes matter enough to justify new data collection

### Phase 4 - Hindcast modeling
- [x] Train and test reduced-scope models against the retained stations
- [x] Compare against trend and persistence baselines
- [x] Decide whether the active stack is sufficient or needs expansion

### Phase 5 - Projection decision
- [x] Approve limited monthly prediction work for Portland and Bar Harbor based on Phase 4 hindcast skill
- [x] Implement the monthly reconstruction/export pipeline for the final Argo-inclusive model
- [x] Decide and implement the post-2017 ocean-mass continuation path before publishing 2018+ estimates
- [x] Produce annual means strictly from the monthly outputs
- [ ] Keep Rockland out of the active prediction workflow unless a modern target record is added
- [ ] Treat true future estimates as scenario extrapolations, not validated predictions

### Phase 6 - Annual projection track
- [x] Build the Portland annual training table with coverage diagnostics
- [x] Join annual mean and winter DJF NAO features
- [x] Add a first-pass Portland land-motion metadata artifact
- [x] Fit and backtest a separate annual model ladder
- [x] Publish baseline, low, and high annual century-projection summary paths from the extracted trend plus trained model noise

### Phase 7 - Communication
- [ ] Keep `plan.md` and `docs/data_collection.md` synchronized
- [ ] Write methods and limitations clearly
- [ ] Prepare final figures, summaries, and any downstream dashboard material

---

*Study area: Penobscot Bay · Muscongus Bay · Rockland Harbor, Maine*  
*Last updated: April 2026*
