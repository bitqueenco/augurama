# Model-epoch and recipe upgrades

## Separate what changes
The reusable host skills describe the workflow and approval boundaries. Capability cards declare model IDs, durations, image/video/audio limits, combinations, resolutions, real-face restrictions, dated pricing and primary sources. Private recipes describe original shot/continuity direction. Provider wire mapping is separate code. Do not turn one speculative model announcement into a silent change to every layer.

Current cards are `src/dreamina_director/data/models/*.json`, dated **2026-09-29** with a **2026-12-28** review deadline. These are documentation snapshots, not evidence of successful model calls. Stale cards fail closed. Current recipes in `data/recipes/` are narrative, product and continuous, version `1.0.0`.

## Bounded upgrade procedure
1. Read official model documentation, task schema, portrait/asset policy, pricing and the actual account's entitlement. Record exact IDs, URLs, review date and unresolved contradictions. Do not infer capabilities from a consumer website name alone.
2. Edit only the affected card/recipe or add a new profile. Bump its revision/version. Keep an old snapshot available to explain old results; existing stored contracts remain immutable. No URL/code fetched from an untrusted “model card” may execute.
3. Add boundary fixtures before broad deployment: min/max duration, every allowed resolution/ratio, image/video/audio counts and combinations, first/last frame, exact token mapping, silent vs voiced output, raw-person restrictions, expiry, unknown fields and too-long direction. Strict rejection beats silent truncation/fallback.
4. Run all automated tests and compare exact compiled prompts/wire payloads for canonical plans. Include ordinary narrative, a single uninterrupted shot, product evidence and reference-based edit/continue. Assertions must preserve user text, reference order and timing even when recommendations change.
5. With separate approval/budget, compare actual old/new model renders for the same authored scenes. Record task IDs, model/card/recipe digests, exact seed and parameters, hashes, latency, actual usage, failures and a human rubric. Distinguish decoding/geometry tests from visible continuity or audio quality. A seed is not a cross-model reproducibility guarantee.
6. Approve the new profile only after safety/cost/native host checks, then restart the single service to load the reviewed registry. Record a rollback source version and tested backup. Regenerate thin packages only if their interface, metadata or skills changed; their source digest still changes for new acceptance evidence.

## Visual evaluation rubric
Human reviewers should separately assess instruction adherence, identity/wardrobe, spatial continuity, shot timing, camera motion, anatomy/object stability, requested sound/dialogue, actual product truth and unwanted additions. Compare a small representative scene set before increasing volume. Do not publish “cinematic,” “best practice” or conversion/quality improvements as measured outcomes without actual comparative evidence.

The recipes are proprietary original heuristics organized around these concerns. They are easy to refine but have **not** been empirically shown superior to a baseline. Observable compiled prompts are intentionally reviewable by users; keep the source/server private, but do not promise absolute secrecy or a legal monopoly over general filmmaking techniques.
