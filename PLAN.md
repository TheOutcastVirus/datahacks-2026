```markdown
# Sojs — Sea Level Rise Modeling & Visualization

Project name: **Sojs**. Use "Sojs" as the canonical name in docs, UI, and metadata.

## Project Overview
Build a 3D world visualization that models sea level rise scenarios, powered by a prediction model trained on climate data. The system should display realistic flooding of real-world locations.
This is a general overview plan. Use this loosely and update tasks directly in this file as the project evolves.

---

## Phase 1: 3D World Generation
- [ ] Collect ~1000 real-world photographs of the target area
- [ ] Use AI-based photogrammetry pipeline to fill gaps and generate additional views from source images
- [ ] Construct 3D model from the combined image set
- [ ] Focus on realistic, image-based reconstruction (not generative/procedural architecture)

## Phase 2: Sea Level Rise Prediction Model
### Data Sources
- [ ] Acquire **Gulf of Mexico spray data** (temperature, salinity)
- [ ] Acquire **NASA ice cap data**
- [ ] Acquire **heat map data**
- [ ] Ensure at least one dataset comes from a required/specified database

### Model Design
- [ ] Input features: temperature, salinity, ice cap metrics, heat map data
- [ ] Output: predicted sea level rise (relative increase, i.e. `+X` or `+X²` over current levels)
- [ ] Prediction horizon: **10–100 years** (target visible, meaningful rise)
- [ ] Use relative sea level increase rather than predicting absolute current levels

### Validation
- [ ] Use **Gulf of Mexico historical sea levels** as the validation set
- [ ] Validate model predictions against known historical data

## Phase 3: Water Simulation & Flooding Visualization
- [ ] Implement water as a flat entity overlay on the 3D world
- [ ] Map predicted sea level rise values to visual flood levels
- [ ] Render flooded areas over the 3D model for different time horizons (10yr, 20yr, 100yr)

## Phase 4: Integration
- [ ] Connect prediction model output to the 3D visualization
- [ ] Allow user to scrub through time to see progressive flooding
- [ ] Display data source attributions (NASA, Gulf of Mexico datasets)

---

---

## Open Questions
- [ ] Determine exact correlation between input features and sea level rise (team lacks climate science expertise)
- [ ] Decide on final prediction horizon (20yr vs. 100yr)
- [ ] Confirm whether `+X` linear or `+X²` polynomial growth model is more appropriate
```
