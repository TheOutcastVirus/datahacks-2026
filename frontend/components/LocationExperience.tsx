"use client";

import { useRef, useState } from "react";

import type { LocationRecord } from "@/lib/locations";
import type { ViewerCommandApi } from "@/lib/viewer-types";

import SplatViewer from "@/components/SplatViewer";
import SeaLevelTimeline from "@/components/SeaLevelTimeline";

const MAX_VISUALIZED_RISE_METERS = 4.0;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export default function LocationExperience({
  location,
}: {
  location: LocationRecord;
}) {
  const fallbackHotspot = {
    id: "overview",
    name: location.name,
    aliases: [location.name.toLowerCase(), "overview", "scene"],
    description: location.description,
    cameraPose: {
      position: [-3.5, 2, 5.5] as [number, number, number],
      target: [0, 0.4, 0] as [number, number, number],
    },
    explainText: `Showing ${location.name}. ${location.description}`,
  };
  const fallbackScenario = {
    id: "baseline",
    label: location.scene.label,
    year: location.scene.year,
    riseMeters: location.scene.rise,
    narration: `${location.name} is shown in its ${location.scene.label.toLowerCase()} state.`,
    color: location.scene.color,
  };
  const hotspots = location.hotspots?.length
    ? location.hotspots
    : [fallbackHotspot];
  const scenarios = location.scenarios?.length
    ? location.scenarios
    : [fallbackScenario];
  const normalizedLocation = {
    ...location,
    hotspots,
    scenarios,
    defaultHotspotId: location.defaultHotspotId ?? hotspots[0].id,
  };
  const viewerRef = useRef<ViewerCommandApi | null>(null);
  const [sliderYear, setSliderYear] = useState(2026);
  const [riseMeters, setRiseMeters] = useState(normalizedLocation.scene.rise);
  const [timelineVisible, setTimelineVisible] = useState(true);
  const floodProgress = clamp(riseMeters / MAX_VISUALIZED_RISE_METERS, 0, 1);

  return (
    <>
      <div className="viewport">
        <div className="splat-stage">
          <SplatViewer
            ref={viewerRef}
            floodProgress={floodProgress}
            hotspots={hotspots}
            hazardsUrl={normalizedLocation.hazardsUrl}
            splatUrl={normalizedLocation.splatUrl}
            renderer={normalizedLocation.renderer ?? "auto"}
          />
        </div>

        {timelineVisible ? (
          <SeaLevelTimeline
            sliderYear={sliderYear}
            riseMeters={riseMeters}
            onYearChange={(year, rise) => {
              setSliderYear(year);
              setRiseMeters(rise);
            }}
            onHide={() => setTimelineVisible(false)}
          />
        ) : (
          <button
            type="button"
            className="panel-tab"
            style={{ position: "absolute", bottom: 24, right: 16, zIndex: 30 }}
            onClick={() => setTimelineVisible(true)}
          >
            Sea Level ▲
          </button>
        )}
      </div>
    </>
  );
}
