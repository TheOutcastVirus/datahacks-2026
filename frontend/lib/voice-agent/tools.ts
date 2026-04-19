import type { LocationRecord, ScenarioRecord, SceneHotspot } from '@/lib/locations';
import {
  buildCompareResponse,
  buildCurrentViewResponse,
  buildFloodRiskResponse,
  buildHelpResponse,
  buildNavigationResponse,
  buildScenarioResponse,
  buildSourcesResponse,
} from '@/lib/voice-responses';
import { getNearestScenario, normalizeTranscript } from '@/lib/scene-command-catalog';
import type {
  VoiceAgentAction,
  VoiceAgentToolContext,
  VoiceAgentToolCall,
} from '@/lib/voice-agent/types';

type ToolExecutionResult = {
  action?: VoiceAgentAction;
  response?: {
    speech: string;
    caption: string;
  };
  result: unknown;
  clarification?: boolean;
};

type HotspotMatchResult =
  | { hotspot: SceneHotspot; clarification?: false }
  | { clarification: true; matches: SceneHotspot[] };

type ScenarioMatchResult =
  | { scenario: ScenarioRecord; snappedFromYear?: number; clarification?: false }
  | { clarification: true; matches: ScenarioRecord[] };

export type VoiceAgentToolDefinition = {
  name: string;
  description: string;
  args: Record<string, string>;
  stateChanging: boolean;
  execute: (ctx: VoiceAgentToolContext, args: Record<string, unknown>) => ToolExecutionResult;
};

function findHotspotByIdOrAlias(location: LocationRecord, value: unknown): HotspotMatchResult {
  if (typeof value !== 'string') {
    throw new Error('hotspotId must be a string.');
  }

  const normalized = normalizeTranscript(value);
  const matches = location.hotspots.filter((hotspot) => {
    const aliases = [hotspot.id, hotspot.name, ...hotspot.aliases].map(normalizeTranscript);
    return aliases.includes(normalized);
  });

  if (matches.length > 1) {
    return { clarification: true, matches };
  }

  if (!matches[0]) {
    throw new Error(`Unknown hotspot: ${value}`);
  }

  return { hotspot: matches[0] };
}

function findScenarioByIdOrAlias(location: LocationRecord, value: unknown): ScenarioMatchResult {
  if (typeof value === 'number') {
    return { scenario: getNearestScenario(location.scenarios, value), snappedFromYear: value };
  }

  if (typeof value !== 'string') {
    throw new Error('scenarioId must be a string or year.');
  }

  const year = Number(value);
  if (Number.isFinite(year) && /^\d{4}$/.test(value.trim())) {
    return { scenario: getNearestScenario(location.scenarios, year), snappedFromYear: year };
  }

  const normalized = normalizeTranscript(value);
  const matches = location.scenarios.filter((scenario) => {
    const aliases = [
      scenario.id,
      scenario.label,
      String(scenario.year),
      scenario.year === 2026 ? 'baseline' : '',
      scenario.year === 2026 ? 'current' : '',
      scenario.label.toLowerCase().includes('worst') ? 'worst case' : '',
    ]
      .filter(Boolean)
      .map(normalizeTranscript);
    return aliases.includes(normalized);
  });

  if (matches.length > 1) {
    return { clarification: true, matches };
  }

  if (!matches[0]) {
    throw new Error(`Unknown scenario: ${value}`);
  }

  return { scenario: matches[0] };
}

function getActiveHotspot(location: LocationRecord, activeHotspotId: string) {
  return location.hotspots.find((hotspot) => hotspot.id === activeHotspotId) ?? location.hotspots[0];
}

function getActiveScenario(location: LocationRecord, activeScenarioId: string) {
  return (
    location.scenarios.find((scenario) => scenario.id === activeScenarioId) ?? location.scenarios[0]
  );
}

function assertDefined<T>(value: T | undefined, message: string): T {
  if (value === undefined) {
    throw new Error(message);
  }

  return value;
}

function buildClarificationResponseForMatches(
  kind: 'hotspot' | 'scenario',
  matches: Array<SceneHotspot | ScenarioRecord>,
) {
  const names = matches.map((match) => ('name' in match ? match.name : match.label));
  return {
    speech: `I found multiple ${kind} matches: ${names.join(', ')}. Which one do you want?`,
    caption: `Multiple ${kind} matches: ${names.join(', ')}.`,
  };
}

const TOOL_DEFINITIONS: VoiceAgentToolDefinition[] = [
  {
    name: 'get_scene_state',
    description: 'Get the current scene state and active view.',
    args: {},
    stateChanging: false,
    execute(ctx) {
      const activeHotspot = getActiveHotspot(ctx.location, ctx.sceneState.activeHotspotId);
      const activeScenario = getActiveScenario(ctx.location, ctx.sceneState.activeScenarioId);
      return {
        result: {
          activeHotspot,
          activeScenario,
          compareScenarioIds: ctx.sceneState.compareScenarioIds,
          riseMeters: ctx.sceneState.riseMeters,
          viewerState: ctx.sceneState.viewerState,
        },
      };
    },
  },
  {
    name: 'list_hotspots',
    description: 'List the known scene hotspots.',
    args: {},
    stateChanging: false,
    execute(ctx) {
      return {
        result: ctx.location.hotspots.map((hotspot) => ({
          id: hotspot.id,
          name: hotspot.name,
          aliases: hotspot.aliases,
          description: hotspot.description,
        })),
      };
    },
  },
  {
    name: 'go_to_hotspot',
    description: 'Navigate to a hotspot by id or name.',
    args: { hotspotId: 'Canonical hotspot id or spoken hotspot name.' },
    stateChanging: true,
    execute(ctx, args) {
      const match = findHotspotByIdOrAlias(ctx.location, args.hotspotId);
      if (match.clarification) {
        return {
          clarification: true,
          response: buildClarificationResponseForMatches('hotspot', match.matches),
          result: { ambiguous: true, matches: match.matches.map((item) => item.id) },
        };
      }
      const hotspot = assertDefined(match.hotspot, 'Resolved hotspot was missing.');
      return {
        action: { type: 'go_to_hotspot', hotspotId: hotspot.id },
        response: buildNavigationResponse(hotspot),
        result: { hotspotId: hotspot.id, hotspotName: hotspot.name },
      };
    },
  },
  {
    name: 'set_scenario',
    description: 'Change the active scenario by id, label, or year.',
    args: { scenarioId: 'Canonical scenario id, scenario label, or year.' },
    stateChanging: true,
    execute(ctx, args) {
      const match = findScenarioByIdOrAlias(ctx.location, args.scenarioId);
      if (match.clarification) {
        return {
          clarification: true,
          response: buildClarificationResponseForMatches('scenario', match.matches),
          result: { ambiguous: true, matches: match.matches.map((item) => item.id) },
        };
      }
      const scenario = assertDefined(match.scenario, 'Resolved scenario was missing.');
      return {
        action: { type: 'set_scenario', scenarioId: scenario.id },
        response: buildScenarioResponse(ctx.location, scenario, match.snappedFromYear),
        result: { scenarioId: scenario.id, year: scenario.year },
      };
    },
  },
  {
    name: 'compare_scenarios',
    description: 'Compare two scenarios.',
    args: {
      leftScenarioId: 'Left scenario id, label, or year.',
      rightScenarioId: 'Right scenario id, label, or year.',
    },
    stateChanging: true,
    execute(ctx, args) {
      const leftMatch = findScenarioByIdOrAlias(ctx.location, args.leftScenarioId);
      const rightMatch = findScenarioByIdOrAlias(ctx.location, args.rightScenarioId);
      if (leftMatch.clarification || rightMatch.clarification) {
        const matches = leftMatch.clarification
          ? leftMatch.matches
          : assertDefined(
              rightMatch.clarification ? rightMatch.matches : undefined,
              'Ambiguous scenario matches were missing.',
            );
        return {
          clarification: true,
          response: buildClarificationResponseForMatches('scenario', matches),
          result: { ambiguous: true },
        };
      }
      const left = assertDefined(leftMatch.scenario, 'Left scenario was missing.');
      const right = assertDefined(rightMatch.scenario, 'Right scenario was missing.');
      return {
        action: {
          type: 'compare_scenarios',
          leftScenarioId: left.id,
          rightScenarioId: right.id,
        },
        response: buildCompareResponse(ctx.location, left, right),
        result: { leftScenarioId: left.id, rightScenarioId: right.id },
      };
    },
  },
  {
    name: 'move_camera',
    description: 'Move the camera slightly in a direction.',
    args: { direction: 'One of left, right, forward, back.' },
    stateChanging: true,
    execute(_ctx, args) {
      const direction = args.direction;
      if (
        direction !== 'left' &&
        direction !== 'right' &&
        direction !== 'forward' &&
        direction !== 'back'
      ) {
        throw new Error('direction must be one of left, right, forward, back.');
      }
      return {
        action: { type: 'move_camera', direction },
        response: {
          speech: `Moving ${direction}.`,
          caption: `Moved the camera ${direction}.`,
        },
        result: { direction },
      };
    },
  },
  {
    name: 'zoom_camera',
    description: 'Zoom the camera in or out.',
    args: { direction: 'One of in or out.' },
    stateChanging: true,
    execute(_ctx, args) {
      const direction = args.direction;
      if (direction !== 'in' && direction !== 'out') {
        throw new Error('direction must be one of in or out.');
      }
      return {
        action: { type: 'zoom_camera', direction },
        response: {
          speech: direction === 'in' ? 'Zooming in.' : 'Zooming out.',
          caption: `Zoomed ${direction}.`,
        },
        result: { direction },
      };
    },
  },
  {
    name: 'reset_camera',
    description: 'Reset the camera to the default view.',
    args: {},
    stateChanging: true,
    execute() {
      return {
        action: { type: 'reset_camera' },
        response: {
          speech: 'Resetting the camera to the default view.',
          caption: 'Camera reset to the default view.',
        },
        result: { reset: true },
      };
    },
  },
  {
    name: 'explain_current_view',
    description: 'Explain the current hotspot and scenario.',
    args: {},
    stateChanging: false,
    execute(ctx) {
      const activeHotspot = getActiveHotspot(ctx.location, ctx.sceneState.activeHotspotId);
      const activeScenario = getActiveScenario(ctx.location, ctx.sceneState.activeScenarioId);
      return {
        response: buildCurrentViewResponse(ctx.location, activeHotspot, activeScenario),
        result: { hotspotId: activeHotspot.id, scenarioId: activeScenario.id },
      };
    },
  },
  {
    name: 'explain_flood_risk',
    description: 'Explain which hotspot floods first or why.',
    args: { hotspotId: 'Optional hotspot id or spoken hotspot name.' },
    stateChanging: false,
    execute(ctx, args) {
      let hotspot = getActiveHotspot(ctx.location, ctx.sceneState.activeHotspotId);
      if (args.hotspotId != null) {
        const match = findHotspotByIdOrAlias(ctx.location, args.hotspotId);
        if (match.clarification) {
          return {
            clarification: true,
            response: buildClarificationResponseForMatches('hotspot', match.matches),
            result: { ambiguous: true },
          };
        }
        hotspot = assertDefined(match.hotspot, 'Resolved hotspot was missing.');
      }
      return {
        response: buildFloodRiskResponse(hotspot),
        result: { hotspotId: hotspot.id },
      };
    },
  },
  {
    name: 'explain_sources',
    description: 'Explain which data sources the scene uses.',
    args: {},
    stateChanging: false,
    execute(ctx) {
      return {
        response: buildSourcesResponse(ctx.location),
        result: { sources: ctx.location.sources },
      };
    },
  },
  {
    name: 'help_with_commands',
    description: 'Explain what commands the user can say.',
    args: {},
    stateChanging: false,
    execute(ctx) {
      return {
        response: buildHelpResponse(ctx.location),
        result: { examples: ['show 2050', 'zoom out', 'go to the waterfront'] },
      };
    },
  },
];

export function getVoiceAgentToolDefinitions() {
  return TOOL_DEFINITIONS;
}

export function getVoiceAgentToolSchema() {
  return TOOL_DEFINITIONS.map((tool) => ({
    name: tool.name,
    description: tool.description,
    args: tool.args,
  }));
}

export function executeVoiceAgentTool(
  ctx: VoiceAgentToolContext,
  toolCall: VoiceAgentToolCall,
) {
  const tool = TOOL_DEFINITIONS.find((entry) => entry.name === toolCall.toolName);
  if (!tool) {
    throw new Error(`Unknown tool: ${toolCall.toolName}`);
  }

  return {
    definition: tool,
    execution: tool.execute(ctx, toolCall.args),
  };
}
