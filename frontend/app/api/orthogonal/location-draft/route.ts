import { NextResponse } from 'next/server';

import {
  createLocationRecordSnippet,
  normalizeGeneratedLocationDraft,
} from '@/lib/orthogonal-drafts';
import type { GeneratedLocationDraft, LocationOnboardingResponse } from '@/lib/orthogonal-types';
import { extractJsonObject, runNvidiaPrompt } from '@/lib/server/nvidia';
import {
  getOrthogonalSetupMessage,
  OrthogonalCliError,
  scrapeWithOrthogonal,
  searchOrthogonalCapabilities,
} from '@/lib/server/orthogonal';

export const runtime = 'nodejs';

type LocationDraftRequest = {
  query?: string;
  siteNotes?: string;
  referenceUrl?: string;
};

const CAVEAT =
  'Draft generated from your prompt plus Orthogonal capability discovery. Validate every source, hotspot, and scenario before adding it to the production location catalog.';

export async function POST(request: Request) {
  const { query, siteNotes, referenceUrl } = (await request.json()) as LocationDraftRequest;

  if (!query?.trim()) {
    return NextResponse.json({ error: 'query is required.' }, { status: 400 });
  }

  try {
    const orthogonal = await searchOrthogonalCapabilities(
      `location onboarding for ${query.trim()} with geocoding elevation coastal data satellite imagery scraping`,
    );
    const scrapeSummary =
      referenceUrl?.trim() && referenceUrl.startsWith('http')
        ? await scrapeWithOrthogonal(referenceUrl.trim()).catch(() => '')
        : '';

    const modelText = await runNvidiaPrompt(
      `You generate starter Sojs location records for a flood-visualization demo.
Return JSON only.
Never claim that a source or scenario is fully verified.
Treat all outputs as draft scaffolding for a developer.
Keep hotspot and scenario IDs kebab-case.
Limit hotspots to 4 and scenarios to 3.`,
      `User location query:
${query.trim()}

Optional site notes:
${siteNotes?.trim() || 'None provided.'}

Optional reference scrape:
${scrapeSummary || 'No reference scrape provided.'}

Orthogonal skill search output:
${orthogonal.skillSearch}

Orthogonal API search output:
${orthogonal.apiSearch}

Return this exact JSON shape:
{
  "slug": "string",
  "name": "string",
  "region": "string",
  "description": "string",
  "status": "string",
  "updatedAt": "string",
  "sources": ["string"],
  "hotspots": [
    {
      "id": "string",
      "name": "string",
      "aliases": ["string"],
      "description": "string",
      "explainText": "string"
    }
  ],
  "scenarios": [
    {
      "id": "string",
      "label": "string",
      "year": 2026,
      "riseMeters": 0,
      "narration": "string",
      "color": "string"
    }
  ],
  "defaultHotspotId": "string",
  "notes": ["string"],
  "orthogonalWorkflow": ["string"],
  "exportChecklist": ["string"]
}

Requirements:
- Sources should be phrased as recommended or likely data sources, not verified citations.
- Scenarios are starter demo scenarios, not scientific claims.
- Notes should tell the developer what still needs validation.
- orthogonalWorkflow should describe which Orthogonal-discovered capabilities to use next.
- exportChecklist should mention how to turn the result into a brief/doc/email workflow.`,
    );

    const parsed = JSON.parse(extractJsonObject(modelText)) as Partial<GeneratedLocationDraft>;
    const draft = normalizeGeneratedLocationDraft(parsed, query.trim());
    const payload: LocationOnboardingResponse = {
      draft,
      locationRecordSnippet: createLocationRecordSnippet(draft),
      orthogonalSearchSummary: {
        skillSearch: orthogonal.skillSearch,
        apiSearch: orthogonal.apiSearch,
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

    const message = error instanceof Error ? error.message : 'Unable to generate location draft.';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
