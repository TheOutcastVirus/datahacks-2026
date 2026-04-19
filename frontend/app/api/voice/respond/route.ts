import axios from 'axios';
import { NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const maxDuration = 60;

const NVIDIA_NIM_URL = 'https://integrate.api.nvidia.com/v1/chat/completions';
const MODEL = 'moonshotai/kimi-k2.5';

type NIMDeltaPart =
  | string
  | {
      text?: string;
      type?: string;
    };

type NIMStreamChunk = {
  choices?: Array<{
    delta?: {
      content?: string | NIMDeltaPart[];
      reasoning_content?: string | NIMDeltaPart[];
    };
    message?: {
      content?: string | NIMDeltaPart[];
      reasoning_content?: string | NIMDeltaPart[];
    };
  }>;
};

function extractTextParts(content: string | NIMDeltaPart[] | undefined) {
  if (!content) {
    return '';
  }

  if (typeof content === 'string') {
    return content;
  }

  return content
    .map((part) => (typeof part === 'string' ? part : part.text ?? ''))
    .join('');
}

function collectTextFromChunk(chunk: NIMStreamChunk) {
  const choice = chunk.choices?.[0];
  return (
    extractTextParts(choice?.delta?.content) ||
    extractTextParts(choice?.delta?.reasoning_content) ||
    extractTextParts(choice?.message?.content) ||
    extractTextParts(choice?.message?.reasoning_content)
  );
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

  const payload = {
    model: MODEL,
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: transcript.trim() },
    ],
    max_tokens: 384,
    temperature: 0.55,
    top_p: 0.9,
    stream: true,
    chat_template_kwargs: { thinking: false },
  };

  try {
    const response = await axios.post(NVIDIA_NIM_URL, payload, {
      headers: {
        Authorization: `Bearer ${apiKey}`,
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
      },
      responseType: 'stream',
      // Cap a single request — overall route is bounded by `maxDuration` above.
      timeout: 55_000,
    });

    let text = '';
    let buffer = '';

    for await (const chunk of response.data as AsyncIterable<Buffer | string>) {
      buffer += chunk.toString();

      const events = buffer.split('\n\n');
      buffer = events.pop() ?? '';

      for (const event of events) {
        for (const line of event.split('\n')) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;

          const raw = trimmed.slice(5).trim();
          if (!raw || raw === '[DONE]') continue;

          try {
            const parsed = JSON.parse(raw) as NIMStreamChunk;
            text += collectTextFromChunk(parsed);
          } catch (parseError) {
            console.warn('Unable to parse NVIDIA NIM SSE chunk:', raw, parseError);
          }
        }
      }
    }

    const finalText = text.trim();
    if (!finalText) {
      return NextResponse.json(
        { error: 'AI response came back empty.' },
        { status: 502 },
      );
    }

    return NextResponse.json({ text: finalText });
  } catch (error) {
    console.error('NVIDIA NIM voice error:', error);

    if (axios.isAxiosError(error)) {
      if (error.code === 'ECONNABORTED') {
        return NextResponse.json(
          { error: 'NVIDIA NIM timed out before responding.' },
          { status: 504 },
        );
      }

      const status = error.response?.status;
      const body = error.response?.data;
      const detail =
        typeof body === 'string'
          ? body.slice(0, 500)
          : body && typeof body === 'object' && 'error' in body
            ? String((body as { error?: unknown }).error)
            : error.message;

      return NextResponse.json(
        { error: detail || 'NVIDIA NIM request failed.' },
        { status: status && status >= 400 && status < 600 ? status : 502 },
      );
    }

    const message =
      error instanceof Error ? error.message : 'NVIDIA NIM request failed.';

    return NextResponse.json({ error: message }, { status: 502 });
  }
}
