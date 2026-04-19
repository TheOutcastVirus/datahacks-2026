'use client';

import { useRef, useState } from 'react';

type VoicePlaybackEvent = {
  level?: 'info' | 'error';
  message: string;
};

export function useVoicePlayback(
  onEvent?: (event: VoicePlaybackEvent) => void,
) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    audioRef.current?.pause();
    audioRef.current = null;
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    setIsPlaying(false);
  };

  const speak = async (text: string) => {
    stop();
    setError(null);

    const trimmed = text.trim();
    if (!trimmed) return;

    const controller = new AbortController();
    abortRef.current = controller;
    onEvent?.({ message: `Sending ${trimmed.length} chars to ElevenLabs.` });

    try {
      const response = await fetch('/api/voice/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: trimmed }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const errJson = (await response.json().catch(() => null)) as {
          error?: string;
        } | null;
        throw new Error(
          errJson?.error ??
            (response.status === 503
              ? 'Voice playback is not configured (ElevenLabs).'
              : 'Voice playback is unavailable right now.'),
        );
      }

      const blob = await response.blob();
      if (!blob.size) {
        onEvent?.({
          level: 'error',
          message: 'ElevenLabs returned an empty audio response.',
        });
        return;
      }

      const objectUrl = URL.createObjectURL(blob);
      objectUrlRef.current = objectUrl;
      const audio = new Audio(objectUrl);
      audioRef.current = audio;
      setIsPlaying(true);
      onEvent?.({
        message: `ElevenLabs audio ready (${Math.round(blob.size / 1024)} KB).`,
      });
      audio.addEventListener(
        'ended',
        () => {
          setIsPlaying(false);
          onEvent?.({ message: 'ElevenLabs playback finished.' });
        },
        { once: true },
      );
      await audio.play();
      onEvent?.({ message: 'Playing ElevenLabs response.' });
    } catch (error) {
      if (controller.signal.aborted) {
        onEvent?.({ message: 'ElevenLabs playback request was cancelled.' });
        return;
      }
      setIsPlaying(false);
      const message =
        error instanceof Error ? error.message : 'Unable to play the voice response.';
      setError(message);
      onEvent?.({ level: 'error', message });
    }
  };

  return {
    error,
    isPlaying,
    speak,
    stop,
  };
}
