export type VoiceIntent =
  | { type: 'go_to_hotspot'; hotspotId: string }
  | { type: 'camera_move'; direction: 'left' | 'right' | 'forward' | 'back' }
  | { type: 'camera_zoom'; direction: 'in' | 'out' }
  | { type: 'reset_camera' }
  | { type: 'set_scenario'; scenarioId: string; matchedYear?: number; snappedFromYear?: number }
  | { type: 'compare_scenarios'; leftId: string; rightId: string }
  | { type: 'explain_current_view' }
  | { type: 'explain_flood_risk'; hotspotId?: string }
  | { type: 'explain_sources' }
  | { type: 'help' }
  | { type: 'scan_hazards' }
  | { type: 'unknown'; transcript: string };
