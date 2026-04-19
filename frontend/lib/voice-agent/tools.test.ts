import assert from 'node:assert/strict';
import test from 'node:test';

import { LOCATIONS } from '@/lib/locations';
import { executeVoiceAgentTool } from '@/lib/voice-agent/tools';

const location = LOCATIONS[0];
const sceneState = {
  activeHotspotId: location.defaultHotspotId,
  activeScenarioId: location.scenarios[0].id,
  compareScenarioIds: null,
  riseMeters: 0,
  viewerState: 'ready' as const,
};

test('resolves hotspot aliases into canonical hotspot actions', () => {
  const { execution } = executeVoiceAgentTool(
    { location, sceneState },
    {
      toolName: 'go_to_hotspot',
      callId: 'call-1',
      args: { hotspotId: 'ferry terminal' },
    },
  );

  assert.deepEqual(execution.action, {
    type: 'go_to_hotspot',
    hotspotId: 'ferry-terminal',
  });
});

test('snaps scenario years to the nearest saved scenario', () => {
  const { execution } = executeVoiceAgentTool(
    { location, sceneState },
    {
      toolName: 'set_scenario',
      callId: 'call-2',
      args: { scenarioId: '2065' },
    },
  );

  assert.deepEqual(execution.action, {
    type: 'set_scenario',
    scenarioId: 'mid-century',
  });
});

test('returns grounded read-only responses', () => {
  const { execution } = executeVoiceAgentTool(
    { location, sceneState },
    {
      toolName: 'explain_sources',
      callId: 'call-3',
      args: {},
    },
  );

  assert.match(String(execution.response?.speech), /NASA Ice Cap Metrics/);
});
