# Third-party components

Dreamina Director's own source is proprietary. It depends on separately licensed packages, which are not relicensed by this repository: Python/PSF; FastAPI and Starlette/MIT; Uvicorn/BSD; HTTPX/BSD; Pydantic/MIT; cryptography/Apache-2.0 or BSD; argon2-cffi/MIT; Pillow/HPND; python-multipart/Apache-2.0; and their transitive dependencies. Development uses pytest/MIT, jsonschema/MIT and Playwright/Apache-2.0. Verify the installed versions' actual license files before redistribution; this list is a pointer, not a replacement for notices.

FFmpeg/ffprobe and a browser engine are external executables; their licensing depends on the distributed build and enabled components. The operator installation uses ffprobe, not a bundled copy. Chromium is used only for development checks, not distributed in the host plugins.

The small SVG Corgi-Verse mark, interface CSS and test scene were authored for this implementation. No web fonts, stock photos, copied model-provider logos, or unrelated media are bundled. The provider-test video is an original synthetic calibration fixture, not AI-generated evidence.

MCP and host manifest formats are implemented from the linked primary specifications in docs/SOURCES.md. Refer to upstream license metadata and terms for those specifications and services. No official endorsement is asserted.
