'use client';

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
  isRecording: boolean;
  isSupported: boolean;
  isWorking: boolean;
  speakerEnabled: boolean;
  statusLabel: string;
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
  speakerEnabled,
  statusLabel,
  transcript,
  onMicClick,
  onToggleSpeaker,
  onHide,
}: VoiceAssistantBarProps) {
  return (
    <div className="voice-mic-stack">
      <div className="voice-mic-toolbar">
        <button
          type="button"
          className={`voice-mic-btn ${isRecording ? 'voice-mic-btn-live' : ''}`}
          aria-pressed={isRecording}
          aria-busy={isWorking}
          disabled={!isSupported}
          onClick={onMicClick}
          title={statusLabel}
        >
          <MicGlyph active={isRecording} className="voice-mic-btn-icon" />
          <span className="voice-mic-btn-label">
            {isWorking
              ? '…'
              : isRecording
                ? 'Stop'
                : 'Mic'}
          </span>
        </button>

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

      <div className="voice-agent-transcript" aria-live="polite">
        <div className="voice-agent-transcript-kicker">Assistant</div>
        <div className="voice-agent-transcript-body">{agentResponse}</div>
      </div>

      <p className="voice-mic-status" role="status">
        {statusLabel}
      </p>

      {(transcript || isRecording) && (
        <div className="voice-user-transcript">
          <div className="voice-user-transcript-kicker">You</div>
          <div className="voice-user-transcript-body">
            {transcript || (isRecording ? '…' : '')}
          </div>
        </div>
      )}
    </div>
  );
}
