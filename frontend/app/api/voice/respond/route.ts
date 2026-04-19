import { NextResponse } from 'next/server';

import { getLocationBySlug } from '@/lib/locations';
import { runVoiceAgentTurn } from '@/lib/voice-agent/harness';
import type { VoiceAgentSceneState } from '@/lib/voice-agent/types';

export const runtime = 'nodejs';
export const maxDuration = 60;

export async function POST(request: Request) {
  const { transcript, locationSlug, sceneState } = (await request.json()) as {
    transcript?: string;
    locationSlug?: string;
    sceneState?: VoiceAgentSceneState;
  };

  if (!transcript?.trim()) {
    return NextResponse.json({ error: 'transcript is required.' }, { status: 400 });
  }

  if (!locationSlug?.trim()) {
    return NextResponse.json({ error: 'locationSlug is required.' }, { status: 400 });
  }

  if (!sceneState) {
    return NextResponse.json({ error: 'sceneState is required.' }, { status: 400 });
  }

  const location = getLocationBySlug(locationSlug);
  if (!location) {
    return NextResponse.json({ error: 'Unknown locationSlug.' }, { status: 404 });
  }

  try {
    const result = await runVoiceAgentTurn({
      transcript: transcript.trim(),
      location,
      sceneState,
    });

    return NextResponse.json(result);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : 'Voice agent request failed.';
    const status = /Missing NVIDIA_API_KEY/i.test(message) ? 503 : 502;
    return NextResponse.json({ error: message }, { status });
  }
}
