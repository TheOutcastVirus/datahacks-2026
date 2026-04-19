'use client';

import { useRef, useState } from 'react';

import type { LocationRecord, ScenarioRecord } from '@/lib/locations';
import { getSeaLevel } from '@/lib/sea-level-data';
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
import SplatViewer from '@/components/SplatViewer';
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
  const fallbackHotspot = {
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
  const fallbackScenario = {
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
  const [speakerEnabled, setSpeakerEnabled] = useState(true);
  const [, setCommandLabel] = useState('Ready');
  const [, setResponse] = useState(
    'Use your voice to move around the scene, switch scenarios, and ask what the model is showing.',
  );
  const [activeHotspotId, setActiveHotspotId] = useState(normalizedLocation.defaultHotspotId);
  const [activeScenarioId, setActiveScenarioId] = useState(normalizedLocation.scenarios[0].id);
  const [compareScenarioIds, setCompareScenarioIds] = useState<
    [string, string] | null
  >(null);
  const [sliderYear, setSliderYear] = useState(2026);
  const [riseMeters, setRiseMeters] = useState(normalizedLocation.scene.rise);
  const [statsVisible, setStatsVisible] = useState(true);
  const [voiceVisible, setVoiceVisible] = useState(true);
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
  const { isPlaying: isVoicePlaying, speak } = useVoicePlayback();

  const activeHotspot =
    hotspots.find((hotspot) => hotspot.id === activeHotspotId) ?? hotspots[0];
  const activeScenario =
    scenarios.find((scenario) => scenario.id === activeScenarioId) ?? scenarios[0];

  const speakIfEnabled = async (text: string) => {
    if (!speakerEnabled) return;
    await speak(text);
  };

  const runVoiceCommand = async (rawTranscript: string) => {
    const intent = parseVoiceIntent(normalizedLocation, rawTranscript);
    setCommandLabel(describeIntent(intent.type));

    if (
      viewerState !== 'ready' &&
      ['go_to_hotspot', 'camera_move', 'camera_zoom', 'reset_camera'].includes(intent.type)
    ) {
      const loadingCopy = 'The scene is still loading. Try that command again in a moment.';
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
        setSliderYear(scenario.year);
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
        setSliderYear(right.year);
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
        const nextResponse = buildUnknownResponse();
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
    }
  };

  const handleMicClick = async () => {
    if (
      speech.state === 'recording' ||
      speech.state === 'connecting' ||
      speech.state === 'stopping'
    ) {
      const nextTranscript = await speech.stopRecording();
      if (nextTranscript) {
        await runVoiceCommand(nextTranscript);
      }
      return;
    }

    await speech.startRecording();
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
  const scenarioLabel = compareScenarios.length
    ? `${compareScenarios[0].label} vs ${compareScenarios[1].label}`
    : currentScenario.label;
  const floodProgress = clamp(riseMeters / MAX_VISUALIZED_RISE_METERS, 0, 1);

  return (
    <>
      <div className="viewport">
        <div className="splat-stage">
          <SplatViewer
            ref={viewerRef}
            floodProgress={floodProgress}
            hotspots={hotspots}
            onViewerStateChange={setViewerState}
            splatUrl={normalizedLocation.splatUrl}
            renderer={normalizedLocation.renderer ?? 'auto'}
          />
        </div>

        <div className="right-panel-stack">
          {statsVisible ? (
            <div className="stats-panel">
              <div className="stats-panel-header">
                <div className="stats-label">Sea Level Rise</div>
                <button type="button" className="panel-hide-btn" onClick={() => setStatsVisible(false)} aria-label="Hide panel">×</button>
              </div>
              <div className="stats-rise" style={{ color: currentScenario.color }}>
                +{riseMeters.toFixed(2)}
                <span className="stats-rise-unit">m</span>
              </div>
              <div className="stats-year">{sliderYear}</div>
              <div className="stats-scenario">{scenarioLabel}</div>
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
                    min={2026}
                    max={2100}
                    step={1}
                    value={sliderYear}
                    onChange={(event) => {
                      const year = Number.parseInt(event.currentTarget.value, 10);
                      setSliderYear(year);
                      setRiseMeters(getSeaLevel(year));
                    }}
                    aria-label="Year"
                  />
                  <div className="stats-slider-value">{Math.round(floodProgress * 100)}%</div>
                </div>
                <div className="stats-slider-scale">
                  <span>2026</span>
                  <span>2100</span>
                </div>
              </div>
            </div>
          ) : (
            <button type="button" className="panel-tab" onClick={() => setStatsVisible(true)}>Sea Level ▼</button>
          )}

          {voiceVisible ? (
            <VoiceAssistantBar
              isRecording={speech.state === 'recording'}
              isSpeaking={isVoicePlaying}
              isSupported={speech.isSupported}
              isWorking={speech.state === 'connecting' || speech.state === 'stopping'}
              onMicClick={handleMicClick}
              onToggleSpeaker={() => setSpeakerEnabled((current) => !current)}
              onHide={() => setVoiceVisible(false)}
              speakerEnabled={speakerEnabled}
              statusLabel={
                speech.error
                  ? speech.error
                  : speech.state === 'connecting'
                    ? 'Connecting to AssemblyAI…'
                    : speech.state === 'stopping'
                      ? 'Finalizing AssemblyAI transcript…'
                      : speech.state === 'recording'
                        ? 'Listening via AssemblyAI…'
                        : speech.isSupported
                          ? 'Tap the mic to start or stop recording'
                          : 'Mic recording is not supported in this browser'
              }
              transcript={speech.transcript}
            />
          ) : (
            <button type="button" className="panel-tab" onClick={() => setVoiceVisible(true)}>Voice ▼</button>
          )}
        </div>

        <div className="attr-panel">
          <div className="attr-title">Location</div>
          <div className="attr-item attr-item-strong">{normalizedLocation.name}</div>
          <div className="attr-item">{normalizedLocation.description}</div>
          <div className="attr-title attr-title-spaced">Active Hotspot</div>
          <div className="attr-item attr-item-strong">{activeHotspot.name}</div>
          <div className="attr-item">{activeHotspot.description}</div>
          <div className="attr-title attr-title-spaced">Data Sources</div>
          {normalizedLocation.sources.map((source) => (
            <div key={source} className="attr-item">
              {source}
            </div>
          ))}
        </div>

      </div>
    </>
  );
}
