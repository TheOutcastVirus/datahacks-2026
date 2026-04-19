import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

const NVIDIA_NIM_URL = 'https://integrate.api.nvidia.com/v1/chat/completions';
const MODEL = 'google/gemma-4-31b-it';

type NIMContentPart =
  | string
  | {
      text?: string;
      type?: string;
    };

type NIMResponseBody = {
  choices?: Array<{
    message?: {
      content?: string | NIMContentPart[];
      reasoning_content?: string | NIMContentPart[];
    };
  }>;
};

function extractTextParts(content: string | NIMContentPart[] | undefined) {
  if (!content) {
    return '';
  }

  if (typeof content === 'string') {
    return content.trim();
  }

  return content
    .map((part) => {
      if (typeof part === 'string') {
        return part;
      }

      return part.text ?? '';
    })
    .join(' ')
    .trim();
}

export async function POST(request: Request) {
  const apiKey = process.env.NVIDIA_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: 'Missing NVIDIA_API_KEY.' }, { status: 503 });
  }

  const { transcript, context } = (await request.json()) as {
    transcript?: string;
    context?: string;
  };

  if (!transcript?.trim()) {
    return NextResponse.json({ error: 'transcript is required.' }, { status: 400 });
  }

  const systemPrompt = `You are a helpful flood-risk guide for an interactive 3D visualization.
The user is viewing a real-time sea level rise simulation. Answer conversationally in 1-3 sentences.
Context about the current scene:
${context ?? 'No scene context provided.'}`;

  let response: Response;

  try {
    response = await fetch(NVIDIA_NIM_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: MODEL,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: transcript.trim() },
        ],
        max_tokens: 300,
        temperature: 1.0,
        top_p: 0.95,
        stream: false,
      }),
      signal: AbortSignal.timeout(15_000),
    });
  } catch (error) {
    console.error('NVIDIA NIM fetch failed:', error);
    const message =
      error instanceof Error && /timeout/i.test(error.message)
        ? 'NVIDIA NIM timed out before responding.'
        : 'NVIDIA NIM request failed before a response was received.';
    return NextResponse.json({ error: message }, { status: 504 });
  }

  if (!response.ok) {
    const err = await response.text().catch(() => '');
    console.error('NVIDIA NIM error:', err);
    return NextResponse.json(
      { error: err || 'AI response failed.' },
      { status: 502 },
    );
  }

  const body = (await response.json()) as NIMResponseBody;
  const message = body.choices?.[0]?.message;
  const text =
    extractTextParts(message?.content) || extractTextParts(message?.reasoning_content);

  if (!text) {
    console.error('NVIDIA NIM returned an empty response body:', body);
    return NextResponse.json(
      { error: 'AI response came back empty.' },
      { status: 502 },
    );
  }

  return NextResponse.json({ text });
}
