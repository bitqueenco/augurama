# Registration and distribution · checked 2026-09-29

This document separates a local install from native acceptance and public marketplace approval. No submission, account purchase, registration payment, public source disclosure or external outreach occurred during this build.

## 1. Establish the actual publisher
Use the real Corgi-Verse Software publishing identity you can verify; this delivery does not establish a legal entity, trademark registration or permission to use another company's brand. The product and listing must say it is independent. Review the “Dreamina Director” name, relevant provider commercial/distribution terms, logos and any required written permission before offering it. The independent original corgi mark is included; no ByteDance/Google/OpenAI endorsement badge is used.

Decide who operates the service, where data is processed, real support/deletion contacts, privacy/terms, retention/backups and incident response. The company name alone is not legal review. Keep the full source repository private; only distribute the thin host ZIPs.

Deploy a stable owned HTTPS origin and run `docs/OPERATIONS.md`. There is no deployed endpoint in this delivery. BYOK onboarding requires an invitation, Director account and a separately enabled BytePlus account. Disclose this accurately. A reviewer account should already exist and work; do not require the reviewer to provision an account, obtain credentials, pay or resolve MFA before testing.

## 2. OpenAI: ChatGPT and Codex

Authoritative guides: [package layout](https://developers.openai.com/plugins/build/plugins), [submission](https://developers.openai.com/plugins/deploy/submission), [review requirements](https://developers.openai.com/plugins/deploy/app-review), [OAuth](https://developers.openai.com/plugins/build/auth).

**Development connection.** Enable developer mode in ChatGPT Settings → Security and login, open Plugins and use the plus control to register the deployed MCP URL with OAuth. Obtain the actual technical connection ID; never invent an `app_id`. Follow the documented plugin-creator/local marketplace mapping to associate that connection with the OpenAI folder. Run the same package in Codex. If the host lacks MCP Apps UI, verify the authenticated browser approval link. Localhost is not a reachable public ChatGPT backend.

**Publisher access.** Use the appropriate OpenAI organization with a verified publishing identity and owner or Apps Management Write permission. Prepare the actual company/site/support/privacy information. Register the MCP connection from the initial submission; do not assume it can be added to a skills-only release later. This candidate declares one MCP connection.

**Domain challenge.** Use the exact token and host issued in the portal. Configure `DD_OPENAI_CHALLENGE_TOKEN`; the service serves that public value as plain text at `/.well-known/openai-apps-challenge`, with no markup. Verify its actual HTTPS URL from outside your network. No challenge token has been issued or verified here.

**Native review evidence.** Execute the five positive and three negative cases in `docs/review/CASES.md` on actual target clients. Record the real deployment/revision, model and results. Provide a functioning preconfigured reviewer account and an accessible walkthrough that demonstrates login/OAuth, reference selection, contract approval, a real provider result and error/recovery. Agree to and budget any reviewer provider costs explicitly; no shared funded account was created in this turn.

**Package.** During testing create hosted staging packages:

```sh
python scripts/package_releases.py --origin https://<owned-host> --out dist
```

The output has actual endpoint metadata but still does not claim native/public acceptance. After completing the owner gates, supply their actual evidence, exact origin and current source digest:

```sh
python scripts/package_releases.py --origin https://<owned-host> \
  --public --evidence /private/completed-release-gates.json --out dist
```

The OpenAI manifest includes the required five positive and three negative case definitions for import; execute them and supply the real walkthrough URL before submission. Reviewer credentials stay outside the ZIP.

Upload **only the OpenAI ZIP with `plugin.json` at its root**, not the source ZIP/wheel. Complete the portal's metadata, domain and review checks; fix findings and resubmit if necessary. Publication is a separate action after approval. Do not promise a review turnaround or automatic listing. Preserve the stable MCP URL and keep future platform requirements under review.

The local validator checks expected file shapes; it is not OpenAI's validator. SDK interoperability, host-supported UI details and marketplace review remain essential external checks. `docs/review/release-gates.json` deliberately records them as false until observed.

## 3. Google: Antigravity

Authoritative guides: [plugins](https://antigravity.google/docs/plugins?tab=ide), [MCP](https://antigravity.google/docs/mcp).

**Local installation.** Extract the Antigravity ZIP and use `agy plugin install /absolute/path/to/extracted-folder`, then `agy plugin list`; the interactive CLI also documents `/plugin install`. In the IDE, workspace plugins are under `.agents/plugins/`, or use `~/.gemini/config/plugins/` for global configuration. Review the detected skills, rules and MCP connection in Customizations. Do not overwrite an existing installation or add automatic spend hooks.

The package uses Google's `mcp_config.json` with `serverUrl`, not the OpenAI `mcp.json` connection shape. Authorize the Director account through OAuth. If the actual installed client presents another callback, add that **exact** callback after verification; never broaden to a wildcard. Run all relevant acceptance cases and confirm the browser-review fallback works in this host. Document the tested Antigravity version.

**Curated distribution.** The reviewed official documentation establishes curated marketplace discovery and local install mechanisms, but it did **not establish an open self-service publisher submission portal**. Local installation is therefore the actionable route; curated-shelf inclusion requires Google to confirm its current publisher/partner process. Do not claim that uploading a ZIP makes a plugin globally available.

A publisher inquiry should contain the independent product summary, company/site, thin Antigravity archive or authorized distribution location, real HTTPS endpoint, two skill descriptions, declared permissions, OAuth/data-flow explanation, privacy/support policies, real recorded acceptance and a working reviewer account. Ask for the official submission/security-review route and permitted branding/distribution terms. This is a preparation checklist; no inquiry has been sent and no contact address is fabricated.

## 4. Owner gates and post-approval operation

The release evidence must be tied to the exact source digest and tested origin. Source changes require reassessing affected acceptance, not copying old checkmarks. The generated package always says `marketplace_registered: false`; platform approval is an external record, not something a build script can grant.

Maintain support, provider model/card updates, expiring-media archival, backup expiry and incident response after any launch. If the invite-only design is not suitable for a public offer, implement and verify real self-service onboarding before changing that promise in the listing. A plugin listing is not evidence that the separately operated backend will remain available.
