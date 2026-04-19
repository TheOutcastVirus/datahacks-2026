import { NextResponse } from 'next/server';

import type { ResearchBrief, ResearchBriefResponse } from '@/lib/orthogonal-types';
import { extractJsonObject, runNvidiaPrompt } from '@/lib/server/nvidia';
import {
  getOrthogonalSetupMessage,
  OrthogonalCliError,
  scrapeWithOrthogonal,
  searchOrthogonalCapabilities,
} from '@/lib/server/orthogonal';

export const runtime = 'nodejs';

type ResearchBriefRequest = {
  locationName?: string;
  region?: string;
  locationDescription?: string;
  activeHotspot?: string;
  activeScenario?: string;
  audience?: string;
  referenceUrls?: string[];
};

const CAVEAT =
  'This brief is a pitch/research draft. Treat it as a working document until the cited sources and any scraped references are reviewed by the team.';

export async function POST(request: Request) {
  const {
    locationName,
    region,
    locationDescription,
    activeHotspot,
    activeScenario,
    audience,
    referenceUrls,
  } = (await request.json()) as ResearchBriefRequest;

  if (!locationName?.trim()) {
    return NextResponse.json({ error: 'locationName is required.' }, { status: 400 });
  }

  try {
    const orthogonal = await searchOrthogonalCapabilities(
      `research summarize create google doc notion email brief for ${locationName.trim()} waterfront flood risk`,
    );
    const scrapeOutputs = await Promise.all(
      (referenceUrls ?? [])
        .map((url) => url.trim())
        .filter((url) => url.startsWith('http'))
        .slice(0, 3)
        .map((url) => scrapeWithOrthogonal(url).catch(() => `Failed to scrape ${url}`)),
    );

    const modelText = await runNvidiaPrompt(
      `You write concise stakeholder briefs for Sojs, a sea-level-rise visualization demo.
Return JSON only.
Use cautious language.
Do not invent specific policy claims if the source material is thin.
If evidence is sparse, say so in the evidence or nextActions fields.`,
      `Location:
- Name: ${locationName.trim()}
- Region: ${region?.trim() || 'Unknown region'}
- Description: ${locationDescription?.trim() || 'No description provided'}
- Active hotspot: ${activeHotspot?.trim() || 'Not specified'}
- Active scenario: ${activeScenario?.trim() || 'Not specified'}
- Audience: ${audience?.trim() || 'City resilience team'}

Orthogonal skill search output:
${orthogonal.skillSearch}

Orthogonal API search output:
${orthogonal.apiSearch}

Scraped source material:
${scrapeOutputs.length > 0 ? scrapeOutputs.join('\n\n---\n\n') : 'No external pages scraped.'}

Return this exact JSON shape:
{
  "title": "string",
  "audience": "string",
  "executiveSummary": "string",
  "whyNow": "string",
  "evidence": ["string"],
  "keyRisks": ["string"],
  "stakeholders": ["string"],
  "demoTalkingPoints": ["string"],
  "nextActions": ["string"],
  "exportActions": ["string"],
  "orthogonalWorkflow": ["string"]
}

Requirements:
- evidence should reference either scraped material or explicitly note that this is a draft research scaffold.
- exportActions should cover Google Docs or Notion plus an email-ready handoff.
- orthogonalWorkflow should describe how Orthogonal can operationalize the brief next.`,
    );

    const brief = JSON.parse(extractJsonObject(modelText)) as ResearchBrief;
    const payload: ResearchBriefResponse = {
      brief,
      orthogonalSearchSummary: {
        skillSearch: orthogonal.skillSearch,
        apiSearch: orthogonal.apiSearch,
        scrapeSummary: scrapeOutputs.join('\n\n'),
      },
      caveat: CAVEAT,
    };

    return NextResponse.json(payload);
  } catch (error) {
    if (error instanceof OrthogonalCliError) {
      return NextResponse.json(
        {
          error: getOrthogonalSetupMessage(error),
        },
        { status: 503 },
      );
    }

    const message = error instanceof Error ? error.message : 'Unable to generate research brief.';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
