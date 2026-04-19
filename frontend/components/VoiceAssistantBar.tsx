'use client';

import type { PointerEventHandler } from 'react';

type VoiceAssistantBarProps = {
  isRecording: boolean;
  liveTranscript?: string;
  isSupported: boolean;
  isWorking: boolean;
  statusLabel: string;
  onMicPointerDown: PointerEventHandler<HTMLButtonElement>;
  onMicPointerUp: PointerEventHandler<HTMLButtonElement>;
  onMicPointerCancel: PointerEventHandler<HTMLButtonElement>;
  onMicLostPointerCapture: PointerEventHandler<HTMLButtonElement>;
};

export default function VoiceAssistantBar({
  isRecording,
  isSupported,
  isWorking,
  statusLabel,
  liveTranscript,
  onMicPointerDown,
  onMicPointerUp,
  onMicPointerCancel,
  onMicLostPointerCapture,
}: VoiceAssistantBarProps) {
  const micLabel = isRecording ? 'Release to send' : 'Hold to talk';

  return (
    <div className="voice-assistant-bar">
      {isRecording && liveTranscript ? (
        <div className="voice-live-transcript">{liveTranscript}</div>
      ) : null}
      <div className="voice-assistant-row">
        <div className="voice-assistant-status">
          <span className={`voice-dot ${isRecording ? 'voice-dot-live' : ''}`} />
          <div className="voice-assistant-copy">
            <div className="voice-status-kicker">Voice Assistant</div>
            <div className="voice-status-label">{statusLabel}</div>
          </div>
        </div>
        <button
          type="button"
          className={`voice-button voice-button-mic ${isRecording ? 'voice-button-live voice-button-mic-live' : ''}`}
          aria-busy={isWorking}
          aria-label={micLabel}
          title={micLabel}
          disabled={!isSupported}
          onPointerDown={onMicPointerDown}
          onPointerUp={onMicPointerUp}
          onPointerCancel={onMicPointerCancel}
          onLostPointerCapture={onMicLostPointerCapture}
        >
          {isRecording ? (
            <svg
              className="voice-button-mic-icon"
              viewBox="0 0 24 24"
              width={20}
              height={20}
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden={true}
            >
              <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />
            </svg>
          ) : (
            <svg
              className="voice-button-mic-icon"
              viewBox="0 0 24 24"
              width={20}
              height={20}
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden={true}
            >
              <path
                d="M12 14a3 3 0 0 0 3-3V7a3 3 0 1 0-6 0v4a3 3 0 0 0 3 3Z"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinejoin="round"
              />
              <path
                d="M19 11a7 7 0 1 1-14 0M12 18v3"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
              />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}
