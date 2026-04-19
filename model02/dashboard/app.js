'use strict';

// ── Data paths ────────────────────────────────────────────────────────
const DATA = {
  monthly:    '../data/predictions/sojs_monthly_predictions.csv',
  projections:'../data/projections/sojs_portland_annual_projections.csv',
  training:   '../data/annual/sojs_portland_annual_training.csv',
  nao:        '../data/nao/nao_monthly.csv',
  skill:      '../plots/hindcast/sojs_hindcast_skill_table.csv',
  validation: '../data/predictions/sojs_prediction_validation_summary.csv',
};

// ── Palette ───────────────────────────────────────────────────────────
const C = {
  portland:     '#1d4ed8',
  barHarbor:    '#dc2626',
  constrained:  '#15803d',
  continuation: '#c2410c',
  extrapolation:'#7e22ce',
  greenland:    '#0f766e',
  historical:   '#9ca3af',
  grid:         '#f0f0f0',
};

const REGIME_COLOR = {
  constrained_reconstruction: C.constrained,
  validated_continuation:     C.continuation,
  pure_extrapolation:         C.extrapolation,
};

// ── Date → decimal year (no date-fns dependency) ──────────────────────
function toY(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const doy = (Date.UTC(y, m - 1, d) - Date.UTC(y, 0, 1)) / 86400000;
  const daysInYear = ((y % 4 === 0 && y % 100 !== 0) || y % 400 === 0) ? 366 : 365;
  return y + doy / daysInYear;
}

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function decYearLabel(v) {
  const y = Math.floor(v);
  const m = Math.min(Math.round((v - y) * 12), 11);
  return `${MONTHS[m]} ${y}`;
}

function fmt(v, decimals = 3) {
  return v != null ? (+v).toFixed(decimals) : '—';
}

function pearsonR(points) {
  if (points.length < 2) return null;
  const meanX = points.reduce((acc, p) => acc + p.x, 0) / points.length;
  const meanY = points.reduce((acc, p) => acc + p.y, 0) / points.length;

  let num = 0;
  let denX = 0;
  let denY = 0;
  for (const p of points) {
    const dx = p.x - meanX;
    const dy = p.y - meanY;
    num += dx * dy;
    denX += dx * dx;
    denY += dy * dy;
  }
  if (denX === 0 || denY === 0) return null;
  return num / Math.sqrt(denX * denY);
}

function setPredictionTitles(station) {
  document.getElementById('pred-chart-title').textContent =
    `${station} - predicted vs observed monthly sea level`;
  document.getElementById('pred-error-title').textContent =
    `${station} - monthly residual (actual - expected)`;
}

// ── CSV loader ────────────────────────────────────────────────────────
function loadCSV(url) {
  return new Promise((resolve, reject) => {
    Papa.parse(url, {
      download: true,
      header: true,
      dynamicTyping: true,
      skipEmptyLines: true,
      complete: r => resolve(r.data),
      error: err => reject(new Error(`${url}: ${err}`)),
    });
  });
}

// ── Chart.js global defaults ──────────────────────────────────────────
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.font.size   = 11;
Chart.defaults.color       = '#6b7280';
Chart.defaults.animation   = false;
Chart.defaults.plugins.legend.labels.boxWidth       = 10;
Chart.defaults.plugins.legend.labels.padding        = 14;
Chart.defaults.plugins.legend.labels.usePointStyle  = true;

// Shared linear x-axis config (decimal years or plain integers)
function xAxis(extra = {}) {
  return {
    type: 'linear',
    grid: { color: C.grid },
    ticks: { maxTicksLimit: 8, callback: v => String(Math.round(v)) },
    ...extra,
  };
}

// Tooltip preset: mode:'x' finds items by x-VALUE proximity across all
// datasets (not by array index), so datasets of different lengths align
// correctly. filter drops the hidden band-boundary datasets.
function tooltipX(callbacks = {}) {
  return {
    mode: 'x',
    axis: 'x',
    intersect: false,
    filter: item => !item.dataset.label.startsWith('_'),
    callbacks: {
      title: items => items.length ? String(Math.round(items[0].parsed.x)) : '',
      ...callbacks,
    },
  };
}

// ── Lazy chart renderer via IntersectionObserver ──────────────────────
function lazyChart(canvasId, renderFn) {
  const el = document.getElementById(canvasId);
  if (!el) return;
  const obs = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting) { obs.disconnect(); renderFn(); }
  }, { rootMargin: '200px' });
  obs.observe(el);
}

// ── Global state ──────────────────────────────────────────────────────
let activeStation = 'Bar Harbor';
let predChart     = null;
let predErrorChart = null;
let allMonthly    = null;
let allValidation = null;

// ── Entry point ───────────────────────────────────────────────────────
async function init() {
  try {
    const [monthly, projections, training, nao, skill, validation] = await Promise.all([
      loadCSV(DATA.monthly),
      loadCSV(DATA.projections),
      loadCSV(DATA.training),
      loadCSV(DATA.nao),
      loadCSV(DATA.skill),
      loadCSV(DATA.validation),
    ]);

    allMonthly    = monthly;
    allValidation = validation;

    // Pre-compute all derived series once
    const annualNao       = computeAnnualNao(nao);
    const annualGreenland = computeAnnualGreenland(training);
    const portlandAnnual  = computePortlandAnnual(training);
    const barHarborAnnual = computeBarHarborAnnual(monthly);

    // First section is visible on load — render immediately
    renderSeaLevelChart(portlandAnnual, barHarborAnnual);

    // Remaining charts are lazy — render only when scrolled into view
    lazyChart('chart-nao',        () => renderNaoChart(annualNao));
    lazyChart('chart-greenland',  () => renderGreenlandChart(annualGreenland));
    lazyChart('chart-skill',      () => renderSkillChart(skill));
    lazyChart('chart-predictions', () => {
      renderValidationTable(validation);
      setPredictionTitles(activeStation);
      renderPredictionSection(monthly, activeStation);
      renderPredictionStats(validation, activeStation);
    });
    lazyChart('chart-projection', () => {
      renderProjectionChart(portlandAnnual, projections);
      renderProjectionStats(projections);
    });

    document.querySelectorAll('.tab').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        btn.classList.add('active');
        activeStation = btn.dataset.station;
        document.getElementById('pred-chart-title').textContent =
          `${activeStation} — predicted vs observed monthly sea level`;
        document.getElementById('pred-error-title').textContent =
          `${activeStation} â€” monthly error (actual - expected)`;
        document.getElementById('pred-error-title').textContent =
          `${activeStation} - monthly error (actual - expected)`;
        setPredictionTitles(activeStation);
        renderPredictionSection(allMonthly, activeStation);
        renderPredictionStats(allValidation, activeStation);
      });
    });

  } catch (err) {
    console.error('Dashboard load error:', err);
    document.querySelector('#hero .abstract').insertAdjacentHTML('afterend',
      `<p style="color:#dc2626;margin-top:16px;font-size:13px;padding:12px;
         background:#fef2f2;border-radius:6px;border:1px solid #fecaca">
        ⚠ Could not load data. Run
        <code style="font-family:monospace">python -m http.server 8000</code>
        from <code style="font-family:monospace">model02/</code> and open
        <code style="font-family:monospace">http://localhost:8000/dashboard/</code>.
      </p>`
    );
  }
}

// ── Pre-compute helpers ───────────────────────────────────────────────

function computeAnnualNao(nao) {
  const byYear = {};
  nao.forEach(d => {
    if (d.year < 1950 || d.nao == null) return;
    (byYear[d.year] = byYear[d.year] || []).push(d.nao);
  });
  return Object.entries(byYear)
    .map(([y, v]) => ({ x: +y, y: +(v.reduce((a,b)=>a+b,0)/v.length).toFixed(3) }))
    .sort((a,b) => a.x - b.x);
}

function computeAnnualGreenland(training) {
  return training
    .filter(d => d.greenland_mass_gt != null && +d.months_present_greenland_mass_gt > 0)
    .map(d => ({ x: +d.year, y: +d.greenland_mass_gt }));
}

function computePortlandAnnual(training) {
  return training
    .filter(d => d.portland_msl_m != null && +d.months_present_portland_msl_m >= 9)
    .map(d => ({ x: +d.year, y: +d.portland_msl_m }));
}

function computeBarHarborAnnual(monthly) {
  const byYear = {};
  monthly
    .filter(d => d.station_name === 'Bar Harbor' && d.has_observation && d.observed_m != null)
    .forEach(d => {
      const y = +d.time.slice(0, 4);
      (byYear[y] = byYear[y] || []).push(+d.observed_m);
    });
  return Object.entries(byYear)
    .filter(([, v]) => v.length >= 9)
    .map(([y, v]) => ({ x: +y, y: +(v.reduce((a,b)=>a+b,0)/v.length).toFixed(4) }))
    .sort((a,b) => a.x - b.x);
}

// ── 01 Sea level history ──────────────────────────────────────────────
// Portland: annual means 1912–2026 (~113 pts). Bar Harbor: annual means
// from predictions CSV 2004–2024 (~20 pts). mode:'x' aligns them by
// x-value so different-length datasets don't cross-index incorrectly.
function renderSeaLevelChart(portlandAnnual, barHarborAnnual) {
  const ctx = document.getElementById('chart-sealevel').getContext('2d');
  new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [
        {
          label: 'Portland (annual mean)',
          data: portlandAnnual,
          borderColor: C.portland,
          borderWidth: 1.5,
          pointRadius: 2,
          pointHoverRadius: 5,
          tension: 0.25,
          fill: false,
        },
        {
          label: 'Bar Harbor (annual mean)',
          data: barHarborAnnual,
          borderColor: C.barHarbor,
          borderWidth: 1.5,
          pointRadius: 2,
          pointHoverRadius: 5,
          tension: 0.25,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      parsing: false,
      scales: {
        x: xAxis(),
        y: { title: { display: true, text: 'MSL anomaly (m)' }, grid: { color: C.grid } },
      },
      plugins: {
        legend: { position: 'top', align: 'end' },
        tooltip: tooltipX({
          label: item => `${item.dataset.label}: ${fmt(item.parsed.y)} m`,
        }),
      },
    },
  });
}

// ── 02a NAO annual index ──────────────────────────────────────────────
function renderNaoChart(annualNao) {
  const ctx = document.getElementById('chart-nao').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      datasets: [{
        label: 'Annual mean NAO',
        data: annualNao,
        backgroundColor: annualNao.map(d => d.y >= 0 ? 'rgba(29,78,216,0.72)' : 'rgba(220,38,38,0.72)'),
        borderWidth: 0,
        borderRadius: 1,
      }],
    },
    options: {
      responsive: true,
      parsing: false,
      scales: {
        x: xAxis(),
        y: { title: { display: true, text: 'NAO index' }, grid: { color: C.grid } },
      },
      plugins: {
        legend: { display: false },
        // Bar charts work best with mode:'index'; single dataset so no
        // length-mismatch issue. Use nearest for single-dataset clarity.
        tooltip: {
          mode: 'nearest',
          intersect: false,
          callbacks: {
            title: items => items.length ? String(items[0].raw.x) : '',
            label: item => `NAO: ${fmt(item.parsed.y, 2)}`,
          },
        },
      },
    },
  });
}

// ── 02b Greenland mass ────────────────────────────────────────────────
function renderGreenlandChart(annualGreenland) {
  const ctx = document.getElementById('chart-greenland').getContext('2d');
  new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [{
        label: 'Greenland mass anomaly (Gt)',
        data: annualGreenland,
        borderColor: C.greenland,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 5,
        tension: 0.35,
        fill: { target: 'origin', below: 'rgba(15,118,110,0.18)', above: 'rgba(15,118,110,0.04)' },
      }],
    },
    options: {
      responsive: true,
      parsing: false,
      scales: {
        x: xAxis({ ticks: { maxTicksLimit: 6, callback: v => String(Math.round(v)) } }),
        y: { title: { display: true, text: 'Mass anomaly (Gt)' }, grid: { color: C.grid } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'nearest',
          intersect: false,
          callbacks: {
            title: items => items.length ? String(items[0].raw.x) : '',
            label: item => `Mass: ${fmt(item.parsed.y, 0)} Gt`,
          },
        },
      },
    },
  });
}

// ── 03a Skill chart ───────────────────────────────────────────────────
function renderSkillChart(skill) {
  const ORDER  = ['persistence','trend_only','ols_reduced','ols_reduced_detrended','ols_with_argo_ridge'];
  const LABELS = {
    persistence:           'Persistence',
    trend_only:            'Trend only',
    ols_reduced:           'OLS reduced',
    ols_reduced_detrended: 'OLS detrended',
    ols_with_argo_ridge:   '★  Ridge + Argo (final)',
  };
  const isFinal = d => d.is_final_model === true || d.is_final_model === 'True';

  const portland  = ORDER.map(m => skill.find(d => d.station === 'Portland'   && d.model === m)).filter(Boolean);
  const barHarbor = ORDER.map(m => skill.find(d => d.station === 'Bar Harbor' && d.model === m)).filter(Boolean);

  const ctx = document.getElementById('chart-skill').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: portland.map(d => LABELS[d.model] || d.model),
      datasets: [
        {
          label: 'Portland RMSE (m)',
          data: portland.map(d => +d.rmse_m.toFixed(4)),
          backgroundColor: portland.map(d => isFinal(d) ? C.portland : 'rgba(29,78,216,0.22)'),
          borderColor:     portland.map(d => isFinal(d) ? C.portland : 'rgba(29,78,216,0.4)'),
          borderWidth: 1, borderRadius: 3, borderSkipped: false,
        },
        {
          label: 'Bar Harbor RMSE (m)',
          data: barHarbor.map(d => +d.rmse_m.toFixed(4)),
          backgroundColor: barHarbor.map(d => isFinal(d) ? C.barHarbor : 'rgba(220,38,38,0.22)'),
          borderColor:     barHarbor.map(d => isFinal(d) ? C.barHarbor : 'rgba(220,38,38,0.4)'),
          borderWidth: 1, borderRadius: 3, borderSkipped: false,
        },
      ],
    },
    options: {
      responsive: true,
      indexAxis: 'y',
      scales: {
        x: { title: { display: true, text: 'RMSE (m)' }, grid: { color: C.grid } },
        y: { grid: { display: false } },
      },
      plugins: {
        legend: { position: 'top', align: 'end' },
        // Skill chart uses categorical labels (not x-value matching), so
        // mode:'index' is correct here — same number of items per dataset.
        tooltip: { mode: 'index', intersect: false },
      },
    },
  });
}

// ── 03b Validation table ──────────────────────────────────────────────
function renderValidationTable(validation) {
  const badgeClass = { constrained_reconstruction:'badge-constrained', validated_continuation:'badge-continuation', pure_extrapolation:'badge-extrapolation' };
  const badgeName  = { constrained_reconstruction:'Constrained', validated_continuation:'Continuation', pure_extrapolation:'Extrapolation' };

  document.getElementById('validation-table').innerHTML = `
    <table>
      <thead><tr>
        <th>Station</th><th>Regime</th><th>Obs.</th>
        <th>RMSE (m)</th><th>MAE (m)</th><th>Bias (m)</th><th>R²</th>
      </tr></thead>
      <tbody>${validation.map(d => `
        <tr class="${d.regime_label === 'constrained_reconstruction' ? 'highlight' : ''}">
          <td>${d.station_name}</td>
          <td><span class="badge-regime ${badgeClass[d.regime_label]||''}">${badgeName[d.regime_label]||d.regime_label}</span></td>
          <td>${d.observed_months}</td>
          <td>${fmt(d.rmse_m, 4)}</td>
          <td>${fmt(d.mae_m, 4)}</td>
          <td>${fmt(d.bias_m, 4)}</td>
          <td>${fmt(d.r_squared, 3)}</td>
        </tr>`).join('')}
      </tbody>
    </table>`;
}

// ── 04 Monthly predictions ────────────────────────────────────────────
// Observations exist only for some months. Storing obs as a property on
// each predicted point lets the Predicted tooltip show both values while
// a separate observed line can render visible segments with gaps where
// observations are unavailable.
function renderPredictionSection(monthly, station) {
  renderPredictionsChart(monthly, station);
  renderPredictionErrorChart(monthly, station);
}

function renderPredictionsChart(monthly, station) {
  const rows = monthly.filter(d => d.station_name === station);

  // Attach observed value as property so the Predicted tooltip can show it
  const pred  = rows.map(d => ({
    x: toY(d.time),
    y: +d.predicted_m,
    obs: (d.has_observation && d.observed_m != null) ? +d.observed_m : null,
    regime: d.regime_label,
  }));
  const upper = rows.map(d => ({ x: toY(d.time), y: +d.predicted_upper_1sigma_m }));
  const lower = rows.map(d => ({ x: toY(d.time), y: +d.predicted_lower_1sigma_m }));

  const obs = rows.map(d => ({
    x: toY(d.time),
    y: (d.has_observation && d.observed_m != null) ? +d.observed_m : null,
  }));

  const ctx = document.getElementById('chart-predictions').getContext('2d');
  if (predChart) predChart.destroy();

  predChart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [
        { label: '_upper', data: upper, borderWidth: 0, pointRadius: 0, fill: false, borderColor: 'transparent' },
        {
          label: '±1σ band',
          data: lower,
          borderWidth: 0, pointRadius: 0,
          fill: '-1',
          backgroundColor: 'rgba(99,132,255,0.10)',
          borderColor: 'transparent',
        },
        {
          label: 'Predicted',
          data: pred,
          borderWidth: 2, pointRadius: 0, pointHoverRadius: 0,
          fill: false, tension: 0.2,
          borderColor: C.portland,
          segment: {
            borderColor: ctx => REGIME_COLOR[pred[ctx.p1DataIndex]?.regime] || C.portland,
          },
        },
        {
          label: 'Observed',
          data: obs,
          borderWidth: 1.5,
          pointRadius: 0,
          pointHoverRadius: 0,
          fill: false,
          spanGaps: false,
          tension: 0.15,
          borderColor: 'rgba(15, 23, 42, 0.65)',
        },
      ],
    },
    options: {
      responsive: true,
      parsing: false,
      scales: {
        x: xAxis(),
        y: { title: { display: true, text: 'Sea level (m)' }, grid: { color: C.grid } },
      },
      plugins: {
        legend: {
          position: 'top', align: 'end',
          labels: { filter: item => !item.text.startsWith('_') },
        },
        tooltip: tooltipX({
          title: items => items.length ? decYearLabel(items[0].parsed.x) : '',
          label: item => {
            if (item.dataset.label === '_upper') return null;
            if (item.dataset.label === '±1σ band') {
              // Show band as a range rather than one boundary
              const ub = pred[item.dataIndex];
              if (!ub) return null;
              return `±1σ: ${fmt(item.parsed.y)} – ${fmt(ub.y + (ub.y - item.parsed.y))} m`;
            }
            if (item.dataset.label === 'Predicted') {
              const pt = pred[item.dataIndex];
              const lines = [`Predicted: ${fmt(pt.y)} m`];
              if (pt.obs != null) lines.push(`Observed:  ${fmt(pt.obs)} m`);
              return lines;
            }
            if (item.dataset.label === 'Observed') {
              return `Observed: ${fmt(item.parsed.y)} m`;
            }
            return null;
          },
          filter: item => !item.dataset.label.startsWith('_'),
        }),
      },
    },
  });
}

// ── 04 Prediction stats ───────────────────────────────────────────────
function renderPredictionErrorChart(monthly, station) {
  const rows = monthly.filter(d => d.station_name === station);
  const observedRows = rows.filter(d => d.has_observation && d.observed_m != null);
  const error = observedRows.map(d => ({
    x: toY(d.time),
    y: +d.observed_m - +d.predicted_m,
  }));
  const observedVsPredicted = observedRows.map(d => ({
    x: +d.predicted_m,
    y: +d.observed_m,
  }));
  const zero = error.map(d => ({ x: d.x, y: 0 }));
  const coeff = pearsonR(observedVsPredicted);
  const meta = document.getElementById('pred-error-meta');

  meta.textContent = coeff == null
    ? 'Observed-month alignment coefficient unavailable'
    : `Observed-month alignment coefficient: r = ${fmt(coeff, 3)} (${error.length} months). This supports timing and trend capture even when the modeled swings run somewhat large.`;

  const ctx = document.getElementById('chart-prediction-error').getContext('2d');
  if (predErrorChart) predErrorChart.destroy();

  predErrorChart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [
        {
          label: '_zero',
          data: zero,
          borderWidth: 1,
          pointRadius: 0,
          pointHoverRadius: 0,
          fill: false,
          borderColor: 'rgba(148, 163, 184, 0.85)',
          borderDash: [5, 5],
        },
        {
          label: 'Residual',
          data: error,
          borderWidth: 1.8,
          pointRadius: 0,
          pointHoverRadius: 0,
          fill: false,
          tension: 0.15,
          borderColor: station === 'Portland' ? C.portland : C.barHarbor,
        },
      ],
    },
    options: {
      responsive: true,
      parsing: false,
      scales: {
        x: xAxis(),
        y: {
          title: { display: true, text: 'Actual - expected (m)' },
          grid: { color: C.grid },
        },
      },
      plugins: {
        legend: {
          position: 'top', align: 'end',
          labels: { filter: item => !item.text.startsWith('_') },
        },
        tooltip: tooltipX({
          title: items => items.length ? decYearLabel(items[0].parsed.x) : '',
          label: item => {
            if (item.dataset.label === '_zero') return null;
            return `Residual: ${fmt(item.parsed.y)} m`;
          },
        }),
      },
    },
  });
}

function renderPredictionStats(validation, station) {
  const rows = validation.filter(d => d.station_name === station);
  const cr   = rows.find(d => d.regime_label === 'constrained_reconstruction');
  const cont = rows.find(d => d.regime_label === 'validated_continuation');
  const weak = station === 'Portland';

  document.getElementById('prediction-stats').innerHTML = `
    <div class="pstat ${cr ? 'strong' : ''}">
      <span class="pstat-label">Constrained RMSE</span>
      <span class="pstat-value">${cr ? (cr.rmse_m * 1000).toFixed(1) + ' mm' : '—'}</span>
      <span class="pstat-sub">2004–2017 · 40 months</span>
    </div>
    <div class="pstat ${cr && cr.r_squared > 0.7 ? 'strong' : ''}">
      <span class="pstat-label">Constrained R²</span>
      <span class="pstat-value">${cr ? fmt(cr.r_squared) : '—'}</span>
      <span class="pstat-sub">Ridge OLS cross-validation</span>
    </div>
    <div class="pstat ${weak ? 'weak' : ''}">
      <span class="pstat-label">Continuation RMSE</span>
      <span class="pstat-value">${cont ? (cont.rmse_m * 1000).toFixed(1) + ' mm' : '—'}</span>
      <span class="pstat-sub">2018+ · GRACE-FO substitution</span>
    </div>
    <div class="pstat ${weak ? 'weak' : ''}">
      <span class="pstat-label">Continuation R²</span>
      <span class="pstat-value">${cont ? fmt(cont.r_squared) : '—'}</span>
      <span class="pstat-sub">${weak ? 'Weak — treat with caution' : 'Defensible continuation'}</span>
    </div>`;
}

// ── 05 Century projection ─────────────────────────────────────────────
// Same fix: mode:'x' aligns historical (~113 pts) with projection paths
// (~100 pts each) by x-value, not by array index.
function renderProjectionChart(portlandAnnual, projections) {
  const byScenario = s => projections.filter(d => d.scenario === s).map(d => ({ x: +d.year, y: +d.predicted_m }));
  const baseline = byScenario('baseline');
  const low      = byScenario('low');
  const high     = byScenario('high');
  const lower80  = projections.filter(d => d.scenario === 'baseline').map(d => ({ x: +d.year, y: +d.predicted_lower_80_m }));
  const upper80  = projections.filter(d => d.scenario === 'baseline').map(d => ({ x: +d.year, y: +d.predicted_upper_80_m }));

  const ctx = document.getElementById('chart-projection').getContext('2d');
  new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [
        { label: '_upper80', data: upper80, borderWidth: 0, pointRadius: 0, fill: false, borderColor: 'transparent' },
        {
          label: '80% interval',
          data: lower80,
          borderWidth: 0, pointRadius: 0,
          fill: '-1',
          backgroundColor: 'rgba(29,78,216,0.09)',
          borderColor: 'transparent',
        },
        {
          label: 'Historical (observed)',
          data: portlandAnnual,
          borderColor: C.historical,
          borderWidth: 1.5,
          pointRadius: 2,
          pointHoverRadius: 5,
          pointBackgroundColor: C.historical,
          fill: false, tension: 0.2,
        },
        {
          label: 'Baseline (sim. mean)',
          data: baseline,
          borderColor: C.portland,
          borderWidth: 2.5,
          pointRadius: 0, pointHoverRadius: 4,
          fill: false, tension: 0.35,
        },
        {
          label: 'Low (p25)',
          data: low,
          borderColor: C.portland,
          borderWidth: 1.5,
          borderDash: [5, 4],
          pointRadius: 0, pointHoverRadius: 4,
          fill: false, tension: 0.35,
        },
        {
          label: 'High (p75)',
          data: high,
          borderColor: C.portland,
          borderWidth: 1.5,
          borderDash: [5, 4],
          pointRadius: 0, pointHoverRadius: 4,
          fill: false, tension: 0.35,
        },
      ],
    },
    options: {
      responsive: true,
      parsing: false,
      scales: {
        x: xAxis({ title: { display: true, text: 'Year' }, ticks: { maxTicksLimit: 10, callback: v => String(Math.round(v)) } }),
        y: { title: { display: true, text: 'Annual-average sea level (m)' }, grid: { color: C.grid } },
      },
      plugins: {
        legend: {
          position: 'top', align: 'end',
          labels: { filter: item => !item.text.startsWith('_') },
        },
        tooltip: tooltipX({
          title: items => items.length ? String(Math.round(items[0].parsed.x)) : '',
          label: item => {
            if (item.dataset.label.startsWith('_')) return null;
            return `${item.dataset.label}: ${fmt(item.parsed.y)} m`;
          },
          filter: item => !item.dataset.label.startsWith('_'),
        }),
      },
    },
  });
}

// ── 05 Projection stats ───────────────────────────────────────────────
function renderProjectionStats(projections) {
  const at2126 = s => projections.find(d => d.scenario === s && d.year === 2126);
  const b = at2126('baseline'), lo = at2126('low'), hi = at2126('high');
  const cm = v => v != null ? `${(+v * 100).toFixed(1)} cm` : '—';

  document.getElementById('projection-stats').innerHTML = `
    <div class="proj-row"><span class="label">Selected model</span><span class="value">trend_plus_nao</span></div>
    <div class="proj-row"><span class="label">Predictors</span><span class="value">NAO annual + winter DJF + lags</span></div>
    <div class="proj-row"><span class="label">Trend slope</span><span class="value">2.86 mm / yr</span></div>
    <div class="proj-row"><span class="label">Residual σ (annual)</span><span class="value">31.4 mm</span></div>
    <div class="proj-row"><span class="label">AR(1) persistence ρ</span><span class="value">0.589</span></div>
    <div class="proj-row"><span class="label">Bootstrap simulations</span><span class="value">4,000</span></div>
    <div class="proj-row"><span class="label">2126 baseline</span><span class="value">${b ? cm(b.predicted_m) : '—'}</span></div>
    <div class="proj-row"><span class="label">2126 low / high (p25–p75)</span><span class="value">${lo ? cm(lo.predicted_m) : '—'} – ${hi ? cm(hi.predicted_m) : '—'}</span></div>
    <div class="proj-row"><span class="label">2126 80% interval</span><span class="value">${b ? cm(b.predicted_lower_80_m) + ' – ' + cm(b.predicted_upper_80_m) : '—'}</span></div>`;
}

// ── Boot ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
