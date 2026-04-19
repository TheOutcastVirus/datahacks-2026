import type { LocationRecord, ScenarioRecord, SceneHotspot } from '@/lib/locations';

export function buildNavigationResponse(hotspot: SceneHotspot) {
  return {
    caption: `Showing ${hotspot.name}.`,
    speech: hotspot.explainText || `Showing ${hotspot.name}.`,
  };
}

export function buildScenarioResponse(
  location: LocationRecord,
  scenario: ScenarioRecord,
  snappedFromYear?: number,
) {
  if (snappedFromYear && snappedFromYear !== scenario.year) {
    return {
      caption: `Showing ${scenario.year} for ${location.name}.`,
      speech: `I snapped that request to ${scenario.year}, the closest saved scenario for ${location.name}.`,
    };
  }

  return {
    caption: `Showing the ${scenario.label} scenario for ${location.name}.`,
    speech: `This view reflects the ${scenario.label.toLowerCase()} scenario for ${location.name}.`,
  };
}

export function buildCompareResponse(
  location: LocationRecord,
  left: ScenarioRecord,
  right: ScenarioRecord,
) {
  return {
    caption: `Comparing ${left.label} and ${right.label}.`,
    speech: `Comparing ${left.label.toLowerCase()} with ${right.label.toLowerCase()} for ${location.name}.`,
  };
}

export function buildCurrentViewResponse(
  location: LocationRecord,
  hotspot: SceneHotspot,
  scenario: ScenarioRecord,
) {
  return {
    caption: `${hotspot.name} in ${scenario.label}.`,
    speech: `You are looking at ${hotspot.name} in the ${scenario.label.toLowerCase()} scenario for ${location.name}. ${hotspot.description}`,
  };
}

export function buildFloodRiskResponse(hotspot: SceneHotspot) {
  return {
    caption: `${hotspot.name} floods earlier in this model.`,
    speech: hotspot.explainText,
  };
}

export function buildSourcesResponse(location: LocationRecord) {
  const [first, second, third] = location.sources;
  return {
    caption: `Sources: ${location.sources.join(', ')}.`,
    speech: `This scene references ${first}, ${second}, and ${third}.`,
  };
}

export function buildHelpResponse(location: LocationRecord) {
  const hotspotNames = location.hotspots.slice(0, 3).map((hotspot) => hotspot.name);
  return {
    caption: 'Try “show 2050”, “zoom out”, or “go to the waterfront”.',
    speech: `You can say things like show 2050, zoom out, reset camera, or go to ${hotspotNames.join(', ')}.`,
  };
}

export function buildUnknownResponse() {
  return {
    caption: `I didn't catch that. Try “show 2050” or “go to the waterfront”.`,
    speech: `I didn't catch that. Try saying show 2050 or go to the waterfront.`,
  };
}
