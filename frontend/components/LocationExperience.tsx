'use client';

import { useRef, useState } from 'react';

import type { LocationRecord, ScenarioRecord } from '@/lib/locations';
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
import { useLocalSpeechToText } from '@/hooks/useLocalSpeechToText';
import { useVoicePlayback } from '@/hooks/useVoicePlayback';

function describeIntent(intent: string) {
  return intent
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function LocationExperience({ location }: { location: LocationRecord }) {
  const viewerRef = useRef<ViewerCommandApi | null>(null);
  const pointerActiveRef = useRef(false);
  const [viewerState, setViewerState] = useState<ViewerState>('loading');
  const [speakerEnabled, setSpeakerEnabled] = useState(true);
  const [commandLabel, setCommandLabel] = useState('Ready');
  const [response, setResponse] = useState(
    'Use your voice to move around the scene, switch scenarios, and ask what the model is showing.',
  );
  const [activeHotspotId, setActiveHotspotId] = useState(location.defaultHotspotId);
  const [activeScenarioId, setActiveScenarioId] = useState(location.scenarios[0]?.id);
  const [compareScenarioIds, setCompareScenarioIds] = useState<
    [string, string] | null
  >(null);
  const speech = useLocalSpeechToText([
    'show 2050',
    'show baseline',
    'show worst case',
    'compare now and 2100',
    'zoom in',
    'zoom out',
    'reset camera',
    'what floods first here',
    'what data is this based on',
    ...location.hotspots.flatMap((hotspot) => [hotspot.name, ...hotspot.aliases]),
  ]);
  const playback = useVoicePlayback();

  const activeHotspot =
    location.hotspots.find((hotspot) => hotspot.id === activeHotspotId) ??
    location.hotspots[0];
  const activeScenario =
    location.scenarios.find((scenario) => scenario.id === activeScenarioId) ??
    location.scenarios[0];

  const speakIfEnabled = async (text: string) => {
    if (!speakerEnabled) return;
    await playback.speak(text);
  };

  const runVoiceCommand = async (rawTranscript: string) => {
    const intent = parseVoiceIntent(location, rawTranscript);
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
          location.hotspots.find((item) => item.id === intent.hotspotId) ?? activeHotspot;
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
        setActiveHotspotId(location.defaultHotspotId);
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
          location.scenarios.find((item) => item.id === intent.scenarioId) ?? activeScenario;
        viewerRef.current?.setScenario(scenario.id);
        setCompareScenarioIds(null);
        setActiveScenarioId(scenario.id);
        const nextResponse = buildScenarioResponse(
          location,
          scenario,
          intent.snappedFromYear,
        );
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'compare_scenarios': {
        const left =
          location.scenarios.find((item) => item.id === intent.leftId) ??
          location.scenarios[0];
        const right =
          location.scenarios.find((item) => item.id === intent.rightId) ??
          location.scenarios[location.scenarios.length - 1];
        viewerRef.current?.compareScenario(left.id, right.id);
        setCompareScenarioIds([left.id, right.id]);
        setActiveScenarioId(right.id);
        const nextResponse = buildCompareResponse(location, left, right);
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'explain_current_view': {
        const nextResponse = buildCurrentViewResponse(
          location,
          activeHotspot,
          activeScenario,
        );
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'explain_flood_risk': {
        const hotspot =
          location.hotspots.find((item) => item.id === intent.hotspotId) ?? activeHotspot;
        const nextResponse = buildFloodRiskResponse(hotspot);
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'explain_sources': {
        const nextResponse = buildSourcesResponse(location);
        setResponse(nextResponse.caption);
        await speakIfEnabled(nextResponse.speech);
        return;
      }
      case 'help': {
        const nextResponse = buildHelpResponse(location);
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

  const handlePressStart = async () => {
    pointerActiveRef.current = true;
    await speech.startRecording();
  };

  const handlePressEnd = async () => {
    if (!pointerActiveRef.current) return;
    pointerActiveRef.current = false;
    const nextTranscript = await speech.stopRecording();
    if (nextTranscript) {
      await runVoiceCommand(nextTranscript);
    }
  };

  const currentScenario: ScenarioRecord =
    compareScenarioIds?.[1]
      ? location.scenarios.find((scenario) => scenario.id === compareScenarioIds[1]) ??
        activeScenario
      : activeScenario;
  const compareScenarios = compareScenarioIds
    ? compareScenarioIds
        .map((id) => location.scenarios.find((scenario) => scenario.id === id))
        .filter(Boolean) as ScenarioRecord[]
    : [];
  const scenarioLabel = compareScenarios.length
    ? `${compareScenarios[0].label} vs ${compareScenarios[1].label}`
    : currentScenario.label;

  return (
    <>
      <div className="viewport">
        <div className="splat-stage">
          <SplatViewer
            ref={viewerRef}
            hotspots={location.hotspots}
            onViewerStateChange={setViewerState}
            splatUrl={location.splatUrl}
            renderer={location.renderer ?? 'auto'}
          />
        </div>

        <div className="stats-panel">
          <div className="stats-label">Sea Level Rise</div>
          <div className="stats-rise" style={{ color: currentScenario.color }}>
            +{currentScenario.riseMeters.toFixed(2)}
            <span className="stats-rise-unit">m</span>
          </div>
          <div className="stats-year">{currentScenario.year}</div>
          <div className="stats-scenario">{scenarioLabel}</div>
          <div className="stats-narration">{currentScenario.narration}</div>
        </div>

        <div className="attr-panel">
          <div className="attr-title">Location</div>
          <div className="attr-item attr-item-strong">{location.name}</div>
          <div className="attr-item">{location.description}</div>
          <div className="attr-title attr-title-spaced">Active Hotspot</div>
          <div className="attr-item attr-item-strong">{activeHotspot.name}</div>
          <div className="attr-item">{activeHotspot.description}</div>
          <div className="attr-title attr-title-spaced">Data Sources</div>
          {location.sources.map((source) => (
            <div key={source} className="attr-item">
              {source}
            </div>
          ))}
        </div>

        <VoiceAssistantBar
          isRecording={speech.state === 'recording'}
          isSpeaking={playback.isPlaying}
          isSupported={speech.isSupported}
          isWorking={speech.state === 'loading-model' || speech.state === 'transcribing'}
          onPressEnd={handlePressEnd}
          onPressStart={handlePressStart}
          onToggleSpeaker={() => setSpeakerEnabled((current) => !current)}
          speakerEnabled={speakerEnabled}
          statusLabel={
            speech.error
              ? speech.error
              : speech.state === 'loading-model'
                ? 'Preparing Chrome on-device speech…'
                : speech.state === 'transcribing'
                  ? 'Finalizing local transcript…'
                  : speech.state === 'recording'
                    ? 'Listening… release to send'
                    : speech.isSupported
                      ? 'Push to talk for scene commands'
                      : 'Chrome on-device speech is not supported in this browser'
          }
          transcript={speech.transcript}
        />

        <VoiceCaptionPanel
          commandLabel={commandLabel}
          error={speech.error ?? playback.error}
          response={response}
          transcript={speech.transcript}
        />
      </div>
    </>
  );
}
