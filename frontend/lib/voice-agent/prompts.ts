import type { LocationRecord } from '@/lib/locations';
import type {
  VoiceAgentSceneState,
  VoiceAgentToolCall,
  VoiceAgentTrace,
} from '@/lib/voice-agent/types';

export const VOICE_AGENT_PROMPT_ID = 'sojs-voice-agent-v1';

type PromptTool = {
  name: string;
  description: string;
  args: Record<string, string>;
};

function formatTools(tools: PromptTool[]) {
  return tools
    .map((tool) => {
      const args = Object.entries(tool.args)
        .map(([name, description]) => `  - ${name}: ${description}`)
        .join('\n');
      return `- ${tool.name}: ${tool.description}\n${args || '  - no args'}`;
    })
    .join('\n');
}

export function buildVoiceAgentSystemPrompt(tools: PromptTool[]) {
  return `You are the Sojs voice agent for an in-app flood visualization.
You may only use the tools listed below and the local scene context provided to you.
Prefer tool calls over unsupported claims.
Keep spoken output to 1-2 short sentences.
Never invent hotspots, scenarios, or data sources.
If a request is ambiguous, ask a clarifying question instead of guessing.
Never emit more than one state-changing action unless the user explicitly asks for a sequence.

Return a single JSON object with this shape:
{
  "toolCalls": [{"toolName":"...", "callId":"...", "args": {...}}],
  "response": {"speech":"...", "caption":"..."},
  "needsClarification": false
}

Rules:
- Use "toolCalls" when the user asks to navigate, change view state, explain the current view, explain flood risk, explain sources, or ask for command help.
- Use "response" without tools only for simple conversational replies that do not require app state changes or grounded lookups.
- If clarification is required, set "needsClarification": true and include a short "response".
- Do not output markdown. Only output JSON.

Allowed tools:
${formatTools(tools)}`;
}

export function buildVoiceAgentUserPrompt(
  transcript: string,
  location: LocationRecord,
  sceneState: VoiceAgentSceneState,
) {
  return JSON.stringify(
    {
      transcript,
      location: {
        slug: location.slug,
        name: location.name,
        region: location.region,
        description: location.description,
        sources: location.sources,
        hotspots: location.hotspots.map((hotspot) => ({
          id: hotspot.id,
          name: hotspot.name,
          aliases: hotspot.aliases,
          description: hotspot.description,
        })),
        scenarios: location.scenarios.map((scenario) => ({
          id: scenario.id,
          label: scenario.label,
          year: scenario.year,
          riseMeters: scenario.riseMeters,
          narration: scenario.narration,
        })),
      },
      sceneState,
    },
    null,
    2,
  );
}

export function buildVoiceAgentRepairPrompt(modelText: string) {
  return `Repair this into a valid JSON object matching the required schema exactly. Do not add markdown.

Original response:
${modelText}`;
}

export function buildVoiceAgentSummaryPrompt(
  transcript: string,
  trace: VoiceAgentTrace,
) {
  return `Summarize the tool results for the Sojs user in one or two short grounded sentences.
Return a JSON object like:
{"speech":"...","caption":"..."}

User transcript: ${JSON.stringify(transcript)}
Tool results:
${JSON.stringify(trace.toolResults, null, 2)}`;
}
