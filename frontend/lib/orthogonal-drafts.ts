import type {
  GeneratedHotspotDraft,
  GeneratedLocationDraft,
  GeneratedScenarioDraft,
} from '@/lib/orthogonal-types';

const SCENARIO_COLORS = ['#00d4b4', '#38bdf8', '#f97316'];

function quoteString(value: string) {
  return `'${value.replaceAll('\\', '\\\\').replaceAll("'", "\\'")}'`;
}

function slugify(input: string) {
  const slug = input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');

  return slug || 'draft-location';
}

function titleCaseFallback(input: string) {
  const trimmed = input.trim();
  if (!trimmed) {
    return 'Untitled Location';
  }

  return trimmed.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function normalizeHotspot(hotspot: Partial<GeneratedHotspotDraft>, index: number) {
  const name = titleCaseFallback(hotspot.name ?? `Hotspot ${index + 1}`);
  const id = slugify(hotspot.id ?? hotspot.name ?? `hotspot-${index + 1}`);
  const aliases = Array.from(
    new Set([name.toLowerCase(), ...(hotspot.aliases ?? []).map((alias) => alias.trim())].filter(Boolean)),
  );

  return {
    id,
    name,
    aliases,
    description: hotspot.description?.trim() || `Viewpoint ${index + 1} for ${name}.`,
    explainText:
      hotspot.explainText?.trim() ||
      `Showing ${name}. Validate this hotspot against real site imagery before shipping it.`,
  };
}

function normalizeScenario(scenario: Partial<GeneratedScenarioDraft>, index: number) {
  const fallbackYear = index === 0 ? 2026 : index === 1 ? 2050 : 2100;
  const label =
    scenario.label?.trim() ||
    (index === 0 ? 'Baseline' : index === 1 ? 'Mid-Century Draft' : 'End-of-Century Draft');
  const riseMeters =
    typeof scenario.riseMeters === 'number'
      ? Number(scenario.riseMeters.toFixed(2))
      : index === 0
        ? 0
        : index === 1
          ? 0.6
          : 1.8;

  return {
    id: slugify(scenario.id ?? label),
    label,
    year: typeof scenario.year === 'number' ? scenario.year : fallbackYear,
    riseMeters,
    narration:
      scenario.narration?.trim() ||
      `${label} scenario placeholder for Sojs. Replace this with dataset-backed narration before publishing.`,
    color: scenario.color?.trim() || SCENARIO_COLORS[index] || '#7dd3fc',
  };
}

export function normalizeGeneratedLocationDraft(
  draft: Partial<GeneratedLocationDraft>,
  inputQuery: string,
) {
  const name = titleCaseFallback(draft.name ?? inputQuery);
  const slug = slugify(draft.slug ?? name);
  const hotspots =
    (draft.hotspots ?? []).slice(0, 4).map(normalizeHotspot).filter(Boolean) || [];
  const normalizedHotspots =
    hotspots.length > 0
      ? hotspots
      : [
          normalizeHotspot(
            {
              name,
              description: `Primary viewpoint for ${name}.`,
              explainText: `Showing ${name}. Validate this hotspot against imagery and site notes.`,
            },
            0,
          ),
        ];
  const scenarios =
    (draft.scenarios ?? []).slice(0, 3).map(normalizeScenario).filter(Boolean) || [];
  const normalizedScenarios =
    scenarios.length > 0
      ? scenarios
      : [
          normalizeScenario({ label: 'Baseline', year: 2026, riseMeters: 0 }, 0),
          normalizeScenario({ label: '2050 Draft', year: 2050, riseMeters: 0.6 }, 1),
          normalizeScenario({ label: '2100 Draft', year: 2100, riseMeters: 1.8 }, 2),
        ];

  return {
    slug,
    name,
    region: draft.region?.trim() || 'Draft region',
    description:
      draft.description?.trim() ||
      `Starter Sojs location draft for ${name}. Replace this with field-validated context.`,
    status: draft.status?.trim() || 'Draft',
    updatedAt: draft.updatedAt?.trim() || new Date().toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    }),
    sources: (draft.sources ?? []).map((source) => source.trim()).filter(Boolean).slice(0, 6),
    hotspots: normalizedHotspots,
    scenarios: normalizedScenarios,
    defaultHotspotId:
      draft.defaultHotspotId?.trim() || normalizedHotspots[0]?.id || 'overview',
    notes: (draft.notes ?? []).map((note) => note.trim()).filter(Boolean).slice(0, 6),
    orthogonalWorkflow: (draft.orthogonalWorkflow ?? [])
      .map((step) => step.trim())
      .filter(Boolean)
      .slice(0, 6),
    exportChecklist: (draft.exportChecklist ?? [])
      .map((step) => step.trim())
      .filter(Boolean)
      .slice(0, 6),
  };
}

export function createLocationRecordSnippet(draft: GeneratedLocationDraft) {
  const primaryScenario = draft.scenarios[0];

  return `{
  slug: ${quoteString(draft.slug)},
  name: ${quoteString(draft.name)},
  region: ${quoteString(draft.region)},
  description: ${quoteString(draft.description)},
  splatUrl: '/TODO.ply',
  renderer: 'ply',
  status: ${quoteString(draft.status)},
  updatedAt: ${quoteString(draft.updatedAt)},
  scene: {
    year: ${primaryScenario.year},
    rise: ${primaryScenario.riseMeters},
    label: ${quoteString(primaryScenario.label)},
    color: ${quoteString(primaryScenario.color)},
  },
  sources: [${draft.sources.map((source) => quoteString(source)).join(', ')}],
  hotspots: [
${draft.hotspots
  .map(
    (hotspot) => `    {
      id: ${quoteString(hotspot.id)},
      name: ${quoteString(hotspot.name)},
      aliases: [${hotspot.aliases.map((alias) => quoteString(alias)).join(', ')}],
      description: ${quoteString(hotspot.description)},
      cameraPose: {
        position: [-3.5, 2, 5.5],
        target: [0, 0.4, 0],
      },
      explainText: ${quoteString(hotspot.explainText)},
    }`,
  )
  .join(',\n')}
  ],
  scenarios: [
${draft.scenarios
  .map(
    (scenario) => `    {
      id: ${quoteString(scenario.id)},
      label: ${quoteString(scenario.label)},
      year: ${scenario.year},
      riseMeters: ${scenario.riseMeters},
      narration: ${quoteString(scenario.narration)},
      color: ${quoteString(scenario.color)},
    }`,
  )
  .join(',\n')}
  ],
  defaultHotspotId: ${quoteString(draft.defaultHotspotId)},
}`;
}
