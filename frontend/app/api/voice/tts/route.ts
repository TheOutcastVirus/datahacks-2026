import { NextResponse } from 'next/server';

const ELEVENLABS_API_URL = 'https://api.elevenlabs.io/v1/text-to-speech';

export const runtime = 'nodejs';

export async function POST(request: Request) {
  const apiKey = process.env.ELEVENLABS_API_KEY;
  const voiceId = process.env.ELEVENLABS_VOICE_ID;
  const modelId = process.env.ELEVENLABS_MODEL_ID ?? 'eleven_flash_v2_5';

  if (!apiKey || !voiceId) {
    return NextResponse.json(
      { error: 'Missing ElevenLabs configuration.' },
      { status: 503 },
    );
  }

  const { text } = (await request.json()) as { text?: string };
  const trimmed = text?.trim();

  if (!trimmed) {
    return NextResponse.json({ error: 'Text is required.' }, { status: 400 });
  }

  const response = await fetch(
    `${ELEVENLABS_API_URL}/${voiceId}/stream?output_format=mp3_44100_128`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'xi-api-key': apiKey,
      },
      body: JSON.stringify({
        text: trimmed,
        model_id: modelId,
      }),
    },
  );

  if (!response.ok || !response.body) {
    const err = await response.text().catch(() => '');
    console.error('ElevenLabs error:', err);
    return NextResponse.json(
      { error: err || 'Unable to synthesize speech right now.' },
      { status: 502 },
    );
  }

  return new Response(response.body, {
    headers: {
      'Content-Type': 'audio/mpeg',
      'Cache-Control': 'no-store',
    },
  });
}
