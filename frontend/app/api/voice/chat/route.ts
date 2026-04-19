import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

const NVIDIA_CHAT_URL = 'https://integrate.api.nvidia.com/v1/chat/completions';

const KIMI_MODEL = 'moonshotai/kimi-k2.5';
const GEMMA_MODEL = 'google/gemma-4-31b-it';

type ChatRequest = {
  transcript: string;
  locationName: string;
  region: string;
  year: number;
  riseMeters: number;
};

export type Risk = {
  label: string;
  severity: 'low' | 'medium' | 'high';
  description: string;
};

export type ChatResponse = {
  reply: string;
  risks: Risk[];
};

function getApiKey() {
  const key = process.env.NVIDIA_API_KEY;
  if (!key) throw new Error('NVIDIA_API_KEY is not configured.');
  return key;
}

function extractJson(raw: string): string | null {
  const fence = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fence ? fence[1] : raw;
  const start = candidate.indexOf('[');
  const end = candidate.lastIndexOf(']');
  if (start < 0 || end <= start) return null;
  return candidate.slice(start, end + 1);
}

async function callGemmaRisks(
  apiKey: string,
  locationName: string,
  region: string,
  year: number,
  riseMeters: number,
): Promise<Risk[]> {
  const system =
    'You are an environmental scientist specializing in coastal climate risk. ' +
    'Given a location, year, and sea-level rise in meters, identify the top 3 concrete environmental risks. ' +
    'Be specific and grounded — e.g. "soil erosion exposing foundations", "saltwater intrusion into aquifers". ' +
    'Respond with STRICT JSON array only: ' +
    '[{"label": "<short name>", "severity": "low|medium|high", "description": "<one sentence>"}]';
  const user = `Location: ${locationName} (${region}). Year: ${year}. Sea-level rise: ${riseMeters.toFixed(2)} m above baseline.`;

  const res = await fetch(NVIDIA_CHAT_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: GEMMA_MODEL,
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: user },
      ],
      temperature: 0.6,
      max_tokens: 512,
      stream: false,
      chat_template_kwargs: { enable_thinking: false },
    }),
  });

  if (!res.ok) return [];
  const data = (await res.json()) as { choices?: Array<{ message?: { content?: string } }> };
  const content = data.choices?.[0]?.message?.content?.trim() ?? '';
  const jsonSlice = extractJson(content);
  if (!jsonSlice) return [];
  try {
    return JSON.parse(jsonSlice) as Risk[];
  } catch {
    return [];
  }
}

const ANALYZE_RISKS_TOOL = {
  type: 'function' as const,
  function: {
    name: 'analyze_environmental_risks',
    description:
      'Analyze environmental and climate risks for the current coastal scene based on the year and sea-level rise. ' +
      'Call this whenever the user asks about risks, hazards, flooding, erosion, or environmental impacts.',
    parameters: {
      type: 'object',
      properties: {
        reason: {
          type: 'string',
          description: 'Brief reason why you are calling this tool.',
        },
      },
      required: [],
    },
  },
};

export async function POST(request: Request) {
  const body = (await request.json()) as ChatRequest;
  const { transcript, locationName, region, year, riseMeters } = body;

  let apiKey: string;
  try {
    apiKey = getApiKey();
  } catch {
    return NextResponse.json<ChatResponse>({
      reply: 'Voice assistant is not configured. Please add NVIDIA_API_KEY.',
      risks: [],
    });
  }

  const system =
    `You are a knowledgeable coastal flood-risk assistant embedded in a 3D sea-level visualization. ` +
    `Current scene: ${locationName} (${region}), year ${year}, sea-level rise ${riseMeters.toFixed(2)} m. ` +
    `Answer the user concisely in 1-3 sentences suitable for text-to-speech. ` +
    `If the user asks about risks, hazards, or environmental impacts, call the analyze_environmental_risks tool.`;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const messages: Array<Record<string, any>> = [
    { role: 'system', content: system },
    { role: 'user', content: transcript },
  ];

  // First Kimi call — may request tool use
  const firstRes = await fetch(NVIDIA_CHAT_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: KIMI_MODEL,
      messages,
      tools: [ANALYZE_RISKS_TOOL],
      tool_choice: 'auto',
      temperature: 0.7,
      max_tokens: 256,
      stream: false,
    }),
  });

  if (!firstRes.ok) {
    return NextResponse.json<ChatResponse>({
      reply: 'I couldn\'t process that. Please try again.',
      risks: [],
    });
  }

  const firstData = (await firstRes.json()) as {
    choices?: Array<{
      message?: {
        content?: string;
        tool_calls?: Array<{ id: string; function: { name: string; arguments: string } }>;
      };
    }>;
  };

  const firstMessage = firstData.choices?.[0]?.message;
  const toolCalls = firstMessage?.tool_calls;

  // No tool call — return Kimi's direct reply
  if (!toolCalls?.length) {
    return NextResponse.json<ChatResponse>({
      reply: firstMessage?.content?.trim() ?? 'No response.',
      risks: [],
    });
  }

  // Tool call requested — run Gemma in parallel for each call (typically one)
  const toolCall = toolCalls[0];
  const risks = await callGemmaRisks(apiKey, locationName, region, year, riseMeters);

  // Feed tool result back to Kimi for final spoken reply
  const toolResultMessages = [
    ...messages,
    { role: 'assistant', content: firstMessage?.content ?? '', ...{ tool_calls: toolCalls } },
    {
      role: 'tool',
      tool_call_id: toolCall.id,
      name: toolCall.function.name,
      content: JSON.stringify(risks),
    },
  ];

  const secondRes = await fetch(NVIDIA_CHAT_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: KIMI_MODEL,
      messages: toolResultMessages,
      temperature: 0.7,
      max_tokens: 256,
      stream: false,
    }),
  });

  const finalReply = secondRes.ok
    ? ((
        (await secondRes.json()) as {
          choices?: Array<{ message?: { content?: string } }>;
        }
      ).choices?.[0]?.message?.content?.trim() ?? 'Analysis complete.')
    : 'Analysis complete.';

  return NextResponse.json<ChatResponse>({ reply: finalReply, risks });
}
