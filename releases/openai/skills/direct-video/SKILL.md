---
name: direct-video
description: Direct and orchestrate frontier video models (MiniMax H3 Max, Wan 3.0, Kling V3 Turbo, Seedance 2.0/2.5) with Augurama by Corgi-Verse Software powered by fal.ai. Rendering requires separate human approval.
---
# Augurama

You are using Augurama by Corgi-Verse Software. The hosted service routes through fal.ai using the user's separately configured `FAL_KEY` account. Do not imply access to consumer credits or free generations.

## Supported Frontier Models
- **MiniMax H3 Max & H3 Max Turbo**: Ultra-low latency, prompt expansion modes (`balanced`, `quality`), photorealism, on-screen typography ($0.025–$0.08/s).
- **Alibaba Wan 3.0 & Wan 2.7**: Pre-render spatial reasoning ("Thinking" mode), multimodal conditioning (up to 10 images, 5 clips, 5 audio tracks) ($0.05–$0.18/s).
- **Kuaishou Kling V3 Turbo Pro & 2.6 Pro**: Native multi-shot storyboard sequencing via `multi_prompt` (up to 6 shots in a 15s pass) ($0.10–$0.14/s).
- **ByteDance Seedance 2.0 & 2.5**: Seedance 2.0, 2.5, Mini, Fast via fal.ai queue API.

## Operating sequence
1. Read `augurama_get_capabilities` at the beginning of a production session. Fetch current tool schemas and reviewed model profiles.
2. Establish the authored intent: subject, action, setting, camera behavior, timing, aspect ratio, sound, ending, and elements that must not change.
3. Analyze only the user-selected reference images/files already available to the host. Read `augurama_list_assets` before reimporting an existing asset. Use `augurama_import_reference` for selected files.
4. Declare likeness accurately. Raw real-person face references require authorized provider assets. Never relabel a real person as synthetic to bypass a rejection.
5. Create a complete `GenerationPlan` using the live prepare tool's input schema. `direction` is the user's intended scene in precise natural language. References are an ordered array of immutable asset IDs with explicit roles and instructions.
6. Call `augurama_prepare_generation` once the draft is coherent. Present the frozen card or returned `review_url`, exact settings and usage estimate. Preparation makes no paid generation request.
7. STOP at the approval boundary. Never call a paid action on the model's own initiative, impersonate a click, or use a shell to approve. The person approves the exact contract in the review card or web desk.
8. After an actual submission, use `augurama_get_generation` with the same generation ID. Only report success when the provider returned `succeeded` and the saved video is available.
9. Offer a variation/edit/extension only when requested. This creates a new plan with `parent_generation_id`, newly reviewed references, and a new human approval.

## Failure and cost rules
- `submission_unknown`: never retry or create a replacement automatically. Direct the operator to reconcile it in the provider console.
- Expired or invalidated approvals require a newly prepared contract.
- Provider credentials (`FAL_KEY`) are entered only on the secure account page, never in chat, tool arguments, project files, or logs.
