# Sojs Flood-Risk Labeling and Fine-Tuning Plan

## Goal

Use the images that feed the Sojs SLAM / photogrammetry pipeline to identify flood-risk regions, then project those detections back into the 3D splat or SLAM scene as markers, masks, or clustered hotspots.

The right system split is:

1. `SLAM / photogrammetry`: reconstruct scene geometry from images
2. `Vision model`: detect or segment flood-relevant regions in 2D images
3. `Projection layer`: map 2D detections back into 3D
4. `Reasoning layer`: explain risk, evidence, confidence, and recommended action

Do not try to train a model directly on raw splats first. Use the source images and camera poses.

## Recommendation

### MVP

Use `Gemini` first for automatic labeling of source images because it already supports:

- object detection with bounding boxes
- segmentation masks

This gives a fast path to generating labels on our own scene images without fine-tuning first.

### Open-model path

If we want an open model we can fine-tune ourselves, use `PaliGemma` before `Gemma 3` for precise vision tasks.

Reason:

- `Gemma 3` is good for image and video understanding, but Google explicitly notes that specialized tools such as `PaliGemma` or CNNs are better for precise object detection and segmentation.
- `PaliGemma` is explicitly positioned for detection and segmentation tasks.

### Practical split

Use:

- `Gemini` or `PaliGemma` or `YOLOv8-seg` for localization
- `Gemma` for explanation, narration, and planner-facing summaries

That split is more reliable than forcing a single model to do everything.

## Label Taxonomy

Do not train on vague labels like `risk`.

Train on visible, scene-grounded classes such as:

- `flood_water`
- `shoreline_edge`
- `low_walkway`
- `terminal_access`
- `seawall_edge`
- `building_flooded`
- `road_flooded`
- `infrastructure_access`

If needed later, map these visible classes into higher-level planner labels like `high_risk_zone` or `critical_access_point`.

## Public Datasets Worth Using

### FloodNet

Best if our imagery is drone-like or aerial.

- High-resolution UAV flood imagery
- Semantic labels include flooded roads, flooded buildings, water, vehicles, trees, grass

Use it for:

- warm-start segmentation
- flood-water / flooded-road / flooded-building supervision

### xBD / xView2

Good for disaster damage assessment, worse fit for Sojs if the goal is waterfront flood extent overlays.

Use it for:

- damage classification research
- before/after building damage ideas

Not the first dataset I would choose for Sojs flood-zone overlays.

### V-FloodNet

Closer to Sojs if we use street-level images or video.

- Urban flood images and videos
- Water segmentation
- Depth-estimation context

Use it for:

- video-based flood extent detection
- flood-water segmentation on realistic scenes

### AlleyFloodNet

Useful for coarse flood vs non-flood recognition at ground level, but not sufficient by itself for precise boxes or masks.

Use it for:

- binary flood presence
- supplemental ground-level examples

## Best Strategy

### Step 1: Use Gemini as a teacher

Feed our real SLAM input images to Gemini and ask for machine-readable outputs.

Preferred prompt pattern:

```text
Return JSON only.
Identify visible flood-related regions in this image.

Classes:
- flood_water
- shoreline_edge
- low_walkway
- building_flooded
- road_flooded
- infrastructure_access

For each region return:
- label
- box_2d as [ymin, xmin, ymax, xmax] normalized 0-1000
- brief_reason
- confidence

Only mark visually grounded regions.
```

If using Gemini 2.5, use segmentation masks when possible instead of only boxes.

### Step 2: Manually clean the labels

Public datasets will not match our exact waterfront scenes, camera angles, or lighting. We need a cleaned internal dataset built from our own images.

Best starting target:

- `200-500` auto-labeled images
- manually corrected

### Step 3: Fine-tune the localization model

Choose one:

#### Option A: PaliGemma

Best Google-family open-weight path for image-to-detection / segmentation.

Use when:

- we want a multimodal open model
- we want to stay close to Gemma-family tooling

#### Option B: YOLOv8-seg

Best practical choice if the top priority is stable flood overlays in a demo.

Use when:

- we want robust masks or boxes
- we care more about segmentation quality than model-family purity

#### Option C: Gemma 3 vision fine-tune

Possible, but better for image-to-structured-text than precise localization.

Use when:

- we need scene explanation more than high-precision masks
- we want one model for image understanding and structured summaries

## What To Fine-Tune

Train on examples of:

- image or short video clip
- optional scene metadata
- task instruction
- target structured output

Example target output:

```json
{
  "summary": "The shoreline path is the earliest exposed zone.",
  "regions": [
    {
      "label": "low_walkway",
      "risk_type": "early_flood_exposure",
      "box_2d": [412, 280, 690, 470],
      "brief_reason": "Low, flat path directly adjacent to open water.",
      "confidence": 0.84
    }
  ],
  "recommended_action": "Prioritize shoreline edge protection and access-route review."
}
```

## Projection Back Into SLAM

This is the important part that turns image detections into a Sojs feature.

For each labeled image:

1. keep the camera intrinsics and extrinsics from SLAM
2. take each box or mask from the detector
3. back-project mask pixels or representative points into 3D
4. associate them with nearest points / splats / clusters
5. merge detections from multiple views
6. render the result in the viewer

Possible 3D UI outputs:

- pin markers
- highlighted splat clusters
- translucent region overlays
- risk heatmap built from repeated detections

## Recommended MVP Build

1. Choose one Sojs hotspot
2. Take `3-5` source images for that hotspot
3. Use Gemini to get masks or boxes
4. Project detections into the 3D scene
5. Show markers in the viewer
6. Clicking a marker opens:
   - label
   - confidence
   - brief reason
   - scenario-specific explanation

This is the shortest credible version.

## What Not To Do

- Do not train on raw `.ply` or splat tensors first
- Do not rely only on public datasets
- Do not ask the model to infer exact flood physics from a single image
- Do not use one vague label like `risk` for supervision
- Do not make Gemma the source of truth for exact flood boundaries

Use the model for semantic localization and explanation. Use geometry and deterministic code for projection and visualization.

## Decision

If we want the fastest path:

1. `Gemini` for auto-labeling and early detection / segmentation
2. `PaliGemma` or `YOLOv8-seg` for fine-tuned open-model localization
3. `Gemma` for flood-risk explanation and narration

That is the cleanest architecture for Sojs.

## Sources

- Gemini object detection and segmentation:
  - https://ai.google.dev/gemini-api/docs/vision
- Gemma image interpretation:
  - https://ai.google.dev/gemma/docs/capabilities/vision/image-interpretation
- Gemma video analysis:
  - https://ai.google.dev/gemma/docs/capabilities/vision/video-understanding
- Gemma vision fine-tuning:
  - https://ai.google.dev/gemma/docs/core/huggingface_vision_finetune_qlora
- Gemma general fine-tuning:
  - https://ai.google.dev/gemma/docs/tune
- PaliGemma overview:
  - https://ai.google.dev/gemma/docs/paligemma
- PaliGemma prompt and task syntax:
  - https://ai.google.dev/gemma/docs/paligemma/prompt-system-instructions
- FloodNet paper summary:
  - https://impact.ornl.gov/en/publications/floodnet-a-high-resolution-aerial-imagery-dataset-for-post-flood-/
- FloodNet dataset repo:
  - https://github.com/BinaLab/FloodNet-Supervised_v1.0
- xView2 / xBD overview:
  - https://www.ibm.com/think/insights/the-xview2-ai-challenge
- V-FloodNet paper:
  - https://www.sciencedirect.com/science/article/pii/S1364815222002869
- V-FloodNet repo:
  - https://github.com/xmlyqing00/V-FloodNet
- AlleyFloodNet paper:
  - https://www.mdpi.com/2079-9292/14/10/2082
