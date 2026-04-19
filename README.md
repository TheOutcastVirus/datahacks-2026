# Spatiotemporal Oceanographic Growth Simulator
Spatiotemporal Oceanographic Growth Simulator

## Repo layout

- `PLAN.md`: end-to-end project plan (source of truth).
- `frontend/`: Next.js app for the Spatiotemporal Oceanographic Growth Simulator demo UI.

## Quick start (frontend)

```bash
cd frontend
npm run dev
```

## Required environment variables

The voice controls use AssemblyAI for speech-to-text and ElevenLabs for playback.

Set these in your frontend environment before starting the app:

- `ASSEMBLYAI_API_KEY`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- `ELEVENLABS_MODEL_ID` (optional, defaults to `eleven_flash_v2_5`)
- `NVIDIA_API_KEY`
