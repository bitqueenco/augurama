# Architecture and frozen contract

## Product path
Conversation → structured `GenerationPlan` → account-owned references → reviewed model/recipe compiler → immutable contract → human approval → one provider task → archived result → explicit revision.

Two host packages share one service. OpenAI uses portable Agent Plugins `plugin.json` plus `mcp.json`; Google uses its native `plugin.json` and `mcp_config.json`. The packages contain host-facing skills and identity assets, not generation algorithms. Optional MCP Apps UI and the standalone desk share the service's contract and authorization boundaries.

## Code map
| Responsibility | Source |
| --- | --- |
| Typed plans, timeline/reference invariants | `src/dreamina_director/models.py` |
| Model limits, prompt compiler, recipe snapshots | `compiler.py`, `data/models/`, `data/recipes/` |
| Transactions, constraints, account-local state | `db.py`, `service.py` |
| Provider POST/GET/DELETE mapping | `provider.py` |
| Credential encryption, account/OAuth lifecycle | `security.py`, `auth.py` |
| Media validation, signed delivery, outbound fetching | `assets.py`, `safe_fetch.py` |
| HTTP/OAuth/MCP serving and background status reads | `app.py`, `mcp.py` |
| Private operator lifecycle | `operations.py`, `cli.py` |
| Standalone desk / embedded card | `web/app.js`, `web/widget.js` |

## Contract invariants
The schema lives in `contracts/generation-plan.schema.json`, derived from the actual Pydantic model. `examples/paper-moon.plan.json` is valid input. The REST preparation envelope is **`{"plan": ...}`**, not the plan directly. The same envelope is the MCP prepare input.

A fingerprint covers the immutable snapshot, including exact original and compiled direction, ordered asset identities/hashes, provider model card/revision, recipe version/digest and estimate. Approval expires after twenty minutes. The approval nonce is private to the authenticated review surface; tool text/structured results must not reveal it. A nonce is not a provider credential.

A transactional one-contract/one-job constraint prevents duplicate paid submissions. The job is recorded before the provider request. Timeout, server error, interrupted process or an uncertain cancellation remain explicit uncertainty; no “helpful” retry. The already-recorded job remains idempotent even if its credential is subsequently removed. Do not create a new contract just to circumvent uncertainty.

The provider API does not supply a demonstrated exactly-once guarantee. The application therefore guarantees **no intentional automatic repeat POST for the same contract**, not mathematically exactly-once completion across all external failures. A provider task can exist while its ID is unknown locally. Resolve it through the provider console and `reconcile`.

## Models and creative direction
Four capability/pricing snapshots are included: Seedance 2.0, 2.0 Fast, 2.0 Mini and 2.5. API capabilities are conservative and must be reverified for an actual account. Public capability enumeration does not prove entitlement. A stale review date fails closed. No automatic model substitution.

Three original recipes organize narrative, product-film or continuous-take direction. They are deterministic production heuristics, not a learned model, extra hidden inference API, scientific finding or proven superior technique. Explicit authored direction takes precedence. The entire resulting prompt remains visible for meaningful approval. Server-side source confidentiality is useful but cannot guarantee that observable prompting behavior cannot be inferred.

## Operations and data
One POSIX service process owns SQLite and persistent media. Its lock prevents a second server or a concurrent stopped-service backup. No multi-region/replicated SQLite claim is made. Generations survive service restarts. Schema version 1 is checked before initialization; unsupported existing versions fail rather than silently migrate.

Provider credentials are per account and AES-GCM encrypted using an external production key. Passwords are Argon2 hashes. OAuth authorization codes use S256 PKCE, scoped audiences, exact redirect allowlists, one-time exchange and refresh-family reuse detection. No key is sent to a host plugin. Native callback compatibility still needs real-host testing.

Import URLs are HTTPS/public-address-only with pinned DNS results, redirect revalidation and size limits. Local files use an authenticated picker; filenames never become paths. Signed media URLs are bearer capabilities: possession permits temporary access. A provider reference delivery link lasts 48 hours; playback links last 15 minutes. Outputs are archived promptly rather than assuming provider URLs are permanent.

Account deletion removes access metadata transactionally before physical file removal. Failed cleanup is reported; hourly maintenance retries old unreferenced media. Backups are confidential independent copies and require their own deletion schedule. Active/uncertain jobs pin needed assets instead of losing recovery evidence.

## Protocol boundary
The hand-implemented stateless HTTP service supports current MCP `2026-07-28` discovery/request metadata and the implemented legacy initialization versions. The embedded card uses the documented MCP Apps bridge. Tests exercise JSON-RPC exchanges and a simulated host bridge, not the official SDK or an actual host. Do not advertise conformance certification until SDK/native cases pass.

## Deployment decision
A durable single-host service was chosen over ephemeral serverless SQLite. Existing GitHub→Vercel can later serve a marketing surface, but this release does not provision a new paid database/queue/host or pretend local disk will persist across serverless invocations. Container/proxy assets are an operator option, not a verified deployment.
