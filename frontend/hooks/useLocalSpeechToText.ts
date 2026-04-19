'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';

export type SpeechState = 'idle' | 'connecting' | 'recording' | 'stopping' | 'error';

type BrowserSpeechRecognitionEvent = Event & {
  results: SpeechRecognitionResultList;
  resultIndex: number;
};

type BrowserSpeechRecognitionErrorEvent = Event & {
  error: string;
  message?: string;
};

type BrowserSpeechRecognition = EventTarget & {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  onstart: ((event: Event) => void) | null;
  onresult: ((event: BrowserSpeechRecognitionEvent) => void) | null;
  onerror: ((event: BrowserSpeechRecognitionErrorEvent) => void) | null;
  onend: ((event: Event) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

type SpeechWindow = Window & {
  SpeechRecognition?: BrowserSpeechRecognitionConstructor;
  webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
};

function getSpeechRecognitionConstructor() {
  if (typeof window === 'undefined') {
    return null;
  }

  const speechWindow = window as SpeechWindow;
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null;
}

function isSpeechRecognitionSupported() {
  return !!getSpeechRecognitionConstructor();
}

function subscribeToSpeechRecognitionSupport(onStoreChange: () => void) {
  if (typeof window === 'undefined') {
    return () => {};
  }

  window.addEventListener('focus', onStoreChange);
  window.addEventListener('visibilitychange', onStoreChange);

  return () => {
    window.removeEventListener('focus', onStoreChange);
    window.removeEventListener('visibilitychange', onStoreChange);
  };
}

function getFallbackMessage(error: unknown) {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  return 'Unable to start browser speech recognition.';
}

function getRecognitionErrorMessage(error: string) {
  switch (error) {
    case 'not-allowed':
    case 'service-not-allowed':
      return 'Microphone permission was denied.';
    case 'no-speech':
      return 'No speech detected. Try again.';
    case 'audio-capture':
      return 'No microphone was found for speech recognition.';
    case 'network':
      return 'Speech recognition network error.';
    case 'aborted':
      return '';
    default:
      return 'Browser speech recognition failed.';
  }
}

export function useLocalSpeechToText(
  phraseHints: string[] = [],
  onEndOfTurn?: (transcript: string) => void,
) {
  void phraseHints;
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const finalTranscriptRef = useRef('');
  const transcriptRef = useRef('');
  const stateRef = useRef<SpeechState>('idle');
  const stopResolverRef = useRef<((transcript: string | null) => void) | null>(null);
  const isStoppingRef = useRef(false);
  const onEndOfTurnRef = useRef(onEndOfTurn);

  const [state, setState] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState('');

  const isSupported = useSyncExternalStore(
    subscribeToSpeechRecognitionSupport,
    isSpeechRecognitionSupported,
    () => false,
  );

  useEffect(() => {
    onEndOfTurnRef.current = onEndOfTurn;
  }, [onEndOfTurn]);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    return () => {
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    };
  }, []);

  const close = async () => {
    recognitionRef.current?.abort();
    recognitionRef.current = null;
    isStoppingRef.current = false;
    stopResolverRef.current = null;
    setState('idle');
  };

  const stop = async () => {
    if (stateRef.current !== 'recording' && stateRef.current !== 'connecting') {
      return null;
    }

    if (isStoppingRef.current) {
      return new Promise<string | null>((resolve) => {
        const previous = stopResolverRef.current;
        stopResolverRef.current = (value) => {
          previous?.(value);
          resolve(value);
        };
      });
    }

    isStoppingRef.current = true;
    setState('stopping');

    const completion = new Promise<string | null>((resolve) => {
      stopResolverRef.current = resolve;
    });

    recognitionRef.current?.stop();

    return completion;
  };

  const start = async () => {
    if (stateRef.current === 'recording' || stateRef.current === 'connecting' || stateRef.current === 'stopping') {
      return;
    }

    const Recognition = getSpeechRecognitionConstructor();
    if (!Recognition) {
      setState('error');
      setError('Browser speech recognition is not available in this browser.');
      return;
    }

    recognitionRef.current?.abort();
    recognitionRef.current = null;
    finalTranscriptRef.current = '';
    transcriptRef.current = '';
    isStoppingRef.current = false;
    stopResolverRef.current = null;
    setTranscript('');
    setError(null);
    setState('connecting');

    try {
      const recognition = new Recognition();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = 'en-US';
      recognition.maxAlternatives = 1;

      recognition.onstart = () => {
        setState('recording');
      };

      recognition.onresult = (event) => {
        let interimTranscript = '';
        let nextFinalTranscript = finalTranscriptRef.current;

        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const result = event.results[i];
          const alt = result?.[0];
          const text = alt?.transcript?.trim() ?? '';
          if (!text) {
            continue;
          }

          if (result.isFinal) {
            nextFinalTranscript = `${nextFinalTranscript} ${text}`.trim();
          } else {
            interimTranscript = `${interimTranscript} ${text}`.trim();
          }
        }

        finalTranscriptRef.current = nextFinalTranscript;
        const combinedTranscript = `${nextFinalTranscript} ${interimTranscript}`.trim();
        transcriptRef.current = combinedTranscript;
        setTranscript(combinedTranscript);
      };

      recognition.onerror = (event) => {
        const message = getRecognitionErrorMessage(event.error);
        if (!message) {
          return;
        }

        setState('error');
        setError(message);
      };

      recognition.onend = () => {
        const resolvedTranscript = finalTranscriptRef.current || transcriptRef.current || null;

        if (resolvedTranscript) {
          onEndOfTurnRef.current?.(resolvedTranscript);
        }

        if (isStoppingRef.current) {
          stopResolverRef.current?.(resolvedTranscript);
          stopResolverRef.current = null;
          isStoppingRef.current = false;
          recognitionRef.current = null;
          setState('idle');
          return;
        }

        if (stateRef.current !== 'error') {
          setState('idle');
        }

        recognitionRef.current = null;
      };

      recognitionRef.current = recognition;
      recognition.start();
    } catch (startError) {
      recognitionRef.current = null;
      setState('error');
      setError(getFallbackMessage(startError));
    }
  };

  return {
    close,
    error,
    isSupported,
    startRecording: start,
    state,
    stopRecording: stop,
    transcript,
  } as const;
}
