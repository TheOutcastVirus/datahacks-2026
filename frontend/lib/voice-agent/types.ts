import type { LocationRecord } from '@/lib/locations';
import type { ViewerState } from '@/lib/viewer-types';

export type VoiceAgentSceneState = {
  activeHotspotId: string;
  activeScenarioId: string;
  compareScenarioIds: [string, string] | null;
  riseMeters: number;
  viewerState: ViewerState;
};

export type VoiceAgentTurnInput = {
  transcript: string;
  location: LocationRecord;
  sceneState: VoiceAgentSceneState;
};

export type VoiceAgentToolCall = {
  toolName: string;
  callId: string;
  args: Record<string, unknown>;
};

export type VoiceAgentAction =
  | { type: 'go_to_hotspot'; hotspotId: string }
  | { type: 'set_scenario'; scenarioId: string }
  | { type: 'compare_scenarios'; leftScenarioId: string; rightScenarioId: string }
  | { type: 'move_camera'; direction: 'left' | 'right' | 'forward' | 'back' }
  | { type: 'zoom_camera'; direction: 'in' | 'out' }
  | { type: 'reset_camera' };

export type VoiceAgentTrace = {
  transcript: string;
  promptId: string;
  sceneSnapshot: Record<string, unknown>;
  modelText: string;
  toolCalls: VoiceAgentToolCall[];
  toolResults: Array<{ callId: string; toolName: string; result: unknown }>;
  actions: VoiceAgentAction[];
  timingsMs: {
    model: number;
    tools: number;
    total: number;
  };
  error: string | null;
};

export type VoiceAgentTurnResult = {
  speech: string;
  caption: string;
  actions: VoiceAgentAction[];
  traces: VoiceAgentTrace;
  status: 'completed' | 'needs_clarification' | 'failed';
};

export type VoiceAgentModelResult = {
  toolCalls?: VoiceAgentToolCall[];
  response?: {
    speech: string;
    caption: string;
  };
  needsClarification?: boolean;
};

export type VoiceAgentToolContext = {
  location: LocationRecord;
  sceneState: VoiceAgentSceneState;
};
