# Dreamina Director engineering entry

Read `STATUS.md`, `docs/ARCHITECTURE.md`, `docs/VERIFICATION.md` and the applicable release README before changing code. GitHub is canonical; the delivered working tree was reconstructed from the original README because write access disappeared. Recorded upstream base: `112f8f60d2e618ba100f3a514b0af6159a611c19`. Review branch: `release/dual-plugin-rc1`. Inspect the live branch before applying anything.

## Frozen requirements
- Corgi-Verse Software identity; two separate host packages; private shared compiler/recipes.
- Original intent, timeline, reference order and model/recipe snapshots remain reviewable and immutable.
- Human approval binds to exactly one contract. No model-visible approval secrets, automatic paid retries, implicit credential sharing, or billing-cap claims about an estimate.
- Actual BytePlus API use, not fabricated consumer Dreamina integration or account credits.
- Isolate accounts; preserve data and uncertainty through restarts. No destructive recovery shortcuts.
- Keep native/provider/deployed evidence separate from mocks, offline browser harnesses and source review.

## Work
Run `python -m pytest -q`, compile Python, check both JavaScript files and build thin packages. Tests must not call a paid provider. Never weaken assertions to publish a green report. Native acceptance uses `docs/review/CASES.md`; actual paid checks require separate operator approval. `scripts/live_acceptance.py` defaults to free preparation and will not silently render.

Change recipe/model versions rather than mutating old contracts. Source-digest changes invalidate old public acceptance gates. No public repository visibility changes, purchases, registration submissions or broad new permissions are implied by this delivery.

Do not ship `src/`, data cards, source recipes, test credentials, backups or `.director/` in a host package. Run `scripts/package_releases.py`; public mode refuses missing evidence.

Next bounded goal and ready-to-use prompt: `docs/NEXT_AGENT.md`.
