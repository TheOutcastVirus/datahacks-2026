import { NextResponse } from 'next/server';

import type { HazardMarker } from '@/lib/viewer-types';

export const runtime = 'nodejs';

const NVIDIA_CHAT_URL = 'https://integrate.api.nvidia.com/v1/chat/completions';

type NarrateRequest = {
  hazards: HazardMarker[];
  locationName?: string;
  question?: string;
};

type NarrateResponse = {
  hoverTexts: Record<string, string>;
  spokenSummary: string;
};

function fallbackNarration(
  hazards: HazardMarker[],
  locationName: string | undefined,
): NarrateResponse {
  const hoverTexts: Record<string, string> = {};
  for (const hazard of hazards) hoverTexts[hazard.id] = hazard.summary;
  const top = [...hazards].sort((a, b) => b.severity - a.severity)[0];
  const spokenSummary = top
    ? `Scan complete for ${locationName ?? 'this scene'}. Marker ${top.id} is the highest-severity hazard: ${top.summary}`
    : `No hazards available for ${locationName ?? 'this scene'} yet.`;
  return { hoverTexts, spokenSummary };
}

function extractJson(raw: string): string | null {
  const fence = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fence ? fence[1] : raw;
  const start = candidate.indexOf('{');
  const end = candidate.lastIndexOf('}');
  if (start < 0 || end <= start) return null;
  return candidate.slice(start, end + 1);
}

export async function POST(request: Request) {
  const body = (await request.json()) as NarrateRequest;
  const hazards = Array.isArray(body.hazards) ? body.hazards : [];

  const apiKey = process.env.NVIDIA_API_KEY;
  const model = process.env.NVIDIA_NARRATE_MODEL ?? 'moonshotai/kimi-k2.5';

  if (!apiKey || hazards.length === 0) {
    return NextResponse.json(fallbackNarration(hazards, body.locationName));
  }

  try {
    const systemPrompt =
      'You narrate coastal and geologic hazard markers derived from a 3D Gaussian-splat scan. ' +
      'Be cautious and concrete. Emphasize that these are geometric proxies, not confirmed damage. ' +
      'Respond with STRICT JSON only, no prose before or after, matching this schema: ' +
      '{"hoverTexts": {"<id>": "<one short sentence>"}, "spokenSummary": "<2-3 sentences, suitable for text-to-speech>"}.';
    const userPayload = {
      locationName: body.locationName,
      question: body.question,
      hazards: hazards.map(({ id, label, severity, metrics, summary }) => ({
        id,
        label,
        severity,
        metrics,
        summary,
      })),
    };
    const response = await fetch(NVIDIA_CHAT_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
        Accept: 'application/json',
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: JSON.stringify(userPayload) },
        ],
        temperature: 0.6,
        top_p: 1,
        max_tokens: 1024,
        stream: false,
        chat_template_kwargs: { thinking: false },
      }),
    });
    if (!response.ok) {
      return NextResponse.json(fallbackNarration(hazards, body.locationName));
    }
    const data = (await response.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };
    const content = data.choices?.[0]?.message?.content?.trim();
    if (!content) {
      return NextResponse.json(fallbackNarration(hazards, body.locationName));
    }
    const jsonSlice = extractJson(content);
    if (!jsonSlice) {
      return NextResponse.json(fallbackNarration(hazards, body.locationName));
    }
    const parsed = JSON.parse(jsonSlice) as Partial<NarrateResponse>;
    const fallback = fallbackNarration(hazards, body.locationName);
    const result: NarrateResponse = {
      hoverTexts: { ...fallback.hoverTexts, ...(parsed.hoverTexts ?? {}) },
      spokenSummary: parsed.spokenSummary?.trim() || fallback.spokenSummary,
    };
    return NextResponse.json(result);
  } catch {
    return NextResponse.json(fallbackNarration(hazards, body.locationName));
  }
}
