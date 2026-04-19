import { NextResponse } from 'next/server';

const ASSEMBLYAI_TOKEN_URL = 'https://streaming.assemblyai.com/v3/token';

export const runtime = 'nodejs';

export async function GET() {
  const apiKey = process.env.ASSEMBLYAI_API_KEY;

  if (!apiKey) {
    return NextResponse.json(
      { error: 'Missing AssemblyAI_API_KEY configuration.' },
      { status: 503 },
    );
  }

  const response = await fetch(`${ASSEMBLYAI_TOKEN_URL}?expires_in_seconds=60`, {
    method: 'GET',
    headers: {
      Authorization: apiKey,
    },
    cache: 'no-store',
  });

  if (!response.ok) {
    return NextResponse.json(
      { error: 'Unable to create an AssemblyAI streaming token.' },
      { status: 502 },
    );
  }

  const body = (await response.json()) as {
    token?: string;
    expires_in_seconds?: number;
  };

  if (!body.token) {
    return NextResponse.json(
      { error: 'AssemblyAI did not return a streaming token.' },
      { status: 502 },
    );
  }

  return NextResponse.json(
    {
      token: body.token,
      expiresInSeconds: body.expires_in_seconds ?? 60,
    },
    {
      headers: {
        'Cache-Control': 'no-store',
      },
    },
  );
}
