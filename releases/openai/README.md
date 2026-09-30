# Dreamina Director · OpenAI release candidate
**Corgi-Verse Software · 0.1.0-rc.1 · ChatGPT / Codex**

This is the thin host package. The private Corgi-Verse service must run separately. Its compiled production instructions are reviewable; its source recipes are not included in this archive.

## Connect
This checked-in package targets `http://127.0.0.1:8765/mcp` for local development; it is **not a public submission ZIP**. ChatGPT web requires a provider-reachable public HTTPS backend. The operator generates a hosted package with the repository's `scripts/package_releases.py --origin ... --public` after configuring the real domain, support contact and approved policies.

For ChatGPT developer testing, enable Settings → Security and login → Developer mode. Open Plugins, choose the plus button, and enter the actual remote MCP URL. Choose OAuth and authorize your Dreamina Director account. Any technical plugin ID must come from that actual registration; none is fabricated here. Use the official plugin-creator workflow to map the registered connection to this package for local testing.

Codex/local marketplace testing uses this portable `plugin.json`, `mcp.json` and `skills/` layout. Ask the installed plugin-creator to add the folder to your personal marketplace; refresh and start a new conversation. A host without MCP Apps UI opens the same secure review URL for approval.

Sign up with an operator-issued invitation and configure your own BytePlus ModelArk API key on the account page. Never paste a key into chat. Ask: “Prepare a four-second synthetic paper-moon video. Show the contract before generating.”

## What is verified
The shared implementation has automated service, HTTP, OAuth, protocol, failure-recovery and offline Chromium tests. Native ChatGPT/Codex installation and a paid BytePlus render are separate outstanding acceptance gates. The included screenshot is the actual local production desk, not a claim of native-host validation or a generated AI result.

## Public registration
Use the source repository's `docs/REGISTRATION.md` and `docs/review/CASES.md`. Verify the Corgi-Verse publishing identity, bind a stable HTTPS endpoint, complete the domain challenge, configure reviewer access, run the native tests, upload the hosted ZIP, resolve findings, and submit. Publishing happens only after approval. Do not publish the private server repository or credentials.

Official instructions: https://developers.openai.com/plugins/build/plugins and https://developers.openai.com/plugins/deploy/submission (checked 2026-09-29).
