# Verification record · 0.1.0-rc.1

**124 passed; 0 failed; 0 errors; 0 skipped.** Final recorded suite time: 12.861 seconds. See [raw JUnit](evidence/pytest.xml), [test output](evidence/pytest-output.txt) and [machine-readable evidence](evidence/verification.json).

Source digest: `1771889a3e481fabfe02fab8d424a152d963bbeb7c87924aef030aa6d1c10e23`. This digest covers runtime source/assets/cards, both host packages, Python build/lock configuration and Python release scripts; it is not a GitHub commit. Upstream base/branch remained `112f8f60d2e618ba100f3a514b0af6159a611c19` / `release/dual-plugin-rc1` on the final read. No push or hosted CI run occurred.

## Executed checks

| Test module | Passed cases |
| --- | ---: |
| `tests.test_auth` | 20 |
| `tests.test_browser_offline` | 2 |
| `tests.test_core` | 32 |
| `tests.test_http_mcp` | 13 |
| `tests.test_media_security` | 24 |
| `tests.test_operations` | 18 |
| `tests.test_packages` | 14 |
| `tests.test_server_cli` | 1 |

The suite exercises core compiler/provider wire mapping, approved single-submission behavior, concurrent duplicate clicks, uncertainty, credential isolation, account/OAuth/PKCE/scopes/refresh replay, hostile media imports, retention, backup/restoration, account cleanup faults, both host package layouts, reproducibility, registration-gate rejection, exported schema and a real installed-CLI TCP server.

The backend wheel was built and installed into an independent temporary target. Importing it outside the repository loaded all four model profiles, three recipes and packaged web assets. Python compilation, both JavaScript syntax checks and publisher shell syntax checks passed. No Docker build, dependency vulnerability scanner or official MCP SDK check ran.

## Browser evidence

Actual Chromium Chromium 144.0.7559.96 built on Debian GNU/Linux 13 (trixie) executed the production DOM/CSS/JavaScript at desktop 1440×1100 and mobile 390×844. Keyboard-only rights/billing approval, disabled/enabled button behavior, reduced-motion mode, no horizontal overflow and decoding a four-second fixture video passed with no page JavaScript exceptions. An actual iframe exercised the MCP Apps bridge through a simulated parent host at 1080×1000.

Browser URL navigation was administrator-blocked. The tests did not alter that policy: they used inline `about:blank` content and bridged requests through the real FastAPI TestClient. **They therefore do not verify real browser-origin cookies, deployed TLS/proxy behavior or native host integration.** HTTP/auth boundaries have separate service and real loopback tests; deployed browser behavior still needs verification.

Screenshots:
- [Production desk](evidence/desktop-desk.png)
- [Contract review](evidence/desktop-contract.png)
- [Mobile contract](evidence/mobile-contract.png)
- [Fixture playback](evidence/desktop-result-test-fixture.png)
- [Mobile fixture playback](evidence/mobile-result-test-fixture.png)
- [MCP Apps simulated-host review](evidence/mcp-apps-contract-offline-harness.png)

The video visibly says **TEST PROVIDER / No AI generation or charges**. It is a local FFmpeg fixture. Provider responses, tasks and usage in those tests are controlled test data, not observed BytePlus rendering or actual charges. No cinematic quality claim follows from successful fixture playback.

## Remaining acceptance

The actual provider call, native ChatGPT/Codex/Antigravity installs, live OAuth/SDK interoperability, HTTPS deployment, Docker build, CI, independent security review, publisher verification, legal/brand review and marketplace registration remain unexecuted. See [cases](review/CASES.md), [owner gates](review/release-gates.json) and [registration](REGISTRATION.md). No missing gate is silently marked passed.

The source archive and wheel contain proprietary code. Only the two thin host ZIPs are intended for eventual platform distribution. Default ZIPs point to localhost and remain local-development candidates, not ready-to-upload public listings.
