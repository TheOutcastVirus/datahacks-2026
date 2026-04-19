# Sojs Data Collection Log

## Scope

This document records the data collection workflows implemented in Sojs, the data sources used, the outputs written to disk, and the main errors encountered and resolved during setup.

The work covered:

- NOAA CO-OPS tide-gauge monthly mean sea-level records
- Copernicus Marine Gulf of Maine sea-level anomaly and absolute dynamic topography
- PO.DAAC GRACE/GRACE-FO ocean-mass products
- PO.DAAC Greenland ice-sheet mass anomaly time series
- CPC monthly North Atlantic Oscillation index
- Argo monthly NW Atlantic shelf temperature, salinity, and density context
- Portland land-motion metadata for the annual projection track

## Project Conventions

The project uses a consistent pattern:

- Raw or downloaded data stored under `data/...`
- Derived figures and summaries stored under `plots/...`
- Standalone collection scripts stored at repo root
- NetCDF used as the normalized storage format when practical

## 1. NOAA CO-OPS Tide Gauges

### Goal

Download NOAA CO-OPS `monthly_mean` records for Rockland, Portland, and Bar Harbor, convert them to NetCDF, and generate summary plots.

### Script

- `coops_tide_gauges.py`

### Output locations

- `data/coops`
- `plots/coops`

### Key implementation details

- Pulled data from the NOAA CO-OPS API using station IDs
- Parsed monthly mean CSV responses
- Converted each station record to an `xarray.Dataset`
- Saved one NetCDF file per station
- Generated:
  - station time-series plots
  - multi-station overlay
  - anomaly plot
  - climatology plot
  - summary CSV

### Errors solved

- NOAA CSV parsing was not stable enough for a single hard-coded `skiprows=1` strategy.
- The live endpoint sometimes returned a proper header row directly, so the parser was updated to try both direct header parsing and the fallback `skiprows=1` path.
- The parser was hardened to normalize column names and detect the actual monthly mean column rather than assuming one fixed header spelling.

### Final outputs

- `data/coops/bar_harbor_8413320_monthly_mean_msl.nc`
- `data/coops/portland_8418150_monthly_mean_msl.nc`
- `data/coops/rockland_8415490_monthly_mean_msl.nc`
- `plots/coops/monthly_mean_sea_level_overlay.png`
- `plots/coops/monthly_mean_sea_level_anomaly_12mo.png`
- `plots/coops/monthly_mean_sea_level_climatology.png`
- `plots/coops/coops_monthly_mean_summary.csv`

## 2. Copernicus Marine SLA/ADT

### Goal

Download Gulf of Maine sea-level anomaly (`sla`) and absolute dynamic topography (`adt`) from Copernicus Marine, save the subset to NetCDF, and generate map and time-series diagnostics.

### Script

- `copernicusmarine_sla.py`

### Output locations

- `data/copernicusmarine`
- `plots/copernicusmarine`

### Key implementation details

- Requested a bounded Gulf of Maine subset
- Downloaded via `copernicusmarine.subset`
- Opened the output NetCDF with `xarray`
- Generated:
  - mean maps
  - standard deviation maps
  - area-mean time series
  - summary CSV

### Errors solved

- The initial dataset ID from the prompt was not valid in the live Copernicus catalogue.
- The working dataset ID was updated to `cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1D`.
- The runtime was missing `copernicusmarine`.
- NetCDF writing also required `h5py`.
- The script originally failed too opaquely when credentials were missing, so credential checks and clearer auth/catalogue error messages were added.
- Standard deviation plotting emitted `Degrees of freedom <= 0 for slice` warnings, so the plotting path was wrapped to suppress those expected warnings.

### Credential handling

- Supports standard Copernicus credentials file
- Supports `COPERNICUSMARINE_SERVICE_USERNAME`
- Supports `COPERNICUSMARINE_SERVICE_PASSWORD`

### Final outputs

- `data/copernicusmarine/gulf_of_maine_sla.nc`
- `plots/copernicusmarine/sla_mean_map.png`
- `plots/copernicusmarine/sla_std_map.png`
- `plots/copernicusmarine/sla_area_mean_timeseries.png`
- `plots/copernicusmarine/adt_mean_map.png`
- `plots/copernicusmarine/adt_std_map.png`
- `plots/copernicusmarine/adt_area_mean_timeseries.png`
- `plots/copernicusmarine/gulf_of_maine_sla_summary.csv`

## 3. PO.DAAC GRACE/GRACE-FO Ocean Mass

### Goal

Download monthly ocean bottom pressure anomaly grids from PO.DAAC, normalize them into a single NetCDF, and produce regional Gulf of Maine diagnostics.

Two separate collections were used:

- GRACE-FO continuation:
  - `TELLUS_GRFO_L3_CSR_RL06.3_OCN_v04`
- Historical GRACE mission:
  - `TELLUS_GRAC_L3_CSR_RL06_OCN_v04`

### Script

- `grace_mass_grids.py`

### Output locations

- GRACE-FO:
  - `data/grace`
  - `plots/grace`
- Historical GRACE:
  - `data/grace_grac_ocn`
  - `plots/grace_grac_ocn`

### Initial approach and why it changed

The first implementation tried to crawl PO.DAAC/CMR directory-style URLs directly and download granules by scraping HTML listings. That turned out to be brittle and incorrect for this workflow.

The script was then redesigned to use the official PO.DAAC bulk-download path:

- `podaac-data-subscriber`

This matched PO.DAAC guidance for protected cloud collections and was much more stable than trying to scrape the virtual directory directly.

### Key implementation details

- Resolve Earthdata credentials
- Run `podaac-data-subscriber` for the target collection
- Download all `.nc` granules into a raw directory
- Open each granule with `xarray`
- Concatenate along time
- Save a combined NetCDF
- Generate:
  - mean map
  - standard deviation map
  - latest map
  - Gulf of Maine area-mean time series
  - Gulf of Maine anomaly heatmap
  - summary CSV

### Errors solved

#### Wrong OPeNDAP collection URL / `400 Client Error`

- The original approach targeted `https://opendap.earthdata.nasa.gov/PODAAC/GRACE_FO_MONTHLY_MASS_GRIDS_V04/`.
- That URL was not a usable collection-listing endpoint for the workflow.
- The code was changed away from direct scraping and onto `podaac-data-subscriber`.

#### Missing Earthdata credentials

- The script was updated to support:
  - explicit username/password flags
  - `_netrc`
  - `.netrc`

#### `_netrc` created as a directory

- At one point `C:\Users\matfu\_netrc` existed as a directory instead of a file.
- The script now detects that case and exits with a clear message.

#### PO.DAAC subscriber auth bug

- The installed `podaac-data-subscriber` package could crash with:
  - `UnboundLocalError: cannot access local variable 'username'`
- Root cause: its auth helper assumed a usable default `netrc` lookup and did not safely handle missing credentials.
- The wrapper now launches the subscriber inside a controlled environment with both `_netrc` and `.netrc` written into a temporary home directory.

#### Python 3.14 incompatibility

- The repo `.venv` uses Python `3.14.2`.
- `podaac-data-subscriber` depends on `harmony-py`, which only supports Python `3.9` through `3.13`.
- Installing the subscriber inside the project `.venv` failed because `shapely` had no workable wheel/build path in that environment.
- Resolution:
  - install `podaac-data-subscriber` into the local standalone Python 3.12 runtime
  - autodetect that executable from `grace_mass_grids.py`

#### Temporary credential directory permissions

- Using `tempfile.TemporaryDirectory` caused Windows permission issues in this environment.
- The wrapper was updated to create and clean up its own workspace-local auth directory under `.tmp-auth`.

#### Redownload behavior

- The scripts were updated to reuse existing raw downloads unless `--force-download` is set.
- This avoided unnecessary reauthentication and made reruns deterministic.

### Historical GRACE outputs

- `data/grace_grac_ocn/grace_ocean_mass_2002_2017.nc`
- `plots/grace_grac_ocn/lwe_thickness_mean_map.png`
- `plots/grace_grac_ocn/lwe_thickness_std_map.png`
- `plots/grace_grac_ocn/lwe_thickness_latest_map.png`
- `plots/grace_grac_ocn/lwe_thickness_gom_area_mean_timeseries.png`
- `plots/grace_grac_ocn/lwe_thickness_gom_monthly_anomalies.png`
- `plots/grace_grac_ocn/uncertainty_mean_map.png`
- `plots/grace_grac_ocn/grace_ocean_mass_summary.csv`

### Historical GRACE coverage

- Time range in combined NetCDF: `2002-04-18` to `2017-06-10`
- Time steps: `163`
- Grid: `180 x 360`
- Variables:
  - `lwe_thickness`
  - `uncertainty`

## 4. Greenland Ice-Sheet Mass Contributions

### Goal

Download the Greenland mass anomaly time series from PO.DAAC, convert the ASCII product into NetCDF, and generate summary plots.

### Collection used

- `GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4`

### Script

- `greenland_mass_timeseries.py`

### Output locations

- `data/greenland_mass`
- `plots/greenland_mass`

### Key implementation details

- Uses the same subscriber/auth wrapper pattern as `grace_mass_grids.py`
- Downloads the protected PO.DAAC ASCII time-series product
- Parses the text file into a tabular structure
- Converts the result to NetCDF
- Generates:
  - monthly time-series plot
  - annual mean plot
  - summary CSV

### Errors solved

#### File format not CSV

- The downloaded Greenland file is not a simple CSV.
- It contains:
  - `HDR` metadata lines
  - a `Header_End` marker
  - fixed-column numeric data
- A generic `read_csv` call failed with a `ParserError`.
- The parser was replaced with a format-aware path that:
  - finds `Header_End`
  - reads only the numeric rows
  - applies explicit column names

#### Wrong primary file selection

- The raw download directory also includes:
  - checksum files
  - citation sidecars
- Primary-file selection was updated to prefer the actual data table and ignore citation/checksum files.

#### Incorrect time parsing

- The Greenland data uses decimal-year time such as `2002.29`.
- The initial parser tried generic datetime inference first, which led to bad `1970-01-01` output.
- The inference order was changed so decimal-year columns are handled before generic datetime parsing.

#### Missing uncertainty variable capture

- The Greenland ASCII file includes a third column for 1-sigma uncertainty.
- The converter was updated to preserve that as `greenland_mass_sigma_gt`.

### Final outputs

- `data/greenland_mass/greenland_mass_timeseries.nc`
- `plots/greenland_mass/greenland_mass_timeseries.png`
- `plots/greenland_mass/greenland_mass_annual_mean.png`
- `plots/greenland_mass/greenland_mass_summary.csv`

### Greenland coverage

- Time range: `2002-04-01` to `2026-02-01`
- Time steps: `254`
- Variables:
  - `greenland_mass_gt`
- `greenland_mass_sigma_gt`

## 5. Argo NW Atlantic Shelf Context

### Goal

Fetch monthly Argo profile data for the Gulf of Maine and NW Atlantic shelf context, grid it to a consistent cube, derive density, and carry cleaned monthly shelf-context series into the normalized join.

### Scripts

- `argo_cube.py`
- `plot_argo_preliminary.py`
- `normalize_active_data.py`

### Output locations

- `data/sojs_argo_monthly_density_1950_present.nc`
- `plots/argo`
- `data/normalized`

### Key implementation details

- Queried Argo through `argopy` using the ERDDAP regional fetcher
- Filtered to delayed-mode and adjusted-mode data only
- Interpolated profiles onto standard depth levels
- Aggregated the cube to monthly temperature, salinity, density, and sample-count fields
- Reduced the cube into cleaned NW Atlantic shelf monthly context series before joining:
  - temperature
  - salinity
  - density
  - support diagnostics

### Cleaning and join rules

- The normalization workflow does **not** join raw gridded Argo cells directly.
- It first reduces the cube to monthly regional context series over the NW Atlantic shelf box.
- Shallow context is taken from `0-200 dbar`.
- Joined Argo months are masked unless both of the following are true:
  - `sample_count >= 18`
  - occupied lat/lon grid cells `>= 2`
- This keeps isolated one-cell / one-profile months out of the normalized join.

### Final outputs

- `data/sojs_argo_monthly_density_1950_present.nc`
- `plots/argo/monthly_cells_with_support.png`
- `plots/argo/monthly_support_calendar_heatmap.png`
- `plots/argo/shallow_temperature_map.png`
- `plots/argo/shallow_salinity_map.png`
- `plots/argo/shallow_density_map.png`
- `plots/argo/temperature_time_depth.png`
- `plots/argo/salinity_time_depth.png`
- `plots/argo/density_time_depth.png`
- `data/normalized/sojs_active_monthly_normalized.nc`
- `data/normalized/sojs_active_modern_overlap_with_argo.nc`

### Current modeling implications

- `data/normalized/sojs_active_modern_overlap.nc` excludes `rockland_msl_m`; the retained modern overlap is defined by Portland, Bar Harbor, Copernicus SLA/ADT, historical GRACE ocean mass, and Greenland mass.
- `data/normalized/sojs_active_modern_overlap_with_argo.nc` applies the same modern-overlap requirement plus the cleaned Argo support filters. In the current normalized summary this leaves 40 supported Argo-overlap months.
- The historical GRACE ocean-mass workflow in this repo currently ends in 2017. Any 2018+ monthly prediction workflow must either add an explicit continuation series from the same family or retrain a post-2017-compatible model variant on purpose.

## 6. Phase 4 Hindcast Modeling

### Goal

Validate whether the retained active Sojs predictor stack can support limited monthly modeling for the stations that still have a defensible modern overlap window.

### Script

- `hindcast_model.py`

### Stations kept in scope

- Portland
- Bar Harbor

Rockland is intentionally excluded from the validated monthly modeling window because the retained modern overlap dataset is defined without a modern Rockland target series.

### Final model decision

- The final Sojs model is `ols_with_argo_ridge`.
- Predictors kept in the final model:
  - `copernicus_sla_gom_m_zscore`
  - `grace_hist_lwe_thickness_gom_m_zscore`
  - `greenland_mass_gt_zscore`
  - `argo_density_shelf_0_200dbar_kg_m3_zscore`
- Argo density is used instead of carrying temperature, salinity, and density together because density already encodes both T and S physically and avoids the short-window collinearity problem seen in the overlap period.

### Key implementation details

- Evaluates models only on the cleaned Argo-overlap window:
  - `2004-07-01` through `2017-06-01`
  - `40` monthly samples per modeled station
- Pre-removes the trend-adjusted seasonal cycle from both target and predictors before cross-validation.
- Uses forward time-series splits to avoid future leakage.
- Keeps multiple baseline models for comparison:
  - persistence
  - trend only
  - trend plus seasonal harmonics
  - reduced OLS variants
  - detrended OLS with Argo
  - detrended ridge with Argo
- Saves the station-specific in-sample hindcast and residuals to a NetCDF product for downstream reuse.

### Shared-model refactor completed during this work

To support the later projection step without duplicating logic, the hindcast code was refactored so the final-model fit can be reused directly:

- `FinalModelFit` now stores the fitted target/predictor transforms, trend terms, ridge coefficients, and station baseline metadata.
- `fit_station_final_model(...)` fits the validated final model once and returns a reusable fit object.
- `predict_with_final_model(...)` applies the stored transforms to new monthly predictor data.
- The original hindcast outputs were rerun after the refactor to confirm the Phase 4 workflow still executes cleanly.

### Final outputs

- `data/hindcast/sojs_hindcast_results.nc`
- `plots/hindcast/sojs_hindcast_skill_table.csv`
- `plots/hindcast/sojs_hindcast_skill_summary.md`
- `plots/hindcast/sojs_hindcast_rmse_comparison.png`
- `plots/hindcast/portland_hindcast.png`
- `plots/hindcast/bar_harbor_hindcast.png`

## 7. CPC Monthly NAO

### Goal

Fetch the CPC monthly NAO index, convert it into Sojs artifacts, and derive annual plus winter DJF diagnostics for the annual projection track.

### Script

- `nao_index.py`

### Output locations

- `data/nao`
- `plots/nao`

### Key implementation details

- Downloads the CPC monthly ASCII NAO table.
- Saves raw text, wide CSV, long CSV, and NetCDF artifacts.
- Generates monthly, annual, winter DJF, climatology, and seasonal-heatmap diagnostics.
- Provides the long annual climate-driver family used by `annual_projection_data.py`.

### Final outputs

- `data/nao/nao_monthly.csv`
- `data/nao/nao_monthly.nc`
- `plots/nao/nao_annual_mean.png`
- `plots/nao/nao_winter_djf.png`
- `plots/nao/nao_summary.csv`

## 8. Monthly Prediction and Export Pipeline

### Goal

Implement the plan-driven Sojs monthly prediction pipeline using the validated Phase 4 final model, publish station-level monthly outputs, derive annual summaries from those monthly outputs, and label each month by regime.

### Script

- `predict_monthly.py`

### Scope implemented

- Published stations:
  - Portland
  - Bar Harbor
- Explicitly excluded:
  - Rockland

### Regime design implemented

The monthly pipeline does not treat `2004` to future as one uninterrupted model run. It uses three explicit regimes:

- `constrained_reconstruction`
  - Months where the full validated predictor stack is actually present together:
    - Copernicus SLA
    - historical GRACE ocean mass
    - Greenland mass
    - cleaned Argo density
- `validated_continuation`
  - Months after the historical GRACE series where the same-family GRACE-FO ocean-mass continuation is available together with the other required predictors
- `pure_extrapolation`
  - Months where the full predictor stack is not available and the output is therefore only a trend-plus-seasonal extrapolation

### Continuation decision used here

- The historical mass predictor in the validated model ends in `2017-06`.
- The repo already contained a same-family GRACE-FO continuation product:
  - `data/grace/grace_ocean_mass_monthly.nc`
- The prediction pipeline reduces that GRACE-FO grid to the same Gulf of Maine area-mean mass series used by the historical GRACE workflow.
- The continuation series is standardized onto the historical GRACE mean and standard deviation before being inserted into the final model predictor slot.

### Key implementation details

- Reuses the fitted Phase 4 final-model transforms rather than reimplementing them separately.
- Reconstructs monthly absolute sea level by:
  - predicting in the model target space
  - adding back the GIA component
  - adding back the station baseline
- Carries station-specific Phase 4 cross-validation RMSE forward as a constant `+/- 1 sigma` uncertainty band.
- Derives annual mean summaries strictly from the exported monthly predictions, not from a separate annual model.
- Writes both tabular exports and a NetCDF product for downstream analysis.
- Produces station plots with visible regime shading and residual panels.

### Current output span

- Monthly predictions run from `2004-07-01` through `2026-03-01`.
- Observed tide-gauge values available for direct comparison currently run through `2024-12-01`.

### Validation summary from the implemented pipeline

Observed-period validation is now exported explicitly instead of being implicit in the plots.

#### Constrained reconstruction (`2004-07-01` to `2017-06-01`)

- Bar Harbor:
  - RMSE `0.017775 m`
  - R^2 `0.8608`
- Portland:
  - RMSE `0.022987 m`
  - R^2 `0.8188`

#### Validated continuation (observed overlap in practice: `2018-06-01` to `2024-12-01`, with gaps where the full predictor stack is missing)

- Bar Harbor:
  - RMSE `0.031862 m`
  - R^2 `0.6145`
- Portland:
  - RMSE `0.068973 m`
  - R^2 `-0.4452`

That means the GRACE-FO continuation is defensible enough for Bar Harbor as a limited continuation path, but it remains weak for Portland in the currently retained predictor stack. The docs and exported summaries should therefore be read as reduced-scope observational products, not as a fully trusted long-horizon closure model.

### Final outputs

- `data/predictions/sojs_monthly_predictions.csv`
- `data/predictions/sojs_monthly_predictions.nc`
- `data/predictions/sojs_annual_prediction_summary.csv`
- `data/predictions/sojs_prediction_validation_summary.csv`
- `plots/predictions/portland_monthly_prediction.png`
- `plots/predictions/bar_harbor_monthly_prediction.png`
- `plots/predictions/sojs_prediction_summary.md`

## 9. Portland Land-Motion Metadata

### Goal

Publish a narrow Portland land-motion artifact so the annual target adjustment does not silently treat fixed GIA metadata as the whole land-motion story.

### Script

- `land_motion.py`

### Output locations

- `data/land_motion`
- `plots/land_motion`

### Key implementation details

- Writes a single-site Portland artifact with:
  - GIA metadata rate and uncertainty
  - explicit VLM placeholder rate and uncertainty
  - combined relative land-motion rate and uncertainty
  - metadata describing the source and whether the artifact is GIA-only, VLM-only, or combined
- The artifact is deterministic metadata for the annual target adjustment, not a learned annual predictor.

### Final outputs

- `data/land_motion/portland_land_motion.nc`
- `plots/land_motion/portland_land_motion_summary.csv`

## 10. Annual Projection Data, Model, and Century-Projection Pipeline

### Goal

Build a separate Portland annual projection track that is distinct from the monthly reconstruction/export workflow.

### Scripts

- `annual_projection_data.py`
- `annual_projection_model.py`
- `project_annual.py`

### Output locations

- `data/annual`
- `plots/annual`
- `data/projections`
- `plots/projections`

### Key implementation details

- Annual training data is built from `data/normalized/sojs_active_monthly_normalized.nc`.
- Calendar-year means require at least `9` valid months per variable.
- The annual table carries `months_present_<var>` diagnostics for the retained target and predictors.
- Required annual predictors are intentionally limited to:
  - Portland annual mean sea level
  - Copernicus Gulf of Maine SLA annual mean
  - Greenland mass annual mean
  - annual mean NAO
  - winter DJF NAO
  - deterministic land-motion metadata
- Argo and historical GRACE are intentionally excluded as required annual predictors.
- The annual model ladder is backtested separately from the monthly model.
- `project_annual.py` extracts the retained historical annual trend, couples it to the trained annual-model noise, and publishes century-scale annual mean projections with widening uncertainty bands.
- `docs/annual_projection.md` is the canonical detailed reference for annual schema, method, current metrics, and outputs.

### Final outputs

- `data/annual/sojs_portland_annual_training.csv`
- `data/annual/sojs_portland_annual_training.nc`
- `data/annual/sojs_portland_annual_backtest.csv`
- `data/annual/sojs_portland_annual_model.json`
- `plots/annual/portland_annual_coverage.png`
- `plots/annual/portland_annual_backtest.png`
- `plots/annual/sojs_annual_model_summary.md`
- `data/projections/sojs_portland_annual_projections.csv`
- `data/projections/sojs_portland_annual_projections.nc`
- `plots/projections/portland_annual_projection.png`
- `plots/projections/sojs_annual_projection_summary.md`

## Environment and Tooling Notes

### Python environments

- Primary project environment:
  - `.venv`
  - Python `3.14.2`
- Auxiliary PO.DAAC subscriber runtime:
  - `C:\Users\matfu\AppData\Local\Python\pythoncore-3.12-64`

### Temporary auth staging

- Workspace-local directory:
  - `.tmp-auth`

This is used only to stage temporary credential files for the subscriber wrapper.

### Installed scripts added during work

- `coops_tide_gauges.py`
- `copernicusmarine_sla.py`
- `grace_mass_grids.py`
- `greenland_mass_timeseries.py`
- `hindcast_model.py`
- `land_motion.py`
- `nao_index.py`
- `predict_monthly.py`
- `annual_projection_data.py`
- `annual_projection_model.py`
- `project_annual.py`

## Rerun Commands

### NOAA CO-OPS

```powershell
& .\.venv\Scripts\python.exe coops_tide_gauges.py --stations Rockland Portland "Bar Harbor"
```

### Copernicus Marine

```powershell
& .\.venv\Scripts\python.exe copernicusmarine_sla.py
```

### Historical GRACE ocean mass (2002-2017)

```powershell
& .\.venv\Scripts\python.exe grace_mass_grids.py `
  --collection-short-name TELLUS_GRAC_L3_CSR_RL06_OCN_v04 `
  --start-date 2002-04-04T00:00:00Z `
  --end-date 2017-10-25T00:00:00Z `
  --raw-dir data\grace_grac_ocn\raw `
  --output data\grace_grac_ocn\grace_ocean_mass_2002_2017.nc `
  --plot-dir plots\grace_grac_ocn
```

### Greenland mass time series

```powershell
& .\.venv\Scripts\python.exe greenland_mass_timeseries.py `
  --raw-dir data\greenland_mass\raw `
  --output data\greenland_mass\greenland_mass_timeseries.nc `
  --plot-dir plots\greenland_mass
```

### Phase 4 hindcast

```powershell
& .\.venv\Scripts\python.exe hindcast_model.py
```

### Monthly prediction export

```powershell
& .\.venv\Scripts\python.exe predict_monthly.py
```

## Remaining Caveats

- The PO.DAAC subscriber is still an external dependency with upstream auth-handling weaknesses; Sojs currently wraps around those issues rather than fixing the package itself.
- The historical GRACE combined time axis reflects the actual granules delivered by PO.DAAC and may not be strictly one file per calendar month because of mission gaps and product-specific temporal spans.
- If more Greenland subregion or sector-specific contributions are needed, a different PO.DAAC product or a spatial postprocessing workflow will be required.
- The monthly prediction product is intentionally reduced-scope:
  - observationally constrained where the retained predictors exist
  - structurally limited by missing atmospheric and land-motion drivers
  - not valid for Rockland under the current retained-modern-overlap setup
- The exported regime windows are intermittent rather than continuous because Argo support and the retained predictor stack still contain real month-level gaps.
- The current GRACE-FO continuation path is materially stronger for Bar Harbor than for Portland; any future attempt to publish Portland continuation products should be validated again before broad interpretation.
