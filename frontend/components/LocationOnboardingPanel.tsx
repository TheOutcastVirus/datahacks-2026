'use client';

import { useState } from 'react';

import type { LocationOnboardingResponse } from '@/lib/orthogonal-types';

export default function LocationOnboardingPanel() {
  const [query, setQuery] = useState('');
  const [siteNotes, setSiteNotes] = useState('');
  const [referenceUrl, setReferenceUrl] = useState('');
  const [result, setResult] = useState<LocationOnboardingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/orthogonal/location-draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          siteNotes,
          referenceUrl,
        }),
      });
      const data = (await response.json()) as LocationOnboardingResponse | { error?: string };

      if (!response.ok) {
        throw new Error(('error' in data && data.error) || 'Unable to generate location draft.');
      }

      setResult(data as LocationOnboardingResponse);
    } catch (submitError) {
      setResult(null);
      setError(submitError instanceof Error ? submitError.message : 'Request failed.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <section className="orth-panel">
      <div className="orth-panel-kicker">Orthogonal Flow 01</div>
      <h2 className="orth-panel-title">Semi-Automatic Location Onboarding</h2>
      <p className="orth-panel-copy">
        Start with an address, coordinates, or a site name. Sojs uses Orthogonal capability
        discovery to build a draft location card, workflow, and copy-pasteable
        <code>LocationRecord</code> scaffold.
      </p>

      <form className="orth-form" onSubmit={handleSubmit}>
        <label className="orth-field">
          <span className="orth-label">Address or Lat/Lng</span>
          <input
            className="orth-input"
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder="Seattle Waterfront, 47.6062,-122.3321"
            required
          />
        </label>

        <label className="orth-field">
          <span className="orth-label">Site Notes</span>
          <textarea
            className="orth-textarea"
            value={siteNotes}
            onChange={(event) => setSiteNotes(event.currentTarget.value)}
            placeholder="Why this site matters, what the team already knows, what you need next."
            rows={4}
          />
        </label>

        <label className="orth-field">
          <span className="orth-label">Reference URL</span>
          <input
            className="orth-input"
            value={referenceUrl}
            onChange={(event) => setReferenceUrl(event.currentTarget.value)}
            placeholder="https://example.com/waterfront-project"
          />
        </label>

        <button type="submit" className="orth-button" disabled={isLoading}>
          {isLoading ? 'Generating Draft…' : 'Generate Draft'}
        </button>
      </form>

      {error ? <p className="orth-error">{error}</p> : null}

      {result ? (
        <div className="orth-result">
          <div className="orth-result-head">
            <div>
              <div className="orth-result-kicker">Draft Result</div>
              <h3 className="orth-result-title">{result.draft.name}</h3>
              <p className="orth-result-subtitle">
                {result.draft.region} · {result.draft.status}
              </p>
            </div>
            <p className="orth-caveat">{result.caveat}</p>
          </div>

          <p className="orth-summary">{result.draft.description}</p>

          <div className="orth-chip-grid">
            {result.draft.sources.map((source) => (
              <span key={source} className="orth-chip">
                {source}
              </span>
            ))}
          </div>

          <div className="orth-columns">
            <div>
              <div className="orth-section-label">Hotspots</div>
              <ul className="orth-list">
                {result.draft.hotspots.map((hotspot) => (
                  <li key={hotspot.id}>
                    <strong>{hotspot.name}</strong>: {hotspot.description}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <div className="orth-section-label">Starter Scenarios</div>
              <ul className="orth-list">
                {result.draft.scenarios.map((scenario) => (
                  <li key={scenario.id}>
                    <strong>{scenario.label}</strong>: {scenario.year} · +
                    {scenario.riseMeters.toFixed(2)}m
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="orth-columns">
            <div>
              <div className="orth-section-label">Validation Notes</div>
              <ul className="orth-list">
                {result.draft.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>

            <div>
              <div className="orth-section-label">Orthogonal Workflow</div>
              <ul className="orth-list">
                {result.draft.orthogonalWorkflow.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ul>
            </div>
          </div>

          <div className="orth-section-label">LocationRecord Snippet</div>
          <pre className="orth-code">{result.locationRecordSnippet}</pre>
        </div>
      ) : null}
    </section>
  );
}
