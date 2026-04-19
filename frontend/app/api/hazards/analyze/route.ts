import { NextResponse } from 'next/server';

import type { HazardMarker } from '@/lib/viewer-types';

export const runtime = 'nodejs';

const NVIDIA_CHAT_URL = 'https://integrate.api.nvidia.com/v1/chat/completions';

type AnalyzeRequest = {
  hazards: HazardMarker[];
  locationName?: string;
  question?: string;
};

type AnalyzeResponse = {
  analysis: string;
  topRisks: Array<{ id: string; rationale: string }>;
};

function fallbackAnalysis(
  hazards: HazardMarker[],
  locationName: string | undefined,
): AnalyzeResponse {
  const sorted = [...hazards].sort((a, b) => b.severity - a.severity);
  const topRisks = sorted.slice(0, 3).map((hazard) => ({
    id: hazard.id,
    rationale: hazard.summary,
  }));
  const analysis = hazards.length
    ? `Identified ${hazards.length} geometric hazard proxies in ${locationName ?? 'the scene'}.`
    : `No hazards available for ${locationName ?? 'this scene'} yet.`;
  return { analysis, topRisks };
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
  const body = (await request.json()) as AnalyzeRequest;
  const hazards = Array.isArray(body.hazards) ? body.hazards : [];

  const apiKey = process.env.NVIDIA_API_KEY;
  const model = process.env.NVIDIA_ANALYSIS_MODEL ?? 'google/gemma-4-31b-it';

  if (!apiKey || hazards.length === 0) {
    return NextResponse.json(fallbackAnalysis(hazards, body.locationName));
  }

  try {
    const systemPrompt =
      'You analyze structured hazard markers extracted from a 3D Gaussian-splat scan. ' +
      'The inputs are geometric proxies (not confirmed damage). Rank risk and explain concretely. ' +
      'Respond with STRICT JSON only matching: ' +
      '{"analysis": "<2-4 sentences>", "topRisks": [{"id": "<marker id>", "rationale": "<one sentence>"}]}.';
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
        temperature: 0.7,
        top_p: 0.95,
        max_tokens: 1024,
        stream: false,
        chat_template_kwargs: { enable_thinking: false },
      }),
    });
    if (!response.ok) {
      return NextResponse.json(fallbackAnalysis(hazards, body.locationName));
    }
    const data = (await response.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };
    const content = data.choices?.[0]?.message?.content?.trim();
    if (!content) {
      return NextResponse.json(fallbackAnalysis(hazards, body.locationName));
    }
    const jsonSlice = extractJson(content);
    if (!jsonSlice) {
      return NextResponse.json(fallbackAnalysis(hazards, body.locationName));
    }
    const parsed = JSON.parse(jsonSlice) as Partial<AnalyzeResponse>;
    const fallback = fallbackAnalysis(hazards, body.locationName);
    const result: AnalyzeResponse = {
      analysis: parsed.analysis?.trim() || fallback.analysis,
      topRisks: Array.isArray(parsed.topRisks) && parsed.topRisks.length
        ? parsed.topRisks.filter((r) => r && typeof r.id === 'string')
        : fallback.topRisks,
    };
    return NextResponse.json(result);
  } catch {
    return NextResponse.json(fallbackAnalysis(hazards, body.locationName));
  }
}
