import { extractJsonObject, runNvidiaPrompt } from '@/lib/server/nvidia';
import { parseVoiceIntent } from '@/lib/scene-command-catalog';
import {
  buildCurrentViewResponse,
  buildFloodRiskResponse,
  buildHelpResponse,
  buildNavigationResponse,
  buildScenarioResponse,
  buildSourcesResponse,
  buildUnknownResponse,
  buildCompareResponse,
} from '@/lib/voice-responses';
import {
  buildVoiceAgentRepairPrompt,
  buildVoiceAgentSummaryPrompt,
  buildVoiceAgentSystemPrompt,
  buildVoiceAgentUserPrompt,
  VOICE_AGENT_PROMPT_ID,
} from '@/lib/voice-agent/prompts';
import { createVoiceAgentTrace, finalizeVoiceAgentTrace } from '@/lib/voice-agent/tracing';
import { executeVoiceAgentTool, getVoiceAgentToolSchema } from '@/lib/voice-agent/tools';
import type {
  VoiceAgentAction,
  VoiceAgentModelResult,
  VoiceAgentTrace,
  VoiceAgentTurnInput,
  VoiceAgentTurnResult,
} from '@/lib/voice-agent/types';

type HarnessDeps = {
  runModel?: (systemPrompt: string, userPrompt: string) => Promise<string>;
};

function asResponse(value: unknown) {
  if (
    value &&
    typeof value === 'object' &&
    'speech' in value &&
    typeof value.speech === 'string' &&
    'caption' in value &&
    typeof value.caption === 'string'
  ) {
    return value as { speech: string; caption: string };
  }

  throw new Error('Model response was missing a valid speech/caption payload.');
}

function parseModelResult(text: string) {
  const parsed = JSON.parse(extractJsonObject(text)) as VoiceAgentModelResult;
  if (!parsed.toolCalls && !parsed.response && !parsed.needsClarification) {
    throw new Error('Model response did not contain toolCalls or response.');
  }
  return parsed;
}

function buildViewerLoadingResponse() {
  const speech = 'The scene is still loading. Try that command again in a moment.';
  return { speech, caption: speech };
}

function buildFallbackResult(input: VoiceAgentTurnInput, trace: VoiceAgentTrace): VoiceAgentTurnResult {
  const location = input.location;
  const activeHotspot =
    location.hotspots.find((hotspot) => hotspot.id === input.sceneState.activeHotspotId) ??
    location.hotspots[0];
  const activeScenario =
    location.scenarios.find((scenario) => scenario.id === input.sceneState.activeScenarioId) ??
    location.scenarios[0];
  const intent = parseVoiceIntent(location, input.transcript);

  switch (intent.type) {
    case 'go_to_hotspot': {
      const hotspot = location.hotspots.find((item) => item.id === intent.hotspotId) ?? activeHotspot;
      const response = buildNavigationResponse(hotspot);
      return { speech: response.speech, caption: response.caption, actions: [intent], traces: trace, status: 'completed' };
    }
    case 'set_scenario': {
      const scenario = location.scenarios.find((item) => item.id === intent.scenarioId) ?? activeScenario;
      const response = buildScenarioResponse(location, scenario, intent.snappedFromYear);
      return {
        speech: response.speech,
        caption: response.caption,
        actions: [{ type: 'set_scenario', scenarioId: scenario.id }],
        traces: trace,
        status: 'completed',
      };
    }
    case 'compare_scenarios': {
      const left = location.scenarios.find((item) => item.id === intent.leftId) ?? location.scenarios[0];
      const right =
        location.scenarios.find((item) => item.id === intent.rightId) ??
        location.scenarios[location.scenarios.length - 1];
      const response = buildCompareResponse(location, left, right);
      return {
        speech: response.speech,
        caption: response.caption,
        actions: [{ type: 'compare_scenarios', leftScenarioId: left.id, rightScenarioId: right.id }],
        traces: trace,
        status: 'completed',
      };
    }
    case 'camera_move':
      return {
        speech: `Moving ${intent.direction}.`,
        caption: `Moved the camera ${intent.direction}.`,
        actions: [{ type: 'move_camera', direction: intent.direction }],
        traces: trace,
        status: 'completed',
      };
    case 'camera_zoom':
      return {
        speech: intent.direction === 'in' ? 'Zooming in.' : 'Zooming out.',
        caption: `Zoomed ${intent.direction}.`,
        actions: [{ type: 'zoom_camera', direction: intent.direction }],
        traces: trace,
        status: 'completed',
      };
    case 'reset_camera':
      return {
        speech: 'Resetting the camera to the default view.',
        caption: 'Camera reset to the default view.',
        actions: [{ type: 'reset_camera' }],
        traces: trace,
        status: 'completed',
      };
    case 'explain_current_view': {
      const response = buildCurrentViewResponse(location, activeHotspot, activeScenario);
      return { speech: response.speech, caption: response.caption, actions: [], traces: trace, status: 'completed' };
    }
    case 'explain_flood_risk': {
      const response = buildFloodRiskResponse(activeHotspot);
      return { speech: response.speech, caption: response.caption, actions: [], traces: trace, status: 'completed' };
    }
    case 'explain_sources': {
      const response = buildSourcesResponse(location);
      return { speech: response.speech, caption: response.caption, actions: [], traces: trace, status: 'completed' };
    }
    case 'help': {
      const response = buildHelpResponse(location);
      return { speech: response.speech, caption: response.caption, actions: [], traces: trace, status: 'completed' };
    }
    case 'unknown': {
      const response = buildUnknownResponse();
      return { speech: response.speech, caption: response.caption, actions: [], traces: trace, status: 'needs_clarification' };
    }
  }
}

export function createVoiceAgentHarness(deps: HarnessDeps = {}) {
  const runModel = deps.runModel ?? ((systemPrompt: string, userPrompt: string) => runNvidiaPrompt(systemPrompt, userPrompt));

  return {
    async runVoiceAgentTurn(input: VoiceAgentTurnInput): Promise<VoiceAgentTurnResult> {
      const startedAt = Date.now();
      const trace = createVoiceAgentTrace(input);
      trace.promptId = VOICE_AGENT_PROMPT_ID;

      if (!input.transcript.trim()) {
        const result = {
          speech: 'I did not catch anything. Try saying show 2050 or go to the waterfront.',
          caption: 'Transcript is empty.',
          actions: [],
          traces: trace,
          status: 'needs_clarification' as const,
        };
        finalizeVoiceAgentTrace(trace, startedAt, result);
        return result;
      }

      try {
        const systemPrompt = buildVoiceAgentSystemPrompt(getVoiceAgentToolSchema());
        const userPrompt = buildVoiceAgentUserPrompt(
          input.transcript,
          input.location,
          input.sceneState,
        );

        const modelStart = Date.now();
        let modelText = await runModel(systemPrompt, userPrompt);
        trace.timingsMs.model = Date.now() - modelStart;
        trace.modelText = modelText;

        let parsed: VoiceAgentModelResult;
        try {
          parsed = parseModelResult(modelText);
        } catch {
          const repairStart = Date.now();
          modelText = await runModel(
            systemPrompt,
            buildVoiceAgentRepairPrompt(modelText),
          );
          trace.timingsMs.model += Date.now() - repairStart;
          trace.modelText = modelText;
          parsed = parseModelResult(modelText);
        }

        if (!parsed.toolCalls?.length) {
          if (parsed.response) {
            const response = asResponse(parsed.response);
            const result = {
              speech: response.speech,
              caption: response.caption,
              actions: [],
              traces: trace,
              status: parsed.needsClarification ? ('needs_clarification' as const) : ('completed' as const),
            };
            finalizeVoiceAgentTrace(trace, startedAt, result);
            return result;
          }

          throw new Error('Model returned no tool calls or response.');
        }

        trace.toolCalls = parsed.toolCalls;
        const toolStart = Date.now();
        const actions: VoiceAgentAction[] = [];
        let lastResponse: { speech: string; caption: string } | null = null;
        let status: VoiceAgentTurnResult['status'] = 'completed';

        for (const toolCall of parsed.toolCalls) {
          const { definition, execution } = executeVoiceAgentTool(
            { location: input.location, sceneState: input.sceneState },
            toolCall,
          );
          trace.toolResults.push({
            callId: toolCall.callId,
            toolName: toolCall.toolName,
            result: execution.result,
          });

          if (definition.stateChanging && input.sceneState.viewerState !== 'ready') {
            lastResponse = buildViewerLoadingResponse();
            status = 'needs_clarification';
            continue;
          }

          if (execution.action) {
            actions.push(execution.action);
          }

          if (execution.response) {
            lastResponse = execution.response;
          }

          if (execution.clarification) {
            status = 'needs_clarification';
          }
        }

        trace.timingsMs.tools = Date.now() - toolStart;

        if (!actions.length && !lastResponse && trace.toolResults.length) {
          const summaryText = await runModel(
            buildVoiceAgentSystemPrompt(getVoiceAgentToolSchema()),
            buildVoiceAgentSummaryPrompt(input.transcript, trace),
          );
          lastResponse = asResponse(JSON.parse(extractJsonObject(summaryText)));
        }

        const result = {
          speech: lastResponse?.speech ?? buildUnknownResponse().speech,
          caption: lastResponse?.caption ?? buildUnknownResponse().caption,
          actions,
          traces: trace,
          status,
        };
        finalizeVoiceAgentTrace(trace, startedAt, result);
        return result;
      } catch (error) {
        trace.error = error instanceof Error ? error.message : 'Voice agent failed.';
        const result = buildFallbackResult(input, trace);
        finalizeVoiceAgentTrace(trace, startedAt, result);
        return result;
      }
    },
  };
}

export async function runVoiceAgentTurn(input: VoiceAgentTurnInput) {
  return createVoiceAgentHarness().runVoiceAgentTurn(input);
}
