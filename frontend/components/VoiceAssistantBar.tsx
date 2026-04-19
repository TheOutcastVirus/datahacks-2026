'use client';

import type { MouseEventHandler } from 'react';

type VoiceAssistantBarProps = {
  /** Mic is open: connecting or actively streaming to the speech service */
  isLive: boolean;
  /** Audio is being captured (show stop-style control) */
  isCapturing: boolean;
  liveTranscript?: string;
  isSupported: boolean;
  /** Transcript pipeline is finishing after mute */
  isProcessing: boolean;
  isWorking: boolean;
  statusLabel: string;
  onMicClick: MouseEventHandler<HTMLButtonElement>;
};

export default function VoiceAssistantBar({
  isLive,
  isCapturing,
  isSupported,
  isProcessing,
  isWorking,
  statusLabel,
  liveTranscript,
  onMicClick,
}: VoiceAssistantBarProps) {
  const micLabel = isProcessing
    ? 'Processing…'
    : isLive
      ? 'Click to mute'
      : 'Click to unmute';

  const buttonDisabled = !isSupported || isProcessing;

  return (
    <div className="voice-assistant-bar">
      {isCapturing && liveTranscript ? (
        <div className="voice-live-transcript">{liveTranscript}</div>
      ) : null}
      <div className="voice-assistant-row">
        <div className="voice-assistant-status">
          <span className={`voice-dot ${isLive ? 'voice-dot-live' : ''}`} />
          <div className="voice-assistant-copy">
            <div className="voice-status-kicker">Voice Assistant</div>
            <div className="voice-status-label">{statusLabel}</div>
          </div>
        </div>
        <button
          type="button"
          className={`voice-button voice-button-mic ${isLive ? 'voice-button-live voice-button-mic-live' : ''}`}
          aria-busy={isWorking}
          aria-label={micLabel}
          title={micLabel}
          disabled={buttonDisabled}
          onClick={onMicClick}
        >
          {isCapturing ? (
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
