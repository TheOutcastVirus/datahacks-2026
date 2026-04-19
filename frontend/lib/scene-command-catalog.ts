import type { LocationRecord, ScenarioRecord, SceneHotspot } from '@/lib/locations';
import type { VoiceIntent } from '@/lib/voice-types';

const FILLER_WORDS = new Set([
  'please',
  'um',
  'uh',
  'like',
  'hey',
  'okay',
  'ok',
  'sojs',
]);

const NAVIGATION_PREFIXES = ['go to', 'show', 'take me to', 'focus on', 'jump to'];
const CAMERA_MOVE_MAP: Array<{
  direction: 'left' | 'right' | 'forward' | 'back';
  phrases: string[];
}> = [
  { direction: 'left', phrases: ['pan left', 'move left', 'go left', 'left'] },
  { direction: 'right', phrases: ['pan right', 'move right', 'go right', 'right'] },
  { direction: 'forward', phrases: ['move forward', 'go forward', 'forward', 'closer'] },
  { direction: 'back', phrases: ['move back', 'go back', 'back', 'backward'] },
];
const ZOOM_IN_PHRASES = ['zoom in', 'closer', 'come closer'];
const ZOOM_OUT_PHRASES = ['zoom out', 'farther', 'further away'];
const RESET_PHRASES = ['reset camera', 'reset view', 'reset', 'go back to start'];
const HELP_PHRASES = ['help', 'what can i say', 'what can i ask'];
const EXPLAIN_VIEW_PHRASES = [
  'what am i looking at',
  'what is this',
  'where am i',
  'describe this view',
];
const FLOOD_RISK_PHRASES = [
  'what floods first',
  'which area floods first',
  'why does this flood first',
  'why is this area flooding first',
];
const SOURCES_PHRASES = [
  'what data is this based on',
  'what data is this from',
  'what sources is this based on',
  'what sources are you using',
  'show sources',
];
const BASELINE_TERMS = ['baseline', 'now', 'today', 'current', 'present day'];
const WORST_CASE_TERMS = ['worst case', 'highest rise', 'maximum rise'];

function includesPhrase(input: string, phrases: string[]) {
  return phrases.some((phrase) => input.includes(phrase));
}

function getScenarioAliases(scenario: ScenarioRecord) {
  const aliases = new Set<string>([
    scenario.id,
    scenario.label,
    String(scenario.year),
  ]);

  if (scenario.year === 2026 || scenario.label.toLowerCase().includes('baseline')) {
    for (const term of BASELINE_TERMS) aliases.add(term);
  }

  if (scenario.label.toLowerCase().includes('worst')) {
    for (const term of WORST_CASE_TERMS) aliases.add(term);
  }

  return Array.from(aliases).map((alias) => normalizeTranscript(alias));
}

function getScenarioMentions(location: LocationRecord, transcript: string) {
  const mentions: ScenarioRecord[] = [];
  const years = transcript.match(/\b(19|20)\d{2}\b/g)?.map(Number) ?? [];

  for (const year of years) {
    mentions.push(getNearestScenario(location.scenarios, year));
  }

  for (const scenario of location.scenarios) {
    const aliases = getScenarioAliases(scenario);
    if (aliases.some((alias) => transcript.includes(alias))) {
      mentions.push(scenario);
    }
  }

  return mentions.filter((scenario, index, all) => {
    return all.findIndex((candidate) => candidate.id === scenario.id) === index;
  });
}

export function normalizeTranscript(input: string) {
  const normalized = input
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .filter((word, index) => !(index < 2 && FILLER_WORDS.has(word)))
    .join(' ')
    .trim();

  return normalized;
}

export function getNearestScenario(scenarios: ScenarioRecord[], year: number) {
  return scenarios.reduce((closest, scenario) => {
    const currentDelta = Math.abs(scenario.year - year);
    const closestDelta = Math.abs(closest.year - year);
    return currentDelta < closestDelta ? scenario : closest;
  }, scenarios[0]);
}

function findHotspot(location: LocationRecord, transcript: string): SceneHotspot | null {
  for (const hotspot of location.hotspots) {
    const aliases = [hotspot.name, ...hotspot.aliases].map((alias) =>
      normalizeTranscript(alias),
    );

    for (const alias of aliases) {
      if (transcript === alias || transcript.includes(alias)) {
        return hotspot;
      }

      for (const prefix of NAVIGATION_PREFIXES) {
        if (transcript.includes(`${prefix} ${alias}`)) {
          return hotspot;
        }
      }
    }
  }

  return null;
}

export function parseVoiceIntent(location: LocationRecord, transcript: string): VoiceIntent {
  const normalized = normalizeTranscript(transcript);
  if (!normalized) {
    return { type: 'unknown', transcript };
  }

  const hotspot = findHotspot(location, normalized);
  if (hotspot) {
    return { type: 'go_to_hotspot', hotspotId: hotspot.id };
  }

  if (normalized.includes('compare')) {
    const mentions = getScenarioMentions(location, normalized);
    if (mentions.length >= 2) {
      return {
        type: 'compare_scenarios',
        leftId: mentions[0].id,
        rightId: mentions[1].id,
      };
    }
  }

  const explicitYear = normalized.match(/\b(19|20)\d{2}\b/)?.[0];
  const mentionedScenario = getScenarioMentions(location, normalized)[0];
  if (
    normalized.includes('show') ||
    normalized.includes('set') ||
    normalized.includes('scenario') ||
    includesPhrase(normalized, BASELINE_TERMS) ||
    includesPhrase(normalized, WORST_CASE_TERMS) ||
    explicitYear
  ) {
    if (mentionedScenario) {
      const year = explicitYear ? Number(explicitYear) : undefined;
      return {
        type: 'set_scenario',
        scenarioId: mentionedScenario.id,
        matchedYear: year ?? mentionedScenario.year,
        snappedFromYear:
          year && year !== mentionedScenario.year ? year : undefined,
      };
    }
  }

  if (includesPhrase(normalized, ZOOM_IN_PHRASES)) {
    return { type: 'camera_zoom', direction: 'in' };
  }

  if (includesPhrase(normalized, ZOOM_OUT_PHRASES)) {
    return { type: 'camera_zoom', direction: 'out' };
  }

  if (includesPhrase(normalized, RESET_PHRASES)) {
    return { type: 'reset_camera' };
  }

  for (const entry of CAMERA_MOVE_MAP) {
    if (includesPhrase(normalized, entry.phrases)) {
      return { type: 'camera_move', direction: entry.direction };
    }
  }

  if (includesPhrase(normalized, EXPLAIN_VIEW_PHRASES)) {
    return { type: 'explain_current_view' };
  }

  if (includesPhrase(normalized, FLOOD_RISK_PHRASES)) {
    return { type: 'explain_flood_risk' };
  }

  if (includesPhrase(normalized, SOURCES_PHRASES)) {
    return { type: 'explain_sources' };
  }

  if (includesPhrase(normalized, HELP_PHRASES)) {
    return { type: 'help' };
  }

  return { type: 'unknown', transcript };
}
