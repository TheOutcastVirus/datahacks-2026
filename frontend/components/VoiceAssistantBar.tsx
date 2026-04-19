'use client';

import type { Risk } from '@/app/api/voice/chat/route';

function MicGlyph({ className, active }: { className?: string; active?: boolean }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path
        d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"
        fill={active ? 'currentColor' : undefined}
        fillOpacity={active ? 0.2 : undefined}
      />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );
}

function LiveLevels({ active }: { active: boolean }) {
  return (
    <div
      className={`voice-mic-levels ${active ? 'voice-mic-levels--active' : ''}`}
      aria-hidden
    >
      {[0, 1, 2, 3, 4].map((i) => (
        <span key={i} className="voice-mic-level" style={{ animationDelay: `${i * 0.08}s` }} />
      ))}
    </div>
  );
}

function SpeakerGlyph({ on, className }: { on: boolean; className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {on ? (
        <>
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
          <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
          <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
        </>
      ) : (
        <>
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
          <line x1="23" y1="9" x2="17" y2="15" />
          <line x1="17" y1="9" x2="23" y2="15" />
        </>
      )}
    </svg>
  );
}

type VoiceAssistantBarProps = {
  agentResponse: string;
  risks?: Risk[];
  isRecording: boolean;
  isSupported: boolean;
  isWorking: boolean;
  speakerEnabled: boolean;
  /** Short line for mic state (listening, connecting, …). */
  statusLabel: string;
  /** When set, status / setup issues are styled as a warning in the transcription area. */
  statusIsError?: boolean;
  transcript: string;
  onMicClick: () => void;
  onToggleSpeaker: () => void;
  onHide: () => void;
};

export default function VoiceAssistantBar({
  agentResponse,
  isRecording,
  isSupported,
  isWorking,
  risks = [],
  speakerEnabled,
  statusLabel,
  statusIsError = false,
  transcript,
  onMicClick,
  onToggleSpeaker,
  onHide,
}: VoiceAssistantBarProps) {
  const trimmed = transcript.trim();

  const transcriptionBody = (() => {
    if (statusIsError && statusLabel) return statusLabel;
    if (trimmed) return trimmed;
    if (isWorking) return statusLabel || '…';
    if (isRecording) return 'Listening…';
    if (!isSupported) return statusLabel;
    return 'Tap the mic to speak — your words appear here.';
  })();

  const transcriptionIsPlaceholder =
    !trimmed && !statusIsError && !isRecording && !isWorking && isSupported;

  return (
    <div className="voice-mic-stack">
      <div className="voice-mic-hero-row">
        <div className="voice-mic-hero-wrap">
          <button
            type="button"
            className={`voice-mic-hero-btn ${isRecording ? 'voice-mic-hero-btn--live' : ''} ${isWorking ? 'voice-mic-hero-btn--busy' : ''}`}
            aria-pressed={isRecording}
            aria-busy={isWorking}
            disabled={!isSupported}
            onClick={onMicClick}
            title={statusLabel}
            aria-label={
              isWorking
                ? 'Connecting microphone'
                : isRecording
                  ? 'Stop recording'
                  : 'Start microphone'
            }
          >
            <span className="voice-mic-hero-btn-inner">
              <MicGlyph active={isRecording || isWorking} className="voice-mic-hero-icon" />
            </span>
          </button>
          <LiveLevels active={isRecording && !isWorking} />
        </div>

        <div className="voice-mic-secondary">
          <button
            type="button"
            className={`voice-icon-btn ${speakerEnabled ? 'voice-icon-btn-on' : ''}`}
            onClick={onToggleSpeaker}
            aria-label={speakerEnabled ? 'Mute voice replies' : 'Enable voice replies'}
            title={speakerEnabled ? 'Voice replies on' : 'Voice replies off'}
          >
            <SpeakerGlyph on={speakerEnabled} className="voice-icon-btn-glyph" />
          </button>
          <button
            type="button"
            className="voice-icon-btn voice-icon-btn-close"
            onClick={onHide}
            aria-label="Hide voice panel"
          >
            ×
          </button>
        </div>
      </div>

      <div className="voice-agent-transcript" aria-live="polite">
        <div className="voice-agent-transcript-kicker">Assistant</div>
        <div className="voice-agent-transcript-body">{agentResponse}</div>
      </div>

      {risks.length > 0 && (
        <div className="voice-risks-panel">
          <div className="voice-risks-kicker">Risks · {risks[0] ? risks[0].label : ''}</div>
          <ul className="voice-risks-list">
            {risks.map((risk, i) => (
              <li key={i} className={`voice-risk-item voice-risk-item--${risk.severity}`}>
                <span className="voice-risk-label">{risk.label}</span>
                <span className="voice-risk-desc">{risk.description}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="voice-transcription-panel">
        <div className="voice-transcription-kicker">Transcription</div>
        <div
          className={`voice-transcription-body ${statusIsError ? 'voice-transcription-body--error' : ''} ${transcriptionIsPlaceholder ? 'voice-transcription-body--placeholder' : ''}`}
          {...(trimmed ? { 'aria-live': 'polite' as const } : {})}
          role="status"
        >
          {transcriptionBody}
        </div>
      </div>
    </div>
  );
}
