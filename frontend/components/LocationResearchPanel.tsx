'use client';

import { useState } from 'react';

import type { ResearchBriefResponse } from '@/lib/orthogonal-types';

type LocationResearchPanelProps = {
  locationName: string;
  region: string;
  locationDescription: string;
  activeHotspot: string;
  activeScenario: string;
};

export default function LocationResearchPanel({
  locationName,
  region,
  locationDescription,
  activeHotspot,
  activeScenario,
}: LocationResearchPanelProps) {
  const [audience, setAudience] = useState('City resilience team');
  const [referenceUrls, setReferenceUrls] = useState('');
  const [result, setResult] = useState<ResearchBriefResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleGenerate = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/orthogonal/research-brief', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          locationName,
          region,
          locationDescription,
          activeHotspot,
          activeScenario,
          audience,
          referenceUrls: referenceUrls
            .split('\n')
            .map((entry) => entry.trim())
            .filter(Boolean),
        }),
      });
      const data = (await response.json()) as ResearchBriefResponse | { error?: string };

      if (!response.ok) {
        throw new Error(('error' in data && data.error) || 'Unable to generate research brief.');
      }

      setResult(data as ResearchBriefResponse);
    } catch (requestError) {
      setResult(null);
      setError(requestError instanceof Error ? requestError.message : 'Request failed.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <section className="research-panel">
      <div className="research-panel-head">
        <div>
          <h3 className="research-panel-title">Pitch / Research Assistant</h3>
          <p className="research-panel-copy">
            Generate a stakeholder brief for the current scene, then use the suggested workflow
            to turn it into a doc, Notion page, or email handoff.
          </p>
        </div>
      </div>

      <label className="orth-field">
        <span className="orth-label">Audience</span>
        <input
          className="orth-input"
          value={audience}
          onChange={(event) => setAudience(event.currentTarget.value)}
        />
      </label>

      <label className="orth-field">
        <span className="orth-label">Reference URLs</span>
        <textarea
          className="orth-textarea orth-textarea-compact"
          value={referenceUrls}
          onChange={(event) => setReferenceUrls(event.currentTarget.value)}
          placeholder="One URL per line for pages you want Orthogonal to scrape first."
          rows={3}
        />
      </label>

      <button type="button" className="orth-button orth-button-compact" onClick={handleGenerate} disabled={isLoading}>
        {isLoading ? 'Generating Brief…' : 'Generate Brief'}
      </button>

      {error ? <p className="orth-error">{error}</p> : null}

      {result ? (
        <div className="research-brief">
          <div className="research-brief-title">{result.brief.title}</div>
          <p className="orth-caveat">{result.caveat}</p>
          <p className="research-summary">{result.brief.executiveSummary}</p>

          <div className="orth-section-label">Why Now</div>
          <p className="research-summary">{result.brief.whyNow}</p>

          <div className="orth-columns">
            <div>
              <div className="orth-section-label">Evidence</div>
              <ul className="orth-list">
                {result.brief.evidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="orth-section-label">Key Risks</div>
              <ul className="orth-list">
                {result.brief.keyRisks.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </div>

          <div className="orth-columns">
            <div>
              <div className="orth-section-label">Stakeholders</div>
              <ul className="orth-list">
                {result.brief.stakeholders.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="orth-section-label">Demo Talking Points</div>
              <ul className="orth-list">
                {result.brief.demoTalkingPoints.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </div>

          <div className="orth-columns">
            <div>
              <div className="orth-section-label">Next Actions</div>
              <ul className="orth-list">
                {result.brief.nextActions.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="orth-section-label">Export Actions</div>
              <ul className="orth-list">
                {result.brief.exportActions.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
