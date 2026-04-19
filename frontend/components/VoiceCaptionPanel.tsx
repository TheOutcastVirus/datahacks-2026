'use client';

type VoiceCaptionPanelProps = {
  commandLabel: string;
  response: string;
  transcript: string;
  error: string | null;
};

export default function VoiceCaptionPanel({
  commandLabel,
  response,
  transcript,
  error,
}: VoiceCaptionPanelProps) {
  return (
    <aside className="voice-caption-panel">
      <div className="voice-panel-kicker">Voice Feed</div>
      <div className="voice-panel-label">{commandLabel}</div>
      <p className="voice-panel-response">{response}</p>
      <p className="voice-panel-meta">
        {transcript ? `Transcript: ${transcript}` : 'Waiting for a voice command.'}
      </p>
      {error ? <p className="voice-panel-error">{error}</p> : null}
    </aside>
  );
}
