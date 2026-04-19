'use client';

import { useEffect, useRef, useState } from 'react';

type SpeechState = 'idle' | 'connecting' | 'recording' | 'stopping' | 'error';

type AssemblyBeginMessage = {
  type: 'Begin';
  id: string;
  expires_at: number;
};

type AssemblyTurnMessage = {
  type?: 'Turn';
  turn_order: number;
  turn_is_formatted: boolean;
  end_of_turn: boolean;
  transcript: string;
  utterance?: string;
  end_of_turn_confidence?: number;
};

type AssemblyTerminationMessage = {
  type: 'Termination';
  audio_duration_seconds: number;
  session_duration_seconds: number;
};

const TARGET_SAMPLE_RATE = 16_000;
const CHUNK_SAMPLES = 1_600;

function getFallbackMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }

  return 'Unable to start AssemblyAI speech recognition.';
}

function getSupportedFeatures() {
  if (typeof window === 'undefined') {
    return false;
  }

  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
}

export type BrowserAudioSupport = 'unknown' | 'supported' | 'unsupported';

function isAbortError(error: unknown) {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (error instanceof Error && error.name === 'AbortError')
  );
}

async function fetchStreamingToken(signal?: AbortSignal) {
  const response = await fetch('/api/voice/assembly/token', {
    method: 'GET',
    cache: 'no-store',
    signal,
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(body?.error ?? 'Unable to fetch an AssemblyAI streaming token.');
  }

  const body = (await response.json()) as { token?: string };
  if (!body.token) {
    throw new Error('AssemblyAI did not return a streaming token.');
  }

  return body.token;
}

function createWebSocketUrl(token: string, phraseHints: string[]) {
  const params = new URLSearchParams({
    sample_rate: String(TARGET_SAMPLE_RATE),
    encoding: 'pcm_s16le',
    format_turns: 'true',
    end_of_turn_confidence_threshold: '0.4',
    vad_threshold: '0.4',
    speech_model: 'universal-streaming-english',
    token,
  });

  const hints = phraseHints.slice(0, 24);
  if (hints.length > 0) {
    params.set('keyterms_prompt', JSON.stringify(hints));
  }

  return `wss://streaming.assemblyai.com/v3/ws?${params.toString()}`;
}

function downsampleBuffer(
  buffer: Float32Array,
  inputSampleRate: number,
  outputSampleRate: number,
) {
  if (outputSampleRate === inputSampleRate) {
    return buffer;
  }

  const sampleRateRatio = inputSampleRate / outputSampleRate;
  const newLength = Math.round(buffer.length / sampleRateRatio);
  const result = new Float32Array(newLength);

  let outputOffset = 0;
  let bufferOffset = 0;
  while (outputOffset < result.length) {
    const nextBufferOffset = Math.round((outputOffset + 1) * sampleRateRatio);
    let accum = 0;
    let count = 0;

    for (let i = bufferOffset; i < nextBufferOffset && i < buffer.length; i += 1) {
      accum += buffer[i] ?? 0;
      count += 1;
    }

    result[outputOffset] = count ? accum / count : 0;
    outputOffset += 1;
    bufferOffset = nextBufferOffset;
  }

  return result;
}

function floatTo16BitPCM(input: Float32Array) {
  const output = new Int16Array(input.length);

  for (let i = 0; i < input.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, input[i] ?? 0));
    output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }

  return output;
}

function appendChunk(
  pending: number[],
  nextSamples: Int16Array,
  sendChunk: (chunk: Int16Array) => void,
) {
  for (const sample of nextSamples) {
    pending.push(sample);
  }

  while (pending.length >= CHUNK_SAMPLES) {
    const chunk = pending.splice(0, CHUNK_SAMPLES);
    sendChunk(Int16Array.from(chunk));
  }
}

function parseAssemblyMessage(raw: string) {
  try {
    return JSON.parse(raw) as AssemblyBeginMessage | AssemblyTurnMessage | AssemblyTerminationMessage;
  } catch {
    return null;
  }
}

export function useAssemblyAISpeechToText(phraseHints: string[] = []) {
  const socketRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const pendingSamplesRef = useRef<number[]>([]);
  const queuedChunksRef = useRef<Int16Array[]>([]);
  const finalTranscriptRef = useRef('');
  const transcriptRef = useRef('');
  const stateRef = useRef<SpeechState>('idle');
  const stopResolverRef = useRef<((transcript: string | null) => void) | null>(null);
  const isStoppingRef = useRef(false);
  const isSessionReadyRef = useRef(false);
  const tokenFetchAbortRef = useRef<AbortController | null>(null);
  const [state, setState] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState('');
  const [browserAudioSupport, setBrowserAudioSupport] =
    useState<BrowserAudioSupport>('unknown');

  useEffect(() => {
    setBrowserAudioSupport(getSupportedFeatures() ? 'supported' : 'unsupported');
  }, []);

  const isSupported = browserAudioSupport === 'supported';

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    return () => {
      void (async () => {
        const socket = socketRef.current;
        socketRef.current = null;
        try {
          socket?.send(JSON.stringify({ type: 'Terminate' }));
        } catch {
          // Ignore shutdown errors.
        }
        socket?.close();

        processorRef.current?.disconnect();
        processorRef.current = null;
        sourceNodeRef.current?.disconnect();
        sourceNodeRef.current = null;

        mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
        mediaStreamRef.current = null;

        await audioContextRef.current?.close().catch(() => {});
        audioContextRef.current = null;
      })();
    };
  }, []);

  const cleanup = async () => {
    processorRef.current?.disconnect();
    processorRef.current = null;
    sourceNodeRef.current?.disconnect();
    sourceNodeRef.current = null;

    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;

    await audioContextRef.current?.close().catch(() => {});
    audioContextRef.current = null;

    socketRef.current = null;
    isSessionReadyRef.current = false;
    pendingSamplesRef.current = [];
    queuedChunksRef.current = [];
    isStoppingRef.current = false;
  };

  const flushPendingAudio = () => {
    if (!pendingSamplesRef.current.length) {
      return;
    }

    const remaining = Int16Array.from(pendingSamplesRef.current);
    pendingSamplesRef.current = [];
    if (remaining.length >= CHUNK_SAMPLES || remaining.length > 0) {
      if (isSessionReadyRef.current) {
        socketRef.current?.send(remaining.buffer);
      } else {
        queuedChunksRef.current.push(remaining);
      }
    }
  };

  const close = async () => {
    const socket = socketRef.current;
    socketRef.current = null;
    try {
      socket?.send(JSON.stringify({ type: 'Terminate' }));
    } catch {
      // Ignore shutdown errors.
    }
    socket?.close();
    await cleanup();
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

    const socket = socketRef.current;

    // Released before the WebSocket exists (still fetching token) — cancel quietly, no "stopping" flash.
    if (!socket && stateRef.current === 'connecting') {
      tokenFetchAbortRef.current?.abort();
      tokenFetchAbortRef.current = null;
      stopResolverRef.current?.(null);
      stopResolverRef.current = null;
      await cleanup();
      setState('idle');
      return null;
    }

    // Socket created but session not live yet — close without Terminate UI flash.
    if (
      socket &&
      stateRef.current === 'connecting' &&
      socket.readyState !== WebSocket.OPEN
    ) {
      tokenFetchAbortRef.current = null;
      isStoppingRef.current = true;
      socket.close();
      return new Promise<string | null>((resolve) => {
        const previous = stopResolverRef.current;
        stopResolverRef.current = (value) => {
          previous?.(value);
          resolve(value ?? null);
        };
      });
    }

    isStoppingRef.current = true;
    setState('stopping');

    const completion = new Promise<string | null>((resolve) => {
      stopResolverRef.current = resolve;
    });

    flushPendingAudio();

    try {
      socket?.send(JSON.stringify({ type: 'Terminate' }));
    } catch (sendError) {
      setState('error');
      setError(getFallbackMessage(sendError));
      stopResolverRef.current?.(finalTranscriptRef.current || transcriptRef.current || null);
      stopResolverRef.current = null;
      await cleanup();
      return finalTranscriptRef.current || transcriptRef.current || null;
    }

    return completion;
  };

  const start = async () => {
    if (state === 'recording' || state === 'connecting' || state === 'stopping') {
      return;
    }

    if (!getSupportedFeatures()) {
      setState('error');
      setError('Microphone recording is not available in this browser.');
      return;
    }

    setError(null);
    setTranscript('');
    transcriptRef.current = '';
    finalTranscriptRef.current = '';
    pendingSamplesRef.current = [];
    queuedChunksRef.current = [];
    isStoppingRef.current = false;
    isSessionReadyRef.current = false;

    tokenFetchAbortRef.current?.abort();
    const tokenController = new AbortController();
    tokenFetchAbortRef.current = tokenController;

    try {
      setState('connecting');
      const token = await fetchStreamingToken(tokenController.signal);
      tokenFetchAbortRef.current = null;
      if (isStoppingRef.current) {
        await cleanup();
        setState('idle');
        return;
      }

      const socket = new WebSocket(createWebSocketUrl(token, phraseHints));
      socket.binaryType = 'arraybuffer';
      socketRef.current = socket;

      socket.onopen = async () => {
        try {
          if (isStoppingRef.current) {
            socket.close();
            return;
          }

          const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              channelCount: 1,
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
          });
          mediaStreamRef.current = stream;

          const audioContext = new AudioContext();
          audioContextRef.current = audioContext;
          await audioContext.resume();

          const source = audioContext.createMediaStreamSource(stream);
          sourceNodeRef.current = source;

          const processor = audioContext.createScriptProcessor(4096, 1, 1);
          processorRef.current = processor;

          processor.onaudioprocess = (event) => {
            if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
              return;
            }

            if (isStoppingRef.current) {
              return;
            }

            const inputBuffer = event.inputBuffer.getChannelData(0);
            const downsampled = downsampleBuffer(
              inputBuffer,
              audioContext.sampleRate,
              TARGET_SAMPLE_RATE,
            );
            const pcm16 = floatTo16BitPCM(downsampled);
            appendChunk(pendingSamplesRef.current, pcm16, (chunk) => {
              if (isSessionReadyRef.current) {
                socketRef.current?.send(chunk.buffer);
              } else {
                queuedChunksRef.current.push(chunk);
              }
            });
          };

          source.connect(processor);
          processor.connect(audioContext.destination);

          setState('recording');
        } catch (startError) {
          setState('error');
          setError(getFallbackMessage(startError));
          await cleanup();
          socket.close();
        }
      };

      socket.onerror = () => {
        setState('error');
        setError('AssemblyAI streaming websocket failed to connect.');
      };

      socket.onclose = async () => {
        const transcriptValue = finalTranscriptRef.current || transcriptRef.current || null;
        if (isStoppingRef.current) {
          stopResolverRef.current?.(transcriptValue);
        } else if (stateRef.current !== 'error') {
          stopResolverRef.current?.(transcriptValue);
        }
        stopResolverRef.current = null;
        await cleanup();
        if (stateRef.current !== 'error' && !isStoppingRef.current) {
          setState('idle');
        }
      };

      socket.onmessage = (event) => {
        const message = typeof event.data === 'string' ? parseAssemblyMessage(event.data) : null;
        if (!message) {
          return;
        }

        if (message.type === 'Begin') {
          isSessionReadyRef.current = true;
          for (const chunk of queuedChunksRef.current) {
            socket.send(chunk.buffer);
          }
          queuedChunksRef.current = [];
          return;
        }

        if ((message as AssemblyTurnMessage).transcript !== undefined) {
          const turn = message as AssemblyTurnMessage;
          const nextTranscript = turn.transcript.trim();
          transcriptRef.current = nextTranscript;
          setTranscript(nextTranscript);
          if (turn.end_of_turn && nextTranscript) {
            finalTranscriptRef.current = nextTranscript;
          }
          return;
        }

        if (message.type === 'Termination') {
          finalTranscriptRef.current = finalTranscriptRef.current || transcriptRef.current;
          stopResolverRef.current?.(finalTranscriptRef.current || transcriptRef.current || null);
          stopResolverRef.current = null;
          setState('idle');
        }
      };
    } catch (startError) {
      tokenFetchAbortRef.current = null;
      if (isAbortError(startError)) {
        await cleanup();
        setState('idle');
        return;
      }
      setState('error');
      setError(getFallbackMessage(startError));
      await cleanup();
    }
  };

  return {
    audioSupport: browserAudioSupport,
    error,
    isSupported,
    startRecording: start,
    state,
    stopRecording: stop,
    transcript,
    close,
  } as const;
}

export type { SpeechState };
