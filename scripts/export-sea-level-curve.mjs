#!/usr/bin/env node

import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');
const outputPath = path.join(
  repoRoot,
  'frontend',
  'data',
  'sea-level',
  'california-demo-default.json',
);

const DEFAULT_CATALOG = process.env.DATABRICKS_CATALOG ?? 'main';
const DEFAULT_SCHEMA = process.env.DATABRICKS_SCHEMA ?? 'sawjess';
const DEFAULT_VIEW = process.env.DATABRICKS_VIEW ?? 'sea_level_demo_curve';
const DEFAULT_QUERY = `
  SELECT
    year,
    absolute_msl_m,
    rise_from_2000_m,
    rise_from_2026_m,
    is_extrapolated,
    source_station_id,
    curve_id
  FROM ${DEFAULT_CATALOG}.${DEFAULT_SCHEMA}.${DEFAULT_VIEW}
  ORDER BY year
`;

function getRequiredEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }

  return value;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeHost(host) {
  return host.startsWith('http://') || host.startsWith('https://') ? host : `https://${host}`;
}

function mapResultRows(payload) {
  const columns = payload.manifest?.schema?.columns?.map((column) => column.name) ?? [];
  const rows = payload.result?.data_array ?? [];

  return rows.map((values) =>
    Object.fromEntries(columns.map((column, index) => [column, values[index]])),
  );
}

async function fetchAllStatementRows(statementId, host, headers, initialPayload) {
  const rows = [...mapResultRows(initialPayload)];
  let nextChunkPath = initialPayload.result?.next_chunk_internal_link ?? null;

  while (nextChunkPath) {
    const response = await fetch(`${host}${nextChunkPath}`, { headers });
    if (!response.ok) {
      throw new Error(`Failed to fetch result chunk: ${response.status} ${response.statusText}`);
    }

    const payload = await response.json();
    rows.push(...mapResultRows(payload));
    nextChunkPath = payload.next_chunk_internal_link ?? null;
  }

  return rows;
}

async function queryDatabricks() {
  if (process.env.SEA_LEVEL_EXPORT_INPUT_JSON) {
    const sourcePath = path.resolve(repoRoot, process.env.SEA_LEVEL_EXPORT_INPUT_JSON);
    const raw = JSON.parse(await readFile(sourcePath, 'utf8'));
    return Array.isArray(raw) ? raw : raw.records ?? [];
  }

  const host = normalizeHost(getRequiredEnv('DATABRICKS_HOST'));
  const token = getRequiredEnv('DATABRICKS_TOKEN');
  const warehouseId = getRequiredEnv('DATABRICKS_WAREHOUSE_ID');
  const headers = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  const response = await fetch(`${host}/api/2.0/sql/statements`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      warehouse_id: warehouseId,
      statement: process.env.SEA_LEVEL_EXPORT_QUERY ?? DEFAULT_QUERY,
      disposition: 'INLINE',
      format: 'JSON_ARRAY',
      wait_timeout: '30s',
    }),
  });

  if (!response.ok) {
    throw new Error(`Databricks statement submission failed: ${response.status} ${response.statusText}`);
  }

  let payload = await response.json();
  const statementId = payload.statement_id;
  let state = payload.status?.state;

  while (state === 'PENDING' || state === 'RUNNING') {
    await sleep(1000);

    const pollResponse = await fetch(`${host}/api/2.0/sql/statements/${statementId}`, {
      headers,
    });

    if (!pollResponse.ok) {
      throw new Error(`Databricks statement polling failed: ${pollResponse.status} ${pollResponse.statusText}`);
    }

    payload = await pollResponse.json();
    state = payload.status?.state;
  }

  if (state !== 'SUCCEEDED') {
    throw new Error(`Databricks statement ended in state ${state ?? 'UNKNOWN'}`);
  }

  return fetchAllStatementRows(statementId, host, headers, payload);
}

function normalizeBoolean(value) {
  if (typeof value === 'boolean') {
    return value;
  }

  if (typeof value === 'string') {
    return value.toLowerCase() === 'true';
  }

  return Boolean(value);
}

function normalizeRows(rows) {
  return rows.map((row) => ({
    year: Number(row.year),
    absoluteMslMeters: Number(row.absolute_msl_m ?? row.absoluteMslMeters),
    riseFrom2000Meters: Number(row.rise_from_2000_m ?? row.riseFrom2000Meters),
    riseFrom2026Meters: Number(row.rise_from_2026_m ?? row.riseFrom2026Meters),
    isExtrapolated: normalizeBoolean(row.is_extrapolated ?? row.isExtrapolated),
  }));
}

function validateRows(records) {
  if (!records.length) {
    throw new Error('Sea-level export returned no rows.');
  }

  const baseline = records.find((record) => record.year === 2026);
  if (!baseline) {
    throw new Error('Sea-level export is missing the 2026 baseline year.');
  }

  if (baseline.riseFrom2026Meters !== 0) {
    throw new Error(`Expected riseFrom2026Meters to equal 0 for 2026, received ${baseline.riseFrom2026Meters}.`);
  }

  for (let year = 2026; year <= 2100; year += 1) {
    if (!records.find((record) => record.year === year)) {
      throw new Error(`Sea-level export is missing year ${year}.`);
    }
  }

  for (let index = 1; index < records.length; index += 1) {
    const previous = records[index - 1];
    const current = records[index];

    if (current.year <= previous.year) {
      throw new Error(`Years must be strictly increasing. Found ${previous.year} followed by ${current.year}.`);
    }

    if (!current.isExtrapolated && current.year > 2026 && current.riseFrom2026Meters < 0) {
      throw new Error(`Negative non-extrapolated rise detected at ${current.year}.`);
    }

    if (
      !current.isExtrapolated &&
      !previous.isExtrapolated &&
      current.year > 2026 &&
      current.riseFrom2026Meters < previous.riseFrom2026Meters
    ) {
      throw new Error(`Non-monotonic non-extrapolated rise detected between ${previous.year} and ${current.year}.`);
    }
  }
}

async function main() {
  const rows = await queryDatabricks();
  const records = normalizeRows(rows);
  validateRows(records);

  const payload = {
    curveId: 'california-demo-default',
    projectName: 'SAWJESS',
    sourceLabel: process.env.SEA_LEVEL_SOURCE_LABEL ?? 'NOAA monthly mean sea level forecast processed in Databricks',
    sourceRegionLabel:
      process.env.SEA_LEVEL_SOURCE_REGION_LABEL ?? 'California demo curve applied to all scenes',
    sourceStationId: String(rows[0]?.source_station_id ?? process.env.SEA_LEVEL_SOURCE_STATION_ID ?? '9410230'),
    baselineYearScientific: 2000,
    baselineYearUi: 2026,
    aggregation: 'calendar_year_mean',
    extrapolationMethod: 'ols_last_10_years',
    records,
  };

  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`);

  console.log(`Wrote ${records.length} annual sea-level records to ${outputPath}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
