## Sojs (Spatiotemporal Oceanographic Sea-level Journal)

**Sojs** is a **voice-guided, 3D sea-level rise explorer** backed by a locally-calibrated prediction model: you open a real place reconstructed as a **point cloud / Gaussian splat**, scrub time and scenarios, and **talk to the scene**. The visualizer is the front-end experience. The model is the brains.

---

### Inspiration

Sea-level rise is communicated as global averages and static maps. Neither helps a harbor engineer in Rockland, Maine decide whether to raise a pier by 0.4 meters or 1.1 meters. We wanted something closer to **standing in place** — a real 3D capture you can orbit, a timeline driven by a model calibrated to that specific coastline, and a voice interface so anyone can ask *"what floods first here"* without hunting through UI. The goal is to make abstract climate numbers feel **spatial and personal**.

---

### What It Does

- **Location dashboard** — Cards for multiple saved scenes (Seattle Waterfront, Bar Harbor, Maine) with scenario labels and deep links into the viewer.
- **3D viewport** — `SplatViewer` loads `.ply` / Gaussian splat assets in the browser via Three.js. You orbit, zoom, and fly to named hotspots by voice or click.
- **Time & scenarios** — Discrete **baseline / mid-century / end-of-century** steps with rise in meters, driving a water overlay and on-screen metrics. Rise values come from the regional prediction model.
- **Voice loop** — AssemblyAI streaming speech-to-text via a short-lived Next.js token; rule-based intents drive **camera moves, scenario switches, compare mode, hazard narration, and source attribution** in response to natural commands like *"show 2075"* or *"compare now and 2100."*
- **Hotspots** — Named camera poses and aliases ("pier," "ferry terminal") so voice commands match how people actually describe a waterfront.
- **Hazard scan** — Severity-ranked geometric markers from `hazardsUrl` JSON; `/api/hazards/analyze` optionally calls NVIDIA's chat API to narrate findings, with deterministic fallbacks when keys or data are absent.

---

### The Prediction Model

The scenario numbers driving the visualizer come from a regionally-calibrated sea-level model built from scratch for coastal Maine — not global averages.

**We didn't start here.** The first model targeted La Jolla, CA using Scripps CalCOFI hydrographic profiles and the Argo global float network as forecasting predictors. Seven iterations later — dense neural networks, residual heads, inner-join / left-join Argo experiments — the best result was a tie with a one-line persistence baseline (NN RMSE 0.0202 m vs. persistence 0.0194 m). The data was honest with us: monthly sea-level anomaly at a single station at 1–3 month horizons is near the predictability limit, and Argo heat content correlates with sea level contemporaneously, not as a lead.

**What the iterations taught us:**
- Data coverage beats model complexity — extending training from 80 to 327 windows (by including 1982–83 and 1997–98 El Niños) did more than any architecture change
- Distribution shift is silent and catastrophic — a binary Argo-availability mask sent validation inputs out-of-distribution and tripled RMSE
- When a predictor doesn't lead the target, adding it is noise

**So we pivoted.** We shifted the target from short-horizon forecasting to long-horizon reconstruction and projection, shifted the geography to coastal Maine (where Portland's tide gauge runs back to 1912 and the NAO provides a 75-year atmospheric driver), and replaced neural networks with ridge-regularized OLS — interpretable, sample-efficient, and cross-validatable on the 40-month Argo-overlap window. The Scripps EasyOneArgo float data stayed in the pipeline, but in the right role: as a **calibration constraint and regime gate** rather than a forecasting predictor.

**The result:** R² = 0.861 on the calibration window. Beats trend-only on rolling 5-year and 10-year out-of-sample holdouts. Century-scale projections for Portland with 80% uncertainty envelopes that widen honestly with lead time. Every output month carries a regime label — *constrained reconstruction*, *validated continuation*, or *extrapolation* — so the visualizer can show users exactly what kind of estimate they're looking at.

---

### How We Built It

| Layer | Choice |
|---|---|
| App | **Next.js 16** (App Router), **React 19**, **TypeScript** |
| 3D | **Three.js**, **PLYLoader**, Gaussian splat support |
| Styling | **Tailwind v4** + custom CSS for shell, panels, water overlay |
| Speech in | **AssemblyAI** streaming via short-lived server token |
| Speech out | Browser TTS via `useVoicePlayback` / `VoiceAssistantBar` |
| Voice behavior | Rule-based intent catalog — predictable commands, not open-ended LLM |
| Hazard analysis | **NVIDIA** chat completions + JSON extraction, with offline fallback |
| Prediction model | **Python** — ridge OLS, `xarray`, `numpy`, `pandas`, Copernicus Marine, NASA PO.DAAC, NOAA CO-OPS, Scripps EasyOneArgo |
| Model dashboard | Vanilla HTML / Chart.js 4 / PapaParse — no build step |

---

### Challenges

- **Many subsystems, many failure modes** — 3D load errors, mic permissions, STT token expiry, and optional LLM routes each fail differently; fallback copy and visible UI states mattered as much as the happy path.
- **Science communication under time pressure** — connecting plausible scenario numbers to credible attribution without overclaiming. The regime label system (constrained / continuation / extrapolation) is the solution: the app shows *what kind of estimate* is driving the water line, not just a number.
- **Getting Argo right** — three La Jolla iterations used Argo incorrectly. The Maine model uses it correctly. That distinction is the core methodological contribution.
- **Latency and reliability** — voice + 3D needs short commands and visible feedback. The rule-based intent system keeps demo behavior predictable under time pressure.

---

### Accomplishments

- **End-to-end coherence** — dashboard → 3D scene → voice-driven timeline → regime-labeled projections from a validated model, all connected.
- **Voice that actually drives the scene** — hotspots, scenarios, compare mode, and source attribution, not a disconnected chat panel.
- **A model that earns its numbers** — R² = 0.861 on a 40-month out-of-sample calibration window, beats trend-only on rolling holdouts, sources documented, uncertainty bands visible.
- **Honest labeling throughout** — the visualizer surfaces regime labels and uncertainty, not false precision.

---

### What We Learned

- **Transparency beats a black box** — showing regime labels and sources builds trust faster than a prettier water shader.
- **Intent-first voice** beats open-ended LLM for a time-pressured demo — predictable commands reduce failure modes.
- **The right tool for the right problem** — Argo as a calibration gate, ridge OLS over neural networks for a 40-sample window, NAO for century-scale projection. Every architecture choice traces back to something a previous iteration broke.

---

### What's Next

- **Live model API** — wire the visualizer's scenario timeline directly to the prediction model's `SeaLevelFrame` output (year, rise_m, lower_80, upper_80, regime), replacing the current static values.
- **Richer water** — shader-based ocean surface driven by rise values rather than a CSS overlay.
- **More stations** — the model pipeline is portable; any Gulf of Maine station with a modern CO-OPS record can be added. Rockland Harbor is next.
- **Emissions-scenario coupling** — parameterize a scenario-acceleration layer so the visualizer can toggle IPCC AR6 Low / Intermediate / High pathways.
- **Deeper voice** — barge-in, streaming TTS, and longer-form source queries.

---

### Tagline

*"Talk to the shoreline — voice-driven 3D sea-level scenarios, backed by a model that earned its numbers."*
