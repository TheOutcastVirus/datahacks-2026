'use client';

type VoiceAssistantBarProps = {
  isRecording: boolean;
  isSupported: boolean;
  isSpeaking: boolean;
  isWorking: boolean;
  speakerEnabled: boolean;
  statusLabel: string;
  transcript: string;
  onMicClick: () => void;
  onToggleSpeaker: () => void;
};

export default function VoiceAssistantBar({
  isRecording,
  isSupported,
  isSpeaking,
  isWorking,
  speakerEnabled,
  statusLabel,
  transcript,
  onMicClick,
  onToggleSpeaker,
}: VoiceAssistantBarProps) {
  return (
    <div className="voice-assistant-bar">
      <div className="voice-assistant-status">
        <span className={`voice-dot ${isRecording ? 'voice-dot-live' : ''}`} />
        <div>
          <div className="voice-status-kicker">Voice Assistant</div>
          <div className="voice-status-label">{statusLabel}</div>
        </div>
      </div>

      <div className="voice-assistant-actions">
        <button
          type="button"
          className={`voice-button ${isRecording ? 'voice-button-live' : ''}`}
          aria-busy={isWorking}
          disabled={!isSupported}
          onClick={onMicClick}
        >
          {isRecording ? 'Stop Mic' : 'Start Mic'}
        </button>
        <button
          type="button"
          className={`voice-toggle ${speakerEnabled ? 'voice-toggle-on' : ''}`}
          onClick={onToggleSpeaker}
        >
          {speakerEnabled ? (isSpeaking ? 'Voice On / Speaking' : 'Voice On') : 'Voice Off'}
        </button>
      </div>

      <div className="voice-transcript">
        {transcript
          ? `Heard: “${transcript}”`
          : 'Tap the mic and say “show 2050”, “zoom out”, or “go to the waterfront”.'}
      </div>
    </div>
  );
}
