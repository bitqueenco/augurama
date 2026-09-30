from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import html
import json
from pathlib import Path
import time
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import ValidationError

from . import __version__
from .auth import Principal
from .config import Settings
from .db import dumps
from .errors import DirectorError
from .mcp import MCP, safe_asset
from .models import CancelInput, GenerationPlan, ProviderAssetInput, SubmitInput
from .security import digest
from .service import Director

WEB = Path(__file__).parent / "web"
COOKIE = "dd_session"


def page(title: str, body: str) -> str:
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · Augurama</title><link rel="stylesheet" href="/static/style.css"></head><body><main class="legal"><a class="wordmark" href="/">AUGURAMA</a><p class="eyebrow">CORGI-VERSE SOFTWARE</p><h1>{html.escape(title)}</h1>{body}</main></body></html>'


def create_app(settings: Settings | None = None, director: Director | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.environment == "production":
        for policy in ("privacy", "terms"):
            if not (settings.data_dir / "policies" / (policy + ".html")).is_file():
                raise ValueError("Production requires approved privacy.html and terms.html fragments under DD_DATA_DIR/policies. See docs/REGISTRATION.md.")
    director = director or Director(settings)
    mcp = MCP(director)

    @asynccontextmanager
    async def lifespan(app):
        task = None
        stop = asyncio.Event()
        async def monitor():
            last_maintenance = 0.0
            # This deployed service polls existing task IDs only. It NEVER submits or retries generations.
            while not stop.is_set():
                if time.time() - last_maintenance >= 3600:
                    from .operations import maintain
                    try:
                        await run_in_threadpool(maintain, director)
                        last_maintenance = time.time()
                    except Exception:
                        director.db.audit(None, "maintenance.failed")
                ids = director.db.all("SELECT id,user_id FROM jobs WHERE status IN ('queued','running','submitting') OR (status='succeeded' AND (json_extract(result,'$.video_asset_id') IS NULL OR (json_extract(result,'$.last_frame_url') IS NOT NULL AND json_extract(result,'$.last_frame_asset_id') IS NULL))) ORDER BY updated_at ASC LIMIT 30")
                for row in ids:
                    if stop.is_set():
                        break
                    try:
                        await run_in_threadpool(director.get, row["user_id"], row["id"])
                    except Exception:
                        # No credentials, prompts, media URLs or provider response bodies enter logs.
                        director.db.audit(row["user_id"], "monitor.check_failed", row["id"])
                try:
                    await asyncio.wait_for(stop.wait(), timeout=15)
                except asyncio.TimeoutError:
                    pass
        if settings.environment != "test":
            task = asyncio.create_task(monitor())
        yield
        stop.set()
        if task:
            await task
        director.provider.close()

    app = FastAPI(title="Augurama", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.director = director
    app.state.mcp = mcp
    allowed_hosts = [urlsplit(settings.base_url).hostname]
    if settings.environment == "test":
        allowed_hosts += ["testserver", "localhost", "127.0.0.1"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS") and origin != settings.base_url:
            return JSONResponse({"error": {"code": "ORIGIN_REJECTED", "message": "Use this service's secure first-party page."}}, status_code=403)
        if request.url.path == "/mcp" and origin and origin not in {settings.base_url, "https://chatgpt.com", "https://antigravity.google"}:
            return Response(status_code=403)
        size = request.headers.get("content-length")
        maximum = settings.max_upload_bytes + 1024 * 1024 if request.url.path == "/api/assets/upload" else 1024 * 1024
        if size and (not size.isdigit() or int(size) > maximum):
            return JSONResponse({"error": {"code": "REQUEST_TOO_LARGE", "message": "Request size limit exceeded."}}, status_code=413)
        if request.url.path == "/api/assets/upload" and not size:
            return Response("A bounded Content-Length is required for file uploads.", status_code=411)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        if settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path != "/mcp":
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            response.headers["X-Frame-Options"] = "DENY"
        return response

    def failure(exc: DirectorError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(DirectorError)
    async def director_error(request, exc):
        return failure(exc)

    @app.exception_handler(ValidationError)
    @app.exception_handler(RequestValidationError)
    async def input_error(request, exc):
        errors = [{"path": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"error": {"code": "VALIDATION_ERROR", "message": "Check the request fields.", "details": errors}}, status_code=422)

    async def body(request: Request) -> dict:
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise DirectorError("CONTENT_TYPE", "Use application/json.", 415)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 1024 * 1024:
                raise DirectorError("REQUEST_TOO_LARGE", "JSON request is too large.", 413)
        try:
            value = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeDecodeError):
            raise DirectorError("INVALID_JSON", "Supply one valid JSON object.") from None

    def session(request: Request, write=False) -> Principal:
        return director.auth.session(request.cookies.get(COOKIE), request.headers.get("x-csrf-token"), write)

    def ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    @app.get("/healthz")
    def health():
        director.db.one("SELECT 1")
        return {"status": "ok", "version": __version__, "provider_status": "not_checked", "production": settings.environment == "production"}

    @app.get("/")
    def home():
        return FileResponse(WEB / "index.html", media_type="text/html")

    @app.get("/static/{filename}")
    def static(filename: str):
        types = {"app.js": "application/javascript", "style.css": "text/css", "mark.svg": "image/svg+xml"}
        if filename not in types:
            return Response(status_code=404)
        return FileResponse(WEB / filename, media_type=types[filename])

    @app.get("/api/public")
    def public():
        return {"capabilities": director.capabilities(), "version": __version__, "environment": settings.environment}

    @app.post("/api/signup")
    async def signup(request: Request):
        director.db.rate_limit("signup:" + ip(request), 5, 3600)
        data = await body(request)
        if set(data) != {"username", "password", "invitation"} or not all(isinstance(v, str) for v in data.values()):
            raise DirectorError("INVALID_SIGNUP", "Account name, password and invitation are required.")
        uid = await run_in_threadpool(director.auth.create_user, **data)
        return {"created": True}

    @app.post("/api/login")
    async def login(request: Request):
        director.db.rate_limit("login:" + ip(request), 20, 900)
        data = await body(request)
        if set(data) != {"username", "password"} or not all(isinstance(v, str) for v in data.values()):
            raise DirectorError("INVALID_LOGIN", "Account name and password are required.")
        director.db.rate_limit("login-account:" + digest(data["username"].lower()), 15, 900)
        token, csrf = await run_in_threadpool(director.auth.login, **data)
        response = JSONResponse({"signed_in": True, "csrf_token": csrf})
        response.set_cookie(COOKIE, token, max_age=43200, httponly=True, secure=settings.secure_cookies, samesite="lax", path="/")
        response.set_cookie("dd_csrf", csrf, max_age=43200, secure=settings.secure_cookies, samesite="strict", path="/")
        return response

    @app.post("/api/logout")
    def logout(request: Request):
        session(request, True)
        director.auth.logout(request.cookies.get(COOKIE, ""))
        response = JSONResponse({"signed_out": True})
        response.delete_cookie(COOKIE, path="/")
        response.delete_cookie("dd_csrf", path="/")
        return response

    @app.get("/api/account")
    def account(request: Request):
        who = session(request)
        user = director.db.one("SELECT provider_key FROM users WHERE id=?", (who.user_id,))
        return {"username": who.username, "provider_key_configured": bool(user["provider_key"]), "provider_access_verified": False, "retention_days": settings.retention_days}

    @app.post("/api/account/provider-key")
    async def provider_key(request: Request):
        who = session(request, True)
        data = await body(request)
        if set(data) != {"key"} or not isinstance(data["key"], str):
            raise DirectorError("INVALID_KEY", "A key string is required.")
        director.auth.save_provider_key(who.user_id, data["key"])
        return {"configured": bool(data["key"]), "access_verified": False}

    @app.get("/api/assets")
    def list_assets(request: Request):
        who = session(request)
        return {"assets": [{**safe_asset(a), "preview_url": director.assets.media_url(a)} for a in director.assets.list(who.user_id)]}

    @app.post("/api/assets/upload")
    async def upload(request: Request):
        who = session(request, True)
        director.db.rate_limit("upload:" + who.user_id, 50, 3600)
        async with request.form(max_files=1, max_fields=3, max_part_size=settings.max_upload_bytes) as form:
            file = form.get("file")
            if not file or not hasattr(file, "read") or form.get("rights_confirmed") != "true":
                raise DirectorError("UPLOAD_CONSENT", "Select a file and confirm you have permission to use it.")
            data = await file.read(settings.max_upload_bytes + 1)
            asset = await run_in_threadpool(director.assets.ingest, who.user_id, data, file.filename or "reference", form.get("likeness", "unknown"))
        return {"asset": safe_asset(asset)}

    @app.post("/api/assets/provider")
    async def provider_asset(request: Request):
        who = session(request, True)
        args = ProviderAssetInput.model_validate(await body(request))
        return {"asset": safe_asset(director.assets.register_provider_asset(who.user_id, args.uri, args.name, args.kind, args.duration))}

    @app.delete("/api/assets/{asset_id}")
    def delete_asset(asset_id: str, request: Request):
        who = session(request, True)
        director.assets.delete(who.user_id, asset_id)
        return {"deleted": True}

    @app.get("/media/{asset_id}")
    def media(asset_id: str, expires: int, signature: str):
        if not director.vault.verify_media(asset_id, expires, signature):
            return Response("Media link expired or is invalid.", status_code=403)
        row = director.db.one("SELECT metadata FROM assets WHERE id=?", (asset_id,))
        if not row:
            return Response(status_code=404)
        meta = json.loads(row["metadata"])
        if meta.get("provider_uri"):
            return Response(status_code=404)
        # FileResponse implements HEAD/ranges for video playback; filenames never become paths.
        return FileResponse(director.assets.path(meta), media_type=meta["mime"], headers={"Content-Disposition": 'inline; filename="' + asset_id + "." + meta["extension"] + '"'})

    @app.post("/api/contracts")
    async def prepare(request: Request):
        who = session(request, True)
        data = await body(request)
        if set(data) != {"plan"}:
            raise DirectorError("INVALID_INPUT", "Exactly one plan is required.")
        plan = GenerationPlan.model_validate(data["plan"])
        public, private = await run_in_threadpool(director.prepare, who.user_id, plan)
        return {"contract": public, "private": private}

    @app.get("/api/contracts/{cid}")
    def review(cid: str, request: Request):
        who = session(request)
        public, private = director.review(who.user_id, cid)
        return {"contract": public, "private": private}

    @app.delete("/api/contracts/{cid}")
    def invalidate(cid: str, request: Request):
        who = session(request, True)
        director.invalidate(who.user_id, cid)
        return {"invalidated": True}

    @app.get("/api/contracts/{cid}/export")
    def export_contract(cid: str, request: Request):
        who = session(request)
        public, _ = director.review(who.user_id, cid)
        return JSONResponse({"product": "Augurama", "publisher": "Corgi-Verse Software", "contract": public, "warning": "This is a direction/provenance export. Media assets remain private and are not bundled."}, headers={"Content-Disposition": 'attachment; filename="' + cid + '.json"'})

    @app.post("/api/generations")
    async def submit(request: Request):
        who = session(request, True)
        args = SubmitInput.model_validate(await body(request))
        return await run_in_threadpool(director.submit, who.user_id, args)

    @app.get("/api/generations")
    def list_jobs(request: Request):
        return {"generations": director.list(session(request).user_id)}

    @app.get("/api/generations/{jid}")
    async def get_job(jid: str, request: Request):
        who = session(request)
        return await run_in_threadpool(director.get, who.user_id, jid)

    @app.post("/api/generations/{jid}/cancel")
    async def cancel(jid: str, request: Request):
        who = session(request, True)
        data = await body(request)
        args = CancelInput.model_validate({**data, "generation_id": jid})
        return await run_in_threadpool(director.cancel, who.user_id, jid, args.accept_completed_record_deletion)

    # OAuth discovery follows RFC 9728 + RFC 8414.
    @app.get("/.well-known/oauth-protected-resource")
    @app.get("/.well-known/oauth-protected-resource/mcp")
    def protected_resource():
        return {"resource": settings.resource, "authorization_servers": [settings.base_url], "scopes_supported": ["director:read", "director:write"], "bearer_methods_supported": ["header"], "resource_name": "Augurama"}

    @app.get("/.well-known/oauth-authorization-server")
    def authorization_server():
        return {"issuer": settings.base_url, "authorization_endpoint": settings.base_url + "/oauth/authorize", "token_endpoint": settings.base_url + "/oauth/token", "registration_endpoint": settings.base_url + "/oauth/register", "revocation_endpoint": settings.base_url + "/oauth/revoke", "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none"], "scopes_supported": ["director:read", "director:write"], "authorization_response_iss_parameter_supported": True}

    @app.post("/oauth/register")
    async def register(request: Request):
        director.db.rate_limit("dcr:" + ip(request), 10, 3600)
        return JSONResponse(director.auth.register_client(await body(request)), status_code=201)

    @app.get("/oauth/authorize")
    def authorize(request: Request):
        try:
            who = session(request)
        except DirectorError:
            target = "/oauth/authorize?" + request.url.query
            return RedirectResponse("/?return_to=" + quote(target, safe=""), status_code=303)
        # Reject duplicate query parameters; never let different parsers disagree on redirect/resource.
        if len(request.query_params.multi_items()) != len(request.query_params):
            raise DirectorError("invalid_request", "Duplicate authorization parameters are not accepted.")
        rid, client = director.auth.authorization_request(dict(request.query_params))
        csrf = request.cookies.get("dd_csrf", "")
        scopes = html.escape(client["scope"])
        content = f'<p>Connect <strong>{html.escape(client["name"])}</strong> to your account <strong>{html.escape(who.username)}</strong>?</p><p>The host can read your projects and prepare video contracts. Paid generation still requires your explicit approval. Video generation runs through your fal.ai API key.</p><p class="mono">{scopes}</p><form method="post" action="/oauth/consent"><input type="hidden" name="request_id" value="{rid}"><input type="hidden" name="csrf" value="{html.escape(csrf, quote=True)}"><button class="primary" name="allow" value="yes">Connect account</button> <button name="allow" value="no">Cancel</button></form>'
        return HTMLResponse(page("Connect your creative workspace", content))

    @app.post("/oauth/consent")
    async def consent(request: Request):
        if request.headers.get("origin") != settings.base_url:
            raise DirectorError("CSRF_REJECTED", "Invalid consent origin.", 403)
        async with request.form(max_fields=3) as form:
            who = director.auth.session(request.cookies.get(COOKIE), form.get("csrf"), True)
            target = director.auth.consent(who.user_id, str(form.get("request_id", "")), form.get("allow") == "yes")
        return RedirectResponse(target, status_code=303)

    @app.post("/oauth/token")
    async def token(request: Request):
        director.db.rate_limit("token:" + ip(request), 120, 60)
        async with request.form(max_fields=12) as form:
            if len(form.multi_items()) != len(form):
                return JSONResponse({"error": "invalid_request", "error_description": "Duplicate fields are not accepted."}, status_code=400)
            try:
                result = director.auth.token(dict(form))
            except DirectorError as exc:
                return JSONResponse({"error": exc.code, "error_description": exc.message}, status_code=400)
        return JSONResponse(result, headers={"Pragma": "no-cache"})

    @app.post("/oauth/revoke")
    async def revoke(request: Request):
        async with request.form(max_fields=4) as form:
            director.auth.revoke(str(form.get("token", "")), str(form.get("client_id", "")))
        return Response(status_code=200)

    @app.api_route("/mcp", methods=["GET", "POST", "DELETE"])
    async def endpoint(request: Request):
        if request.method != "POST":
            return Response(status_code=405, headers={"Allow": "POST"})
        auth = request.headers.get("authorization", "")
        try:
            if not auth.startswith("Bearer "):
                raise DirectorError("INVALID_TOKEN", "Sign in to connect this plugin.", 401)
            who = director.auth.bearer(auth[7:])
        except DirectorError as exc:
            response = failure(exc)
            response.headers["WWW-Authenticate"] = f'Bearer resource_metadata="{settings.base_url}/.well-known/oauth-protected-resource", scope="director:read director:write"'
            return response
        try:
            message = await body(request)
        except DirectorError as exc:
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700 if exc.code == "INVALID_JSON" else -32600, "message": exc.message}}, status_code=exc.status)
        try:
            result, status = await run_in_threadpool(mcp.handle, who, message, dict(request.headers))
        except DirectorError as exc:
            return failure(exc)
        return Response(status_code=status) if result is None else JSONResponse(result, status_code=status)

    @app.get("/.well-known/openai-apps-challenge")
    def openai_domain_challenge():
        if not settings.openai_challenge_token:
            return Response(status_code=404)
        return Response(content=settings.openai_challenge_token, media_type="text/plain")

    @app.get("/privacy")
    def privacy():
        approved = settings.data_dir / "policies" / "privacy.html"
        if settings.legal_approved and approved.is_file():
            return HTMLResponse(page("Privacy notice", approved.read_text(encoding="utf-8")))
        contact = html.escape(settings.public_contact or "Operator contact must be configured before public launch")
        return HTMLResponse(page("Privacy notice", f'<p class="notice">Release-candidate notice · Corgi-Verse Software · Effective September 29, 2026</p><p>Dreamina Director stores your account name, password hash, encrypted ModelArk key, uploaded media, prompts, generation contracts, OAuth grants, provider task IDs, usage records and security audit events. It has no access to unrelated chats or repository files unless you explicitly attach them.</p><h2>Where information goes</h2><p>On approved execution, the selected prompt, reference media and required settings go to BytePlus ModelArk using your API account. Your host receives tool results and short-lived media links. Your provider key is never included in tool results. BytePlus and your host apply their own policies. We do not integrate consumer Dreamina subscriptions or credits.</p><h2>Storage and deletion</h2><p>Uploads and outputs are private to your account, except anyone holding an unexpired signed media link can access that file. Playback links expire after 15 minutes; provider fetch links last up to 48 hours. Keys are encrypted at rest. The operator must protect the storage volume and backups. Operational retention is {settings.retention_days} days for unpinned media and completed project records with hourly service maintenance or the operator maintenance command; active or unresolved jobs remain until reconciled. Delete unused media in the interface; request account deletion through the operator. No advertising, sale of personal data, or model-training pipeline is implemented in this release.</p><h2>Your controls</h2><p>You can remove your provider key, revoke host connections, export your contracts, delete unused media, and request account deletion. Changing/deleting a local item does not cancel an already running provider job or erase provider-side records.</p><h2>Contact</h2><p>{contact}</p><p>Before public distribution, the operator must confirm its legal identity, jurisdiction, contact, retention schedule and hosting/subprocessor disclosures match this notice.</p>'))

    @app.get("/terms")
    def terms():
        approved = settings.data_dir / "policies" / "terms.html"
        if settings.legal_approved and approved.is_file():
            return HTMLResponse(page("Service terms", approved.read_text(encoding="utf-8")))
        return HTMLResponse(page("Service terms", '<p class="notice">Release-candidate baseline · Requires operator approval before public distribution.</p><p>Dreamina Director is independently developed by Corgi-Verse Software. It is not an official ByteDance, CapCut, Google or OpenAI product, and no endorsement is claimed.</p><h2>Use and permission</h2><p>You must have the rights and consent necessary for every uploaded image, video, voice, likeness, trademark and music reference. Do not use this service to bypass provider safety controls. You must comply with applicable law and your host/provider terms.</p><h2>Charges and approvals</h2><p>Planning does not call a generative model. Generation uses your separately configured ModelArk API account. An estimate is not a quote, invoice or billing cap. You approve the exact contract before execution. Provider charges, refunds and availability are governed by your provider agreement. A failed or cancelled generation is not assumed to be free. Set an account-level spending limit with the provider.</p><h2>Ownership and limitations</h2><p>You retain rights you hold in your inputs. Rights in generated outputs depend on applicable provider terms and law. Corgi-Verse Software retains its software, recipe library, compiler and packaging. An approved contract cannot guarantee photorealism, exact identity, shot continuity or output suitability. Review every output before use. This prerelease has not passed marketplace review or an independent security audit.</p><h2>Public launch</h2><p>Commercial licensing, support commitments, consumer terms, jurisdiction and mandatory protections must be finalized by the operator before offering the service publicly. No subscription purchase or payment collection is implemented here.</p>'))

    return app
