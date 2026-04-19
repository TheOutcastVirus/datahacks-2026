'use client';

import { useRef, useState } from 'react';

type SpeechState = 'idle' | 'loading-model' | 'recording' | 'transcribing' | 'error';

type BrowserSpeechRecognitionResult = {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: {
    readonly transcript: string;
    readonly confidence: number;
  };
};

type BrowserSpeechRecognitionEvent = Event & {
  readonly resultIndex: number;
  readonly results: ArrayLike<BrowserSpeechRecognitionResult>;
};

type BrowserSpeechRecognitionErrorEvent = Event & {
  readonly error: string;
  readonly message?: string;
};

type BrowserSpeechRecognition = EventTarget & {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  onend: ((event: Event) => void) | null;
  onerror: ((event: BrowserSpeechRecognitionErrorEvent) => void) | null;
  onresult: ((event: BrowserSpeechRecognitionEvent) => void) | null;
  processLocally?: boolean;
  phrases?: Array<{ phrase: string; boost: number }>;
  start: () => void;
  stop: () => void;
};

type BrowserSpeechRecognitionConstructor = {
  new (): BrowserSpeechRecognition;
  available?: (options: {
    langs: string[];
    processLocally: boolean;
  }) => Promise<'available' | 'downloadable' | 'downloading' | 'unavailable'>;
  install?: (options: {
    langs: string[];
  }) => Promise<boolean>;
};

function getSpeechRecognitionConstructor() {
  if (typeof window === 'undefined') {
    return null;
  }

  return (
    (window as typeof window & {
      SpeechRecognition?: BrowserSpeechRecognitionConstructor;
      webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
    }).SpeechRecognition ??
    (window as typeof window & {
      webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
    }).webkitSpeechRecognition ??
    null
  );
}

async function ensureLocalLanguagePack(
  SpeechRecognitionCtor: BrowserSpeechRecognitionConstructor,
  lang: string,
) {
  if (!SpeechRecognitionCtor.available) {
    return;
  }

  const availability = await SpeechRecognitionCtor.available({
    langs: [lang],
    processLocally: true,
  });

  if (availability === 'available' || availability === 'downloading') {
    return;
  }

  if (availability === 'downloadable' && SpeechRecognitionCtor.install) {
    const installed = await SpeechRecognitionCtor.install({ langs: [lang] });
    if (installed) {
      return;
    }
  }

  throw new Error('On-device English speech recognition is not available in this browser.');
}

export function useLocalSpeechToText(phraseHints: string[] = []) {
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const resolverRef = useRef<((transcript: string | null) => void) | null>(null);
  const resultRef = useRef<string | null>(null);
  const [status, setStatus] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState('');
  const [isSupported] = useState(() => !!getSpeechRecognitionConstructor());

  const startRecording = async () => {
    if (status === 'recording') {
      return;
    }

    const SpeechRecognitionCtor = getSpeechRecognitionConstructor();
    if (!SpeechRecognitionCtor) {
      setStatus('error');
      setError('Chrome on-device speech recognition is not available here.');
      return;
    }

    setError(null);
    setTranscript('');
    resultRef.current = null;

    try {
      setStatus('loading-model');
      await ensureLocalLanguagePack(SpeechRecognitionCtor, 'en-US');

      const recognition = new SpeechRecognitionCtor();
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = 'en-US';
      recognition.maxAlternatives = 1;

      if (!('processLocally' in recognition)) {
        throw new Error('This browser does not expose local speech recognition controls.');
      }

      recognition.processLocally = true;

      if ('phrases' in recognition) {
        recognition.phrases = phraseHints.slice(0, 24).map((phrase) => ({
          phrase,
          boost: 6,
        }));
      }

      recognition.onresult = (event) => {
        const bestResult = event.results[event.resultIndex];
        const nextTranscript = bestResult?.[0]?.transcript?.trim() ?? '';
        resultRef.current = nextTranscript || null;
        if (nextTranscript) {
          setTranscript(nextTranscript);
        }
      };

      recognition.onerror = (event) => {
        setStatus('error');
        setError(event.message || `Speech recognition failed: ${event.error}`);
        resolverRef.current?.(null);
        resolverRef.current = null;
      };

      recognition.onend = () => {
        setStatus('idle');
        resolverRef.current?.(resultRef.current);
        resolverRef.current = null;
      };

      recognitionRef.current = recognition;
      recognition.start();
      setStatus('recording');
    } catch (error) {
      setStatus('error');
      setError(
        error instanceof Error
          ? error.message
          : 'Unable to start on-device speech recognition.',
      );
    }
  };

  const stopRecording = async () => {
    if (status !== 'recording' || !recognitionRef.current) {
      return null;
    }

    setStatus('transcribing');
    const completion = new Promise<string | null>((resolve) => {
      resolverRef.current = resolve;
    });
    recognitionRef.current.stop();
    recognitionRef.current = null;
    return completion;
  };

  return {
    error,
    isSupported,
    startRecording,
    state: status,
    stopRecording,
    transcript,
  };
}
