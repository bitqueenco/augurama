# Operator guide

## Local installation
Follow the root README. Keep the data directory and original encryption key together and out of source control. Use one server process. `.env` is documentation only until your shell/process manager exports it; arbitrary current-directory files are never auto-loaded.

`dreamina-director invite --label Owner` prints a one-use invitation (48-hour default). Give it through a private channel. Signup is invite-only; there is no email sender or automated password-reset service. `dreamina-director reset-password USERNAME` prompts securely and revokes existing sessions/OAuth tokens. Revocation does not cancel provider jobs.

## Production preparation
Use an **already authorized** persistent Linux/macOS host and an owned hostname. Supply `DD_ENV=production`, `DD_BASE_URL=https://<owned-host>`, `DD_DATA_DIR`, `DD_ENCRYPTION_KEY` (from `dreamina-director keygen`), a real `DD_PUBLIC_CONTACT`, and exact `DD_OAUTH_REDIRECT_URIS`. Preserve the generated key permanently; replacing it makes encrypted existing credentials unreadable. No key is printed by diagnostics.

Approve actual policies after reviewing `docs/legal/REVIEW.md`. Place the approved HTML fragments at `DD_DATA_DIR/policies/privacy.html` and `terms.html`, readable only by the service/operator; set `DD_LEGAL_APPROVED=1` only after this review. Production startup refuses missing policies. There are no invented company addresses or support emails in this delivery.

Run `dreamina-director doctor --production`. This checks local settings, cards, media executable and legal requirements; **it does not contact BytePlus or certify TLS/native readiness**. Bind `serve --host 127.0.0.1 --port 8765` behind your existing HTTPS reverse proxy. Preserve the public Host, Origin and Authorization headers; never trust arbitrary forwarded identity headers. Restrict direct backend access. Request bodies need at least the configured permitted upload size; logs must redact secrets and signed URL queries. Verify HTTPS, cookie security, rate limits, maximum upload size, byte-range video playback and long request timeouts on the actual proxy.

The optional Dockerfile/Compose configuration runs nonroot, exposes only loopback and mounts persistent `/data`. It was **not built or run** here. Before using it, provide `.env.production` privately, initialize the volume permissions for UID 10001 and copy approved policy files to its `policies/` directory. Back up any existing volume first. The root filesystem is read-only; `/tmp` is bounded. No production service is silently created by packaging.

A dedicated owned widget origin can be set through `DD_WIDGET_ORIGIN` when required by OpenAI. Test its actual routing/CSP; configuring a string does not provision the hostname. Keep the MCP endpoint stable after registration.

## Provider configuration and budgets
Users enter their own BytePlus API keys in the secure account form. Corgi-Verse does not spend a central shared key or substitute consumer Dreamina credits. Verify account/model entitlement using the actual provider account. Do not capture API keys in walkthrough recordings.

The USD estimate uses dated list-rate/token heuristics and excludes actual geometry differences, minimum token rules, taxes, discounts and negotiated pricing. `DD_MAX_ESTIMATED_USD_PER_JOB` blocks estimates above its threshold, not the final bill. `DD_DAILY_GENERATION_LIMIT` limits submitted jobs per account. Neither is a provider-side spending cap; configure a true provider-side budget separately. No paid check runs automatically in CI.

## Uncertain jobs and cancellation
Read the stored generation and provider console before considering another render. For a known matching provider task:

```sh
dreamina-director reconcile USERNAME GENERATION_ID PROVIDER_TASK_ID \
  --verified-in-provider-console
```

This attaches an operator-verified task ID; it does not resubmit or prove semantic identity automatically. Keep reconciliation evidence privately. A task that cannot be found must not be treated as a guaranteed refund; investigate account/time/model/outputs first.

Cancellation is offered only for an observed queued task. BytePlus can change state between read and delete, and deleting a completed task may delete its provider record. The UI/tool requires explicit acknowledgment of that race. Cancellation is not a refund guarantee or a running-task stop guarantee. Keep local archived results and provenance.

## Backup, restore and rollback
Stop the service cleanly before backup. Use a new confidential directory outside live data:

```sh
dreamina-director backup /private/new-backup-directory
# Restore to a NEW directory; retain the original key in DD_ENCRYPTION_KEY.
dreamina-director restore /private/new-backup-directory /private/new-restore-directory
```

Backups include SQLite and recorded media, a hash manifest, and the development key only when it is a protected local file. Production keys must be backed up independently in your existing secret system. A hash manifest detects damage, not malicious replacement of the entire backup; accept only trusted backups. Restore checks allowed paths, symlinks, file hashes, SQLite integrity/schema/foreign keys and the original key fingerprint before copying. Never overwrite a live data directory.

For rollback, stop the service, retain a new backup, restore the previous known source/wheel and run it against a **tested copy** of the corresponding data/old key. This release only supports schema 1; do not downgrade a future schema in place. Recheck account isolation, existing jobs and idempotent resubmission before redirecting traffic. Native/provider acceptance remains attached to its tested revision, not an arbitrary rollback.

## Retention and deletion
Default retention is 30 days; hourly maintenance removes eligible local records and unpinned media. Active/uncertain jobs stay pinned. `dreamina-director maintain` runs the same sweep manually. A failed file deletion reports `media_cleanup_pending`; old unreferenced files are retried. Investigate persistent nonzero cleanup counts and disk permissions. New imports have an hour of orphan-cleanup grace to avoid write/insert races.

`dreamina-director delete-account USERNAME --confirm-username USERNAME` removes that account's local data and credentials after all active/uncertain tasks are resolved. It does not delete provider history or independent backups. Apply the disclosed backup expiry policy separately. Do not promise instant worldwide deletion of data already sent to providers.

## Actual live acceptance
On the deployed HTTPS service, first prepare without paying:

```sh
python scripts/live_acceptance.py --origin https://<owned-host> \
  --username <test-account> --out /private/new-preparation-report.json
```

Only after an explicit provider budget decision, repeat with `--render` and a **new report path**. It requires an interactive person to type the entire contract fingerprint. There is exactly one generation POST, never an automatic retry. It then checks actual output retrieval, duration, aspect ratio and ffprobe metadata; human visual/identity/audio quality review is still required. Reports omit passwords, tokens and signed media URLs.

## Release/publishing
The guarded GitHub publisher applies the supplied patch only to the recorded unchanged base. On any conflict, inspect current work rather than forcing it. Public package generation requires real owner evidence tied to the current source digest and deployed origin. CI/package success alone does not authorize publication, external outreach, business registration or provider charges.
