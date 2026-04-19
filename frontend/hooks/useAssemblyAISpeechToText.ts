'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';

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

type LegacyWindowAudio = Window & {
  webkitAudioContext?: typeof AudioContext;
};

type CaptureNode = AudioWorkletNode | ScriptProcessorNode;

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

<<<<<<< Updated upstream
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof AudioWorkletNode !== 'undefined'
  );
=======
  const AC =
    window.AudioContext ||
    (window as LegacyWindowAudio).webkitAudioContext;
  return !!(navigator.mediaDevices?.getUserMedia && window.WebSocket && AC);
}

function subscribeToMicrophoneSupport(onStoreChange: () => void) {
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

/** Inline worklet: copies mic samples to main thread (replaces deprecated ScriptProcessorNode). */
const PCM_CAPTURE_WORKLET = `
class PCMCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const channel0 = input[0];
    const copy = new Float32Array(channel0.length);
    copy.set(channel0);
    this.port.postMessage(copy.buffer, [copy.buffer]);
    return true;
  }
}
registerProcessor('pcm-capture', PCMCaptureProcessor);
`;

async function addPCMWorkletModule(audioContext: AudioContext) {
  const blob = new Blob([PCM_CAPTURE_WORKLET], { type: 'application/javascript' });
  const url = URL.createObjectURL(blob);
  try {
    await audioContext.audioWorklet.addModule(url);
  } finally {
    URL.revokeObjectURL(url);
  }
>>>>>>> Stashed changes
}

const ASSEMBLY_CAPTURE_WORKLET_URL = '/audio-worklets/assemblyai-capture.worklet.js';

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

async function createCaptureNode(
  audioContext: AudioContext,
  onChunk: (buffer: Float32Array) => void,
) {
  if ('audioWorklet' in audioContext) {
    await addPCMWorkletModule(audioContext);

    const workletNode = new AudioWorkletNode(audioContext, 'pcm-capture', {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCount: 1,
      channelCountMode: 'explicit',
    });

    workletNode.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
      onChunk(new Float32Array(event.data));
    };

    return workletNode;
  }

  const legacyNode = audioContext.createScriptProcessor(4096, 1, 1);
  legacyNode.onaudioprocess = (event) => {
    const channel = event.inputBuffer.getChannelData(0);
    const copy = new Float32Array(channel.length);
    copy.set(channel);
    onChunk(copy);
  };

  return legacyNode;
}

export function useAssemblyAISpeechToText(phraseHints: string[] = [], onEndOfTurn?: (transcript: string) => void) {
  const onEndOfTurnRef = useRef(onEndOfTurn);
  useEffect(() => { onEndOfTurnRef.current = onEndOfTurn; }, [onEndOfTurn]);
  const socketRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
<<<<<<< Updated upstream
  const workletRef = useRef<AudioWorkletNode | null>(null);
=======
  const captureNodeRef = useRef<CaptureNode | null>(null);
  const muteGainRef = useRef<GainNode | null>(null);
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
  const [browserAudioSupport, setBrowserAudioSupport] =
    useState<BrowserAudioSupport>('unknown');

  useEffect(() => {
    setBrowserAudioSupport(getSupportedFeatures() ? 'supported' : 'unsupported');
  }, []);

  const isSupported = browserAudioSupport === 'supported';
=======
  const isSupported = useSyncExternalStore(
    subscribeToMicrophoneSupport,
    getSupportedFeatures,
    () => false,
  );
>>>>>>> Stashed changes

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

<<<<<<< Updated upstream
        workletRef.current?.disconnect();
        workletRef.current = null;
=======
        captureNodeRef.current?.disconnect();
        captureNodeRef.current = null;
        muteGainRef.current?.disconnect();
        muteGainRef.current = null;
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
    workletRef.current?.disconnect();
    workletRef.current = null;
=======
    captureNodeRef.current?.disconnect();
    captureNodeRef.current = null;
    muteGainRef.current?.disconnect();
    muteGainRef.current = null;
>>>>>>> Stashed changes
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

          const AC =
            window.AudioContext ||
            (window as LegacyWindowAudio).webkitAudioContext;
          if (!AC) {
            throw new Error('Microphone recording is not available in this browser.');
          }

          const audioContext = new AC();
          audioContextRef.current = audioContext;
          await audioContext.resume();

          const source = audioContext.createMediaStreamSource(stream);
          sourceNodeRef.current = source;

<<<<<<< Updated upstream
          await audioContext.audioWorklet.addModule(ASSEMBLY_CAPTURE_WORKLET_URL);

          const captureNode = new AudioWorkletNode(audioContext, 'assemblyai-capture', {
            numberOfInputs: 1,
            numberOfOutputs: 1,
            channelCount: 1,
            channelCountMode: 'explicit',
            channelInterpretation: 'speakers',
          });
          workletRef.current = captureNode;

          captureNode.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
=======
          const captureNode = await createCaptureNode(audioContext, (inputBuffer) => {
>>>>>>> Stashed changes
            if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
              return;
            }

            if (isStoppingRef.current) {
              return;
            }

<<<<<<< Updated upstream
            const raw = event.data;
            if (!(raw instanceof ArrayBuffer)) {
              return;
            }

            const inputBuffer = new Float32Array(raw);
=======
>>>>>>> Stashed changes
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
          });
          captureNodeRef.current = captureNode;

<<<<<<< Updated upstream
          source.connect(captureNode);
          // Route through a silent sink instead of `destination` so the mic
          // is captured for AssemblyAI without echoing back through the speakers.
          const silentSink = audioContext.createGain();
          silentSink.gain.value = 0;
          captureNode.connect(silentSink);
          silentSink.connect(audioContext.destination);
=======
          const muteGain = audioContext.createGain();
          muteGain.gain.value = 0;
          muteGainRef.current = muteGain;

          source.connect(captureNode);
          captureNode.connect(muteGain);
          muteGain.connect(audioContext.destination);
>>>>>>> Stashed changes

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

        if (message.type === 'Turn') {
          const turn = message as AssemblyTurnMessage;
          const nextTranscript = (turn.utterance || turn.transcript || '').trim();
          transcriptRef.current = nextTranscript;
          setTranscript(nextTranscript);
          if (turn.end_of_turn && nextTranscript) {
            finalTranscriptRef.current = nextTranscript;
            onEndOfTurnRef.current?.(nextTranscript);
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
