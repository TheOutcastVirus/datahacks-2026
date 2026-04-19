import assert from 'node:assert/strict';
import test from 'node:test';

import { LOCATIONS } from '@/lib/locations';
import { createVoiceAgentHarness } from '@/lib/voice-agent/harness';

const location = LOCATIONS[0];
const baseSceneState = {
  activeHotspotId: location.defaultHotspotId,
  activeScenarioId: location.scenarios[0].id,
  compareScenarioIds: null,
  riseMeters: 0,
  viewerState: 'ready' as const,
};

test('runs a state-changing tool call and returns normalized action output', async () => {
  const harness = createVoiceAgentHarness({
    runModel: async () =>
      JSON.stringify({
        toolCalls: [
          {
            toolName: 'go_to_hotspot',
            callId: 'call-1',
            args: { hotspotId: 'ferry-terminal' },
          },
        ],
      }),
  });

  const result = await harness.runVoiceAgentTurn({
    transcript: 'go to the ferry terminal',
    location,
    sceneState: baseSceneState,
  });

  assert.equal(result.status, 'completed');
  assert.deepEqual(result.actions, [
    { type: 'go_to_hotspot', hotspotId: 'ferry-terminal' },
  ]);
  assert.equal(result.traces.toolCalls[0]?.toolName, 'go_to_hotspot');
});

test('uses tool results to answer read-only questions', async () => {
  let calls = 0;
  const harness = createVoiceAgentHarness({
    runModel: async (_systemPrompt, userPrompt) => {
      calls += 1;
      if (calls === 1) {
        return JSON.stringify({
          toolCalls: [{ toolName: 'explain_sources', callId: 'call-1', args: {} }],
        });
      }

      assert.match(userPrompt, /tool results/i);
      return JSON.stringify({
        speech: 'This scene uses NASA Ice Cap Metrics, NOAA Tidal Records, and a local shoreline survey.',
        caption: 'Sources: NASA Ice Cap Metrics, NOAA Tidal Records, Local shoreline survey.',
      });
    },
  });

  const result = await harness.runVoiceAgentTurn({
    transcript: 'what data is this based on',
    location,
    sceneState: baseSceneState,
  });

  assert.equal(result.status, 'completed');
  assert.equal(result.actions.length, 0);
  assert.match(result.speech, /NASA Ice Cap Metrics/);
});

test('falls back when the model keeps returning malformed output', async () => {
  const harness = createVoiceAgentHarness({
    runModel: async () => 'definitely not json',
  });

  const result = await harness.runVoiceAgentTurn({
    transcript: 'show 2065',
    location,
    sceneState: baseSceneState,
  });

  assert.equal(result.status, 'completed');
  assert.deepEqual(result.actions, [{ type: 'set_scenario', scenarioId: 'mid-century' }]);
});

test('blocks state-changing tools when the viewer is not ready', async () => {
  const harness = createVoiceAgentHarness({
    runModel: async () =>
      JSON.stringify({
        toolCalls: [{ toolName: 'reset_camera', callId: 'call-1', args: {} }],
      }),
  });

  const result = await harness.runVoiceAgentTurn({
    transcript: 'reset view',
    location,
    sceneState: { ...baseSceneState, viewerState: 'loading' },
  });

  assert.equal(result.status, 'needs_clarification');
  assert.equal(result.actions.length, 0);
  assert.match(result.speech, /still loading/i);
});
