import assert from 'node:assert/strict';
import test from 'node:test';

import { LOCATIONS } from '@/lib/locations';
import { normalizeTranscript, parseVoiceIntent } from '@/lib/scene-command-catalog';
import {
  buildScenarioResponse,
  buildSourcesResponse,
  buildUnknownResponse,
} from '@/lib/voice-responses';

const location = LOCATIONS[0];

test('normalizes filler words and punctuation', () => {
  assert.equal(normalizeTranscript('Hey Sojs, show 2050 please!'), 'show 2050 please');
});

test('matches hotspot aliases before generic commands', () => {
  assert.deepEqual(parseVoiceIntent(location, 'go to the ferry terminal'), {
    type: 'go_to_hotspot',
    hotspotId: 'ferry-terminal',
  });
});

test('snaps unsupported years to the nearest scenario', () => {
  assert.deepEqual(parseVoiceIntent(location, 'show 2065'), {
    type: 'set_scenario',
    scenarioId: 'mid-century',
    matchedYear: 2065,
    snappedFromYear: 2065,
  });
});

test('falls back to unknown for unrelated phrases', () => {
  assert.deepEqual(parseVoiceIntent(location, 'sing me a song'), {
    type: 'unknown',
    transcript: 'sing me a song',
  });
});

test('builds grounded response text', () => {
  const scenario = location.scenarios[1];
  assert.match(buildScenarioResponse(location, scenario).speech, /2050 outlook/i);
  assert.match(buildSourcesResponse(location).speech, /NASA Ice Cap Metrics/);
  assert.match(buildUnknownResponse().caption, /show 2050/i);
});
