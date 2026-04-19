'use client';

import { useRef, useState } from 'react';

export function useVoicePlayback() {
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

    try {
      const response = await fetch('/api/voice/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: trimmed }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error('Voice playback is unavailable right now.');
      }

      const blob = await response.blob();
      if (!blob.size) return;

      const objectUrl = URL.createObjectURL(blob);
      objectUrlRef.current = objectUrl;
      const audio = new Audio(objectUrl);
      audioRef.current = audio;
      setIsPlaying(true);
      audio.addEventListener(
        'ended',
        () => {
          setIsPlaying(false);
        },
        { once: true },
      );
      await audio.play();
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      setIsPlaying(false);
      setError(
        error instanceof Error ? error.message : 'Unable to play the voice response.',
      );
    }
  };

  return {
    error,
    isPlaying,
    speak,
    stop,
  };
}
