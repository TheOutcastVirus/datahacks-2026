# California Coast Sea Level Model Plan

## Goal

Build a regional sea level model for locations along the California coast.

Primary objective:
- predict or explain relative sea level at coastal California stations over time

Recommended scope for the first usable version:
- station-level monthly model
- target based on NOAA tide-gauge monthly means
- coverage focused on major California coastal stations

Suggested initial station set:
- San Diego
- Los Angeles / La Jolla area station as available from NOAA CO-OPS
- Monterey
- San Francisco
- Humboldt Bay / Crescent City as available from NOAA CO-OPS

## What The Model Should Predict

Choose one target first and keep the project narrow.

Best first target:
- monthly mean relative sea level anomaly by station

Alternative targets:
- monthly mean water level
- detrended anomaly
- seasonal anomaly
- 12-month-forward trend estimate

For the first pass, use:
- `target = monthly mean relative sea level anomaly at each station`

Why:
- monthly data is cleaner than hourly for a first model
- this reduces tidal noise
- it aligns well with climate and oceanographic features

## Phase 1: Define The Problem Clearly

Tasks:
- decide whether the project is forecasting, explanation, or hindcasting
- define the prediction horizon
- define the temporal resolution
- define the spatial unit
- define the evaluation metric

Decisions to lock in:
- use monthly resolution
- use station-level predictions
- start with hindcast/explanatory modeling
- later extend to short-horizon forecasting

Deliverable:
- one sentence problem definition

Example:
- "Predict monthly relative sea level anomaly for California NOAA tide-gauge stations using local and regional ocean-climate features."

## Phase 2: Build The Target Dataset

Primary source:
- NOAA CO-OPS tide-gauge monthly means

Tasks:
- list all California stations to include
- collect station metadata
- pull monthly water level data for each station
- standardize time zones and timestamps
- choose a common datum/anomaly convention
- store one clean table with `station_id`, `lat`, `lon`, `date`, `target`

Required checks:
- station coverage length
- missing months
- station moves or datum issues
- overlap period across stations

Output table:
- `monthly_sea_level.csv` or similar

Recommended columns:
- `station_id`
- `station_name`
- `lat`
- `lon`
- `date`
- `water_level`
- `water_level_anomaly`
- `source`

## Phase 3: Add Core Static Features

These are features that do not change often.

Tasks:
- store station latitude
- store station longitude
- store coastal region label
- store station-to-region grouping
- optionally store coastal orientation or bathymetry proxy later

Recommended features:
- `lat`
- `lon`
- `region`

Possible region labels:
- Southern California
- Central California
- San Francisco Bay
- North Coast

## Phase 4: Add Vertical Land Motion

Purpose:
- separate ocean change from land uplift/subsidence effects

Tasks:
- identify the nearest GNSS/CORS station for each tide gauge
- collect vertical land motion rate
- join land-motion values to each tide station
- document which tide station is paired with which geodetic station

Recommended features:
- `vlm_mm_per_year`
- `vlm_source_station`
- `vlm_distance_km`

Important note:
- tide gauges measure sea level relative to land, so this feature is high priority

## Phase 5: Add Atmospheric Forcing Features

Purpose:
- capture weather-driven coastal water-level variability

Primary data:
- pressure
- wind

Suggested source:
- ERA5 reanalysis

Tasks:
- choose a California coastal ocean box or station-adjacent grid cells
- extract monthly mean sea level pressure
- extract monthly mean zonal wind
- extract monthly mean meridional wind
- create alongshore and onshore wind components if possible
- align to the same monthly timeline as the tide gauges

Recommended features:
- `mslp`
- `u10`
- `v10`
- `alongshore_wind`
- `onshore_wind`

Optional additions:
- wind stress
- wave proxy
- storm count metric

## Phase 6: Add Ocean State Features

### 6A. Satellite Sea Surface Height

Purpose:
- capture offshore sea level anomalies not visible from a single tide gauge

Tasks:
- choose an offshore California box or a few regional sample cells
- download gridded sea surface height anomaly data
- compute monthly means
- decide whether to use a single regional average or multiple coastal segments

Recommended features:
- `ssh_anomaly_ca_south`
- `ssh_anomaly_ca_central`
- `ssh_anomaly_ca_north`

### 6B. Sea Surface Temperature

Purpose:
- capture thermal state and large-scale ocean variability

Suggested source:
- NOAA OISST

Tasks:
- choose one or more California coastal SST boxes
- compute monthly mean SST
- compute SST anomaly relative to climatology

Recommended features:
- `sst`
- `sst_anomaly`

### 6C. Temperature-Salinity Derived Features

Purpose:
- represent steric effects and subsurface ocean structure

Current local data source in this repo:
- CalCOFI temperature and salinity profiles

Tasks:
- decide which region of CalCOFI best maps to each station or subregion
- aggregate profiles to monthly or seasonal features
- engineer density-related metrics
- avoid using raw sparse monthly values directly without aggregation

Recommended derived features:
- upper-ocean mean temperature
- upper-ocean mean salinity
- density anomaly
- steric-height proxy
- heat-content proxy

Important note:
- this is a useful secondary feature set, not the main target source

## Phase 7: Add Climate Index Features

Purpose:
- capture large-scale climate modes that affect the California coast

Priority indices:
- PDO
- ONI / ENSO

Optional indices:
- NPGO
- MEI

Tasks:
- download monthly index values
- align indices to monthly station dates
- test lagged versions

Recommended features:
- `pdo`
- `oni`
- `pdo_lag_3`
- `oni_lag_3`
- `pdo_lag_6`
- `oni_lag_6`

## Phase 8: Add Freshwater Inputs Only If Relevant

Use this only for estuary-influenced stations.

Good candidates:
- San Francisco Bay-related stations
- river-mouth or lagoon-influenced sites

Tasks:
- identify whether each tide station is estuary-affected
- find nearby USGS streamgages
- aggregate streamflow to monthly means or totals

Recommended features:
- `streamflow`
- `streamflow_lag_1`

Important note:
- skip this for exposed open-ocean stations in the first version

## Phase 9: Build The Modeling Table

Create one final table where each row is one station-month.

Required columns:
- station identifiers
- time identifiers
- target
- all engineered features

Tasks:
- merge all sources by `station_id` and `date`
- document every join rule
- mark missing values explicitly
- decide how to impute or drop missing rows
- keep a feature dictionary

Recommended schema:
- `station_id`
- `date`
- `target`
- `lat`
- `lon`
- `region`
- `vlm_mm_per_year`
- `mslp`
- `u10`
- `v10`
- `alongshore_wind`
- `onshore_wind`
- `ssh_anomaly_*`
- `sst`
- `sst_anomaly`
- `pdo`
- `oni`
- `calcofi_*`

## Phase 10: Establish Baselines

Do not start with a complex model.

Build these first:
- climatology baseline
- previous-month persistence baseline
- linear time-trend baseline
- linear regression with a few features

Why:
- you need to know whether the real model beats simple structure

Metrics:
- RMSE
- MAE
- R-squared

Recommended split:
- time-based train/validation/test split

## Phase 11: Train Better Models

After baselines work, try:
- regularized linear regression
- random forest
- gradient boosted trees

Only after that, consider:
- sequence models
- spatiotemporal deep learning

Tasks:
- standardize features where needed
- compare feature subsets
- test lagged inputs
- inspect feature importance
- compare station-specific vs pooled models

Good experiment order:
- pooled linear model across all stations
- pooled tree model across all stations
- station-specific models
- pooled model with station embedding or station fixed effects

## Phase 12: Validate Carefully

You need validation that matches the real use case.

Tasks:
- test on future periods, not random rows
- test generalization across stations
- check whether performance is dominated by trend alone
- compare winter and summer performance
- inspect residuals during major ENSO events

Validation cuts to run:
- train early years, test later years
- leave-one-station-out
- Southern California vs Northern California holdout

Questions to answer:
- does the model beat persistence?
- does the model still work if trend is removed?
- which features matter most by region?

## Phase 13: Interpretability And Diagnostics

Tasks:
- plot predictions vs actual by station
- plot residuals over time
- inspect feature importance
- inspect partial dependence or SHAP if needed
- map performance by coastline region

Specific diagnostics:
- performance during El Nino years
- performance during low-pressure winter months
- sensitivity to land-motion feature
- sensitivity to CalCOFI-derived steric features

## Phase 14: Final Outputs

Minimum useful outputs:
- cleaned target dataset
- feature table
- baseline model results
- best model results
- station-by-station plots
- short methods summary

Good final artifacts:
- `data/processed/monthly_sea_level.csv`
- `data/processed/model_table.csv`
- `notebooks/` or scripts for EDA
- training script
- evaluation script
- figures directory
- model report

## Recommended Repo Work Breakdown

### Data Ingestion

Tasks:
- create scripts to download NOAA CO-OPS station data
- create script to store station metadata
- create script to ingest climate indices
- create script to ingest ERA5-derived monthly fields
- create script to ingest SST
- create script to ingest vertical land motion lookup

### Feature Engineering

Tasks:
- build monthly aggregation pipeline
- generate lagged features
- generate anomalies
- generate California regional averages
- generate CalCOFI steric proxy features

### Modeling

Tasks:
- build baseline model script
- build train/test split utilities
- build evaluation metrics
- build comparison plots

### Documentation

Tasks:
- document all sources
- document feature definitions
- document target definition
- document station inclusion criteria

## Immediate Next Steps

Do these first, in order:

1. Pick the California tide-gauge stations.
2. Build the monthly target dataset from NOAA CO-OPS.
3. Add station lat/lon and region labels.
4. Add vertical land motion by nearest GNSS/CORS station.
5. Add monthly ERA5 pressure and wind features.
6. Add monthly SST and PDO/ONI.
7. Build a station-month modeling table.
8. Train persistence and linear-regression baselines.
9. Add offshore SSH anomaly.
10. Add CalCOFI-derived steric features last.

## First Version Success Criteria

The first version is good enough if it can:
- produce one clean station-month table
- train on all included California stations
- beat a persistence baseline on held-out future months
- show understandable feature effects
- generate station-level plots without manual cleanup

## Things To Avoid

- starting with deep learning
- using raw sparse CalCOFI monthly values as a primary feature
- mixing datums without documenting them
- random train/test splits across time
- combining estuary and open-coast stations without labels
- adding too many features before building baselines

## Open Decisions

These still need to be decided:
- exact California station list
- whether to model raw monthly level or anomaly
- exact offshore boxes for SSH and SST
- whether to use one pooled model or station-specific models
- how to pair tide gauges with GNSS/CORS stations
- whether streamflow is included for bay/estuary stations
