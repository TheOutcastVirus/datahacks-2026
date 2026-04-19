import type {
  VoiceAgentTrace,
  VoiceAgentTurnInput,
  VoiceAgentTurnResult,
} from '@/lib/voice-agent/types';

export function createVoiceAgentTrace(input: VoiceAgentTurnInput): VoiceAgentTrace {
  return {
    transcript: input.transcript,
    promptId: 'sojs-voice-agent-v1',
    sceneSnapshot: {
      locationSlug: input.location.slug,
      activeHotspotId: input.sceneState.activeHotspotId,
      activeScenarioId: input.sceneState.activeScenarioId,
      compareScenarioIds: input.sceneState.compareScenarioIds,
      riseMeters: input.sceneState.riseMeters,
      viewerState: input.sceneState.viewerState,
    },
    modelText: '',
    toolCalls: [],
    toolResults: [],
    actions: [],
    timingsMs: {
      model: 0,
      tools: 0,
      total: 0,
    },
    error: null,
  };
}

export function finalizeVoiceAgentTrace(
  trace: VoiceAgentTrace,
  startedAt: number,
  result: VoiceAgentTurnResult,
) {
  trace.actions = result.actions;
  trace.timingsMs.total = Date.now() - startedAt;

  if (process.env.NODE_ENV !== 'production') {
    console.log('[voice-agent]', JSON.stringify(trace, null, 2));
  }

  return trace;
}
