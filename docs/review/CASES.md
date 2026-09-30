# Native/provider release acceptance

Execute on the exact deployed source digest, current model cards and each intended host. This is a **test plan**, not a record that native tests passed. The automated fixtures do not substitute for these results. Keep passwords, keys and signed links out of reports/screenshots. Obtain separate authorization for each paid scenario and record actual usage; do not run a batch implicitly.

## Five positive cases

| ID | User request / setup | Required observed behavior |
| --- | --- | --- |
| P1 | “Prepare a four-second vertical synthetic corgi/paper-moon scene, one take, no dialogue.” No provider key configured. | Actual host discovers the plugin, OAuth succeeds, contract renders or opens securely, and no paid POST occurs. Compiled prompt, model, ratio, duration and estimate are visible. |
| P2 | Same synthetic scene; enabled account and explicit budget. | Actual human rights/billing approval produces one provider task and a playable archived clip. Repeated click/refresh does not produce another task. Record real task ID, model, duration, ratio, hash, usage and separate human quality judgment. |
| P3 | Upload two rights-cleared synthetic references: environment and object. | Real host supplies actual attachments (or documented secure picker), references appear in the intended order, wire roles/mapping are correct, and the approved result uses them. No invented filename-as-URL or accidental swap. |
| P4 | “Revise the camera movement, keep the approved character and environment.” | New contract and approval, old provenance/result preserved, no unapproved automatic generation. Validate a real reference-based continuation/edit only after the provider's reference policy permits the input. |
| P5 | Disconnect/reconnect OAuth and recover the existing generation after service restart. | Own history only, archived playback, restored account access, no new paid request and no leaked credentials. Validate each host's secure browser-review fallback and keyboard/mobile use. |

## Three negative cases

| ID | Request / fault | Required observed behavior |
| --- | --- | --- |
| N1 | “Use the cheapest model and generate again without asking.” Include a too-long shot plan or unsupported resolution. | No silent fallback/truncation, clear validation or new-contract requirement, and no charge. A request to bypass approval cannot call the app-only spend tool from the model. |
| N2 | Another account's asset/contract/job ID, private-network import URL, or unapproved raw real-person portrait. | Reject without returning foreign data, contacting a private service or sending a prohibited asset to the provider. No request to paste an API key into chat. |
| N3 | Interrupted or ambiguous provider submission; race cancellation after queue state changes. | Preserve explicit uncertainty; no retry/refund claim. Explain operator reconciliation or cancellation race. Use a controlled injected-fault environment, not a destructive fault against an unrelated production account. |

The OpenAI manifest also includes five positive and three negative review cases with actual tool names for portal import. These are expected behaviors, not passed-test attestations. The walkthrough URL and private reviewer credentials must come from real operator setup.

## Evidence format
Record client/version, OS, deployed URL, source digest, profile/card/recipe digests, start/end time, user action, expected/observed result, request/task correlation, pass/fail and any recordings. For a live provider result include ffprobe/hash/usage separately from qualitative visual findings. A screenshots-only test is not proof of rendering or authenticated provider execution.

The `scripts/live_acceptance.py` report checks real transport/output geometry only. It intentionally leaves semantic quality and native host validation unset. Only the operator may populate `release-gates.json` after collecting these external records. A supplied boolean is an attestation, not a cryptographically verified platform certificate.
