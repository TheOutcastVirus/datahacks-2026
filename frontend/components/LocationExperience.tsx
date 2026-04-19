'use client';

import { useRef, useState } from 'react';
import type { MouseEventHandler } from 'react';

import type { LocationRecord, ScenarioRecord, SceneHotspot } from '@/lib/locations';
import {
  parseVoiceIntent,
} from '@/lib/scene-command-catalog';
import {
  buildCompareResponse,
  buildCurrentViewResponse,
  buildFloodRiskResponse,
  buildHelpResponse,
  buildNavigationResponse,
  buildScenarioResponse,
  buildSourcesResponse,
  buildUnknownResponse,
} from '@/lib/voice-responses';
import type { ViewerCommandApi, ViewerState } from '@/lib/viewer-types';

import VoiceAssistantBar from '@/components/VoiceAssistantBar';
import VoiceCaptionPanel from '@/components/VoiceCaptionPanel';
import SplatViewer from '@/components/SplatViewer';
import LocationResearchPanel from '@/components/LocationResearchPanel';
import { useAssemblyAISpeechToText } from '@/hooks/useAssemblyAISpeechToText';
import { useVoicePlayback } from '@/hooks/useVoicePlayback';

const MAX_VISUALIZED_RISE_METERS = 2.0;

function describeIntent(intent: string) {
  return intent
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export default function LocationExperience({ location }: { location: LocationRecord }) {
  const fallbackHotspot: SceneHotspot = {
    id: 'overview',
    name: location.name,
    aliases: [location.name.toLowerCase(), 'overview', 'scene'],
    description: location.description,
    cameraPose: {
      position: [-3.5, 2, 5.5],
      target: [0, 0.4, 0],
    },
    explainText: `Showing ${location.name}. ${location.description}`,
  };
  const fallbackScenario: ScenarioRecord = {
    id: 'baseline',
    label: location.scene.label,
    year: location.scene.year,
    riseMeters: location.scene.rise,
    narration: `${location.name} is shown in its ${location.scene.label.toLowerCase()} state.`,
    color: location.scene.color,
  };
  const hotspots = location.hotspots?.length ? location.hotspots : [fallbackHotspot];
  const scenarios = location.scenarios?.length ? location.scenarios : [fallbackScenario];
  const normalizedLocation = {
    ...location,
    hotspots,
    scenarios,
    defaultHotspotId: location.defaultHotspotId ?? hotspots[0].id,
  };
  const viewerRef = useRef<ViewerCommandApi | null>(null);
  const [viewerState, setViewerState] = useState<ViewerState>('loading');
  const [commandLabel, setCommandLabel] = useState('Ready');
  const [response, setResponse] = useState(
    'Click the voice button to unmute, say your command or question, then click again to mute. We will process it and respond here.',
  );
  const [aiError, setAiError] = useState<string | null>(null);
  const [activeHotspotId, setActiveHotspotId] = useState(normalizedLocation.defaultHotspotId);
  const [activeScenarioId, setActiveScenarioId] = useState(normalizedLocation.scenarios[0].id);
  const [compareScenarioIds, setCompareScenarioIds] = useState<
    [string, string] | null
  >(null);
  const [riseMeters, setRiseMeters] = useState(normalizedLocation.scene.rise);
  const speech = useAssemblyAISpeechToText([
    'show 2050',
    'show baseline',
    'show worst case',
    'compare now and 2100',
    'zoom in',
    'zoom out',
    'reset camera',
    'what floods first here',
    'what data is this based on',
    ...hotspots.flatMap((hotspot) => [hotspot.name, ...hotspot.aliases]),
  ]);
  const appendVoiceLog = (
    message: string,
    level: 'info' | 'error' = 'info',
  ) => {
    if (level === 'error') {
      console.warn(`[voice] ${message}`);
    } else {
      console.log(`[voice] ${message}`);
    }
  };
  const { speak, error: voicePlaybackError } = useVoicePlayback((event) => {
    appendVoiceLog(event.message, event.level ?? 'info');
  });
  const stopInFlightRef = useRef(false);
  const micStartInFlightRef = useRef(false);

  const activeHotspot =
    hotspots.find((hotspot) => hotspot.id === activeHotspotId) ?? hotspots[0];
  const activeScenario =
    scenarios.find((scenario) => scenario.id === activeScenarioId) ?? scenarios[0];

  const speakIfEnabled = async (text: string) => {
    appendVoiceLog(`Preparing spoken response: "${text.slice(0, 90)}${text.length > 90 ? '…' : ''}"`);
    await speak(text);
  };

  const getAIResponse = async (
    transcript: string,
  ): Promise<{ text: string | null; error: string | null }> => {
    try {
      appendVoiceLog(`Sending transcript to NVIDIA NIM: "${transcript}"`);
      const context = [
        `Location: ${normalizedLocation.name}`,
        `Active hotspot: ${activeHotspot.name} — ${activeHotspot.description}`,
        `Active scenario: ${activeScenario.label} (${activeScenario.year}), +${activeScenario.riseMeters}m sea level rise`,
        `Narration: ${activeScenario.narration}`,
      ].join('\n');
      const res = await fetch('/api/voice/respond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript, context }),
      });
      const data = (await res.json().catch(() => null)) as
        | { text?: string; error?: string }
        | null;
      if (!res.ok) {
        const errorMessage = data?.error ?? 'NVIDIA NIM request failed.';
        appendVoiceLog(`NVIDIA NIM error: ${errorMessage}`, 'error');
        return { text: null, error: errorMessage };
      }

      if (data?.text) {
        appendVoiceLog(`NVIDIA NIM replied with ${data.text.length} characters.`);
      } else {
        appendVoiceLog('NVIDIA NIM returned an empty reply.', 'error');
      }
      return { text: data?.text ?? null, error: null };
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : 'NVIDIA NIM request failed.';
      appendVoiceLog(`NVIDIA NIM request threw: ${errorMessage}`, 'error');
      return {
        text: null,
        error: errorMessage,
      };
    }
  };

  const runVoiceCommand = async (rawTranscript: string) => {
    setAiError(null);
    appendVoiceLog(`Mic release produced transcript: "${rawTranscript}"`);
    const intent = parseVoiceIntent(normalizedLocation, rawTranscript);
    appendVoiceLog(`Parsed voice intent: ${intent.type}`);
    setCommandLabel(describeIntent(intent.type));

    if (
      viewerState !== 'ready' &&
      ['go_to_hotspot', 'camera_move', 'camera_zoom', 'reset_camera'].includes(intent.type)
    ) {
      const loadingCopy = 'The scene is still loading. Try that command again in a moment.';
      appendVoiceLog('Viewer is still loading; command execution deferred.', 'error');
      setResponse(loadingCopy);
      await speakIfEnabled(loadingCopy);
      return;
    }

    switch (intent.type) {
      case 'go_to_hotspot': {
        const hotspot =
          hotspots.find((item) => item.id === intent.hotspotId) ?? activeHotspot;
        await viewerRef.current?.goToHotspot(intent.hotspotId);
        setActiveHotspotId(hotspot.id);
        const nextResponse = buildNavigationResponse(hotspot);
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'camera_move': {
        viewerRef.current?.moveCamera(intent.direction);
        const nextResponse = {
          caption: `Moved the camera ${intent.direction}.`,
          speech: `Moving ${intent.direction}.`,
        };
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'camera_zoom': {
        viewerRef.current?.zoomCamera(intent.direction);
        const nextResponse = {
          caption: `Zoomed ${intent.direction}.`,
          speech: intent.direction === 'in' ? 'Zooming in.' : 'Zooming out.',
        };
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'reset_camera': {
        viewerRef.current?.resetCamera();
        setActiveHotspotId(normalizedLocation.defaultHotspotId);
        const nextResponse = {
          caption: 'Camera reset to the default view.',
          speech: 'Resetting the camera to the default view.',
        };
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'set_scenario': {
        const scenario =
          scenarios.find((item) => item.id === intent.scenarioId) ?? activeScenario;
        viewerRef.current?.setScenario(scenario.id);
        setCompareScenarioIds(null);
        setActiveScenarioId(scenario.id);
        setRiseMeters(scenario.riseMeters);
        const nextResponse = buildScenarioResponse(
          normalizedLocation,
          scenario,
          intent.snappedFromYear,
        );
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'compare_scenarios': {
        const left =
          scenarios.find((item) => item.id === intent.leftId) ?? scenarios[0];
        const right =
          scenarios.find((item) => item.id === intent.rightId) ??
          scenarios[scenarios.length - 1];
        viewerRef.current?.compareScenario(left.id, right.id);
        setCompareScenarioIds([left.id, right.id]);
        setActiveScenarioId(right.id);
        setRiseMeters(right.riseMeters);
        const nextResponse = buildCompareResponse(normalizedLocation, left, right);
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'explain_current_view': {
        const nextResponse = buildCurrentViewResponse(
          normalizedLocation,
          activeHotspot,
          activeScenario,
        );
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'explain_flood_risk': {
        const hotspot = hotspots.find((item) => item.id === intent.hotspotId) ?? activeHotspot;
        const nextResponse = buildFloodRiskResponse(hotspot);
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'explain_sources': {
        const nextResponse = buildSourcesResponse(normalizedLocation);
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'help': {
        const nextResponse = buildHelpResponse(normalizedLocation);
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'unknown': {
        const { text: aiText, error } = await getAIResponse(rawTranscript);
        if (aiText) {
          setResponse(aiText);
          await speakIfEnabled(aiText);
        } else {
          setAiError(error);
          const nextResponse = buildUnknownResponse();
          setResponse(nextResponse.caption);
          await speakIfEnabled(nextResponse.speech);
        }
        return;
      }
    }
  };

  const stopMicRecording = async () => {
    if (stopInFlightRef.current) {
      return;
    }

    if (
      speech.state !== 'recording' &&
      speech.state !== 'connecting' &&
      speech.state !== 'stopping'
    ) {
      return;
    }

    stopInFlightRef.current = true;
    try {
      appendVoiceLog('Muted; finalizing transcript.');
      const nextTranscript = await speech.stopRecording();
      if (nextTranscript) {
        await runVoiceCommand(nextTranscript);
      } else {
        appendVoiceLog('AssemblyAI returned no final transcript.', 'error');
        setResponse(
          'No speech was recognized. Unmute, speak clearly, then mute when you are finished.',
        );
      }
    } finally {
      stopInFlightRef.current = false;
    }
  };

  const handleMicClick: MouseEventHandler<HTMLButtonElement> = async () => {
    if (
      speech.state === 'recording' ||
      speech.state === 'connecting' ||
      speech.state === 'stopping'
    ) {
      await stopMicRecording();
      return;
    }

    if (speech.state !== 'idle' && speech.state !== 'error') {
      return;
    }

    if (micStartInFlightRef.current) {
      return;
    }

    micStartInFlightRef.current = true;
    try {
      appendVoiceLog('Unmuted; streaming to AssemblyAI.');
      await speech.startRecording();
    } finally {
      micStartInFlightRef.current = false;
    }
  };

  const currentScenario: ScenarioRecord =
    compareScenarioIds?.[1]
      ? scenarios.find((scenario) => scenario.id === compareScenarioIds[1]) ??
        activeScenario
      : activeScenario;
  const compareScenarios = compareScenarioIds
    ? compareScenarioIds
        .map((id) => scenarios.find((scenario) => scenario.id === id))
        .filter(Boolean) as ScenarioRecord[]
    : [];
  const isOutputSplat = normalizedLocation.slug === 'output-splat';
  const scenarioLabel = compareScenarios.length
    ? `${compareScenarios[0].label} vs ${compareScenarios[1].label}`
    : currentScenario.label;
  const floodProgress = clamp(riseMeters / MAX_VISUALIZED_RISE_METERS, 0, 1);
  const missingAssemblyConfig = speech.error?.includes('AssemblyAI_API_KEY') ?? false;
  const outputSplatSummary =
    normalizedLocation.description.trim() ||
    activeHotspot.description ||
    currentScenario.narration;
  const voiceStatusLabel = missingAssemblyConfig
    ? 'Set ASSEMBLYAI_API_KEY to enable voice input'
    : speech.error
      ? speech.error
      : voicePlaybackError &&
          speech.state !== 'recording' &&
          speech.state !== 'connecting' &&
          speech.state !== 'stopping'
        ? `${voicePlaybackError} (Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in frontend/.env.local.)`
        : speech.state === 'connecting'
          ? 'Unmuted — connecting…'
          : speech.state === 'stopping'
            ? 'Processing — hang on…'
            : speech.state === 'recording'
              ? 'Listening — click to mute when you are done'
              : speech.audioSupport === 'unsupported'
                ? 'Voice is not supported in this browser'
                : 'Muted — click to unmute and speak';

  const viewerStage = (
    <div className={isOutputSplat ? 'splat-stage output-splat-stage' : 'splat-stage'}>
      <SplatViewer
        ref={viewerRef}
        floodProgress={floodProgress}
        floodCalibration={normalizedLocation.floodCalibration}
        floodOverlay={normalizedLocation.floodOverlay}
        hotspots={hotspots}
        onViewerStateChange={setViewerState}
        splatUrl={normalizedLocation.splatUrl}
        renderer={normalizedLocation.renderer ?? 'auto'}
      />
    </div>
  );

  const statsPanel = (
    <div className={isOutputSplat ? 'stats-panel output-splat-card' : 'stats-panel'}>
      <div className="stats-label">Sea Level Rise</div>
      <div className="stats-rise" style={{ color: currentScenario.color }}>
        +{riseMeters.toFixed(2)}
        <span className="stats-rise-unit">m</span>
      </div>
      <div className="stats-meta">
        <span className="stats-year">{currentScenario.year}</span>
        <span className="stats-meta-sep" aria-hidden={true}>
          ·
        </span>
        <span className="stats-scenario">{scenarioLabel}</span>
      </div>
      <div className="stats-narration">{currentScenario.narration}</div>
      <div className="stats-control">
        <label className="stats-control-label" htmlFor="water-level-slider">
          Water Level
        </label>
        <div className="stats-slider-row">
          <input
            id="water-level-slider"
            className="stats-slider"
            type="range"
            min={0}
            max={MAX_VISUALIZED_RISE_METERS}
            step={0.01}
            value={riseMeters}
            onChange={(event) => {
              setRiseMeters(Number.parseFloat(event.currentTarget.value));
            }}
            aria-label="Water level"
          />
          <div className="stats-slider-value">{Math.round(floodProgress * 100)}%</div>
        </div>
        <div className="stats-slider-scale">
          <span>Dry</span>
          <span>Flooded</span>
        </div>
      </div>
    </div>
  );

  const attrPanel = (
    <div
      className={
        isOutputSplat
          ? 'attr-panel attr-panel-splat-output output-splat-card'
          : 'attr-panel'
      }
    >
      <div className="attr-title">Location</div>
      <div className="attr-item attr-item-strong">{normalizedLocation.name}</div>
      {normalizedLocation.description.trim() ? (
        <div className="attr-item">{normalizedLocation.description}</div>
      ) : null}
      {isOutputSplat ? (
        <div className="attr-hotspot-inline">
          <span className="attr-hotspot-label">View</span>
          <span className="attr-item-strong">{activeHotspot.name}</span>
        </div>
      ) : (
        <>
          <div className="attr-title attr-title-spaced">Active Hotspot</div>
          <div className="attr-item attr-item-strong">{activeHotspot.name}</div>
          <div className="attr-item">{activeHotspot.description}</div>
        </>
      )}
      <div className="attr-title attr-title-spaced">Data Sources</div>
      {normalizedLocation.sources.map((source) => (
        <div key={source} className="attr-item">
          {source}
        </div>
      ))}
    </div>
  );

  const voiceAssistantBar = (
    <VoiceAssistantBar
      isCapturing={speech.state === 'recording'}
      isLive={speech.state === 'recording' || speech.state === 'connecting'}
      isProcessing={speech.state === 'stopping'}
      isSupported={!missingAssemblyConfig && speech.audioSupport !== 'unsupported'}
      isWorking={speech.state === 'connecting' || speech.state === 'stopping'}
      onMicClick={handleMicClick}
      liveTranscript={speech.transcript}
      statusLabel={voiceStatusLabel}
    />
  );

  const voiceCaptionPanel = (
    <VoiceCaptionPanel
      commandLabel={commandLabel}
      response={response}
      transcript={speech.transcript}
      error={speech.error ?? voicePlaybackError ?? aiError}
    />
  );

  return (
    <>
      <div className={isOutputSplat ? 'viewport viewport-output-splat' : 'viewport'}>
        {isOutputSplat ? (
          <div className="output-splat-layout">
            <section className="output-splat-main">
              <div className="output-splat-hero">
                <div className="output-splat-kicker">Pipeline Output</div>
                <div className="output-splat-hero-row">
                  <div className="output-splat-hero-copy">
                    <h1 className="output-splat-title">{normalizedLocation.name}</h1>
                    <p className="output-splat-summary">{outputSplatSummary}</p>
                  </div>
                  <div className="output-splat-status-grid" aria-label="Output metadata">
                    <div className="output-splat-status-card">
                      <span className="output-splat-status-label">Status</span>
                      <span className="output-splat-status-value">
                        {normalizedLocation.status}
                      </span>
                    </div>
                    <div className="output-splat-status-card">
                      <span className="output-splat-status-label">Updated</span>
                      <span className="output-splat-status-value">
                        {normalizedLocation.updatedAt}
                      </span>
                    </div>
                    <div className="output-splat-status-card">
                      <span className="output-splat-status-label">Active view</span>
                      <span className="output-splat-status-value">{activeHotspot.name}</span>
                    </div>
                    <div className="output-splat-status-card">
                      <span className="output-splat-status-label">Scenario</span>
                      <span className="output-splat-status-value">{scenarioLabel}</span>
                    </div>
                  </div>
                </div>
              </div>
              {viewerStage}
            </section>

            <aside className="output-splat-sidebar">
              {statsPanel}
              {attrPanel}
              <div className="output-splat-voice-stack">
                {voiceAssistantBar}
                {voiceCaptionPanel}
              </div>
            </aside>
          </div>
        ) : (
          <>
            <div className="viewport-main-column">
              <div className="viewport-theater-stack">
                {viewerStage}
                <div className="research-panel-kicker viewport-flow-kicker">
                  Orthogonal Flow 02
                </div>
              </div>

              <div className="viewport-below-window">
                <LocationResearchPanel
                  locationName={normalizedLocation.name}
                  region={normalizedLocation.region}
                  locationDescription={normalizedLocation.description}
                  activeHotspot={activeHotspot.name}
                  activeScenario={`${currentScenario.label} (${currentScenario.year})`}
                />
              </div>
            </div>
            {statsPanel}
            {attrPanel}
            {voiceAssistantBar}
            {voiceCaptionPanel}
          </>
        )}
      </div>
    </>
  );
}
