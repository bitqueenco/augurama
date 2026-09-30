"""Small stateless MCP endpoint: 2026-07-28 plus legacy 2025 clients.

Implements only advertised tools/resources; no fake streaming, sessions, sampling or tasks.
Native SDK/client acceptance is tracked separately from wire-contract tests.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Type

from pydantic import BaseModel, ValidationError

from . import __version__
from .auth import Principal
from .db import dumps
from .errors import DirectorError
from .models import CancelInput, ContractInput, EmptyInput, GenerationInput, ImportInput, ListInput, PrepareInput, ProviderAssetInput, SubmitInput
from .service import Director

VERSIONS = ["2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26"]
MODERN = VERSIONS[0]
UI_URI = "ui://augurama/review-v1.html"
LEGACY_UI_URI = "ui://dreamina-director/review-v1.html"
INFO = {"name": "augurama", "version": __version__, "title": "Augurama by Corgi-Verse Software"}
CAPABILITIES = {"tools": {}, "resources": {}, "extensions": {"io.modelcontextprotocol/ui": {}}}
INSTRUCTIONS = "Use capabilities before planning. Preserve user-approved story and ordered references. Prepare is free; rendering requires approval of the exact frozen contract in the review card or secure review link. Never request API keys in chat, impersonate consent, retry uncertain submissions or claim consumer credits are supported."


class RPCError(Exception):
    def __init__(self, code: int, message: str, data=None, http_status: int = 200):
        self.code, self.message, self.data, self.http_status = code, message, data, http_status


# name, title, description, input, scope, read_only, destructive, open_world, idempotent, UI, app_only
TOOLS = [
    ("augurama_get_capabilities", "Read video capabilities", "Read reviewed model profiles, limits and account requirements. Does not call a generation provider.", EmptyInput, "director:read", True, False, False, True, False, False),
    ("augurama_get_account", "Read connection status", "Read the signed-in account and whether a provider key is configured. Never returns the key or a credit balance.", EmptyInput, "director:read", True, False, False, True, False, False),
    ("augurama_import_reference", "Import a reference", "Copy a user-selected host attachment to private media storage. Declare actual likeness and permission. Does not generate media or incur model charges.", ImportInput, "director:write", False, False, True, False, False, False),
    ("augurama_register_provider_asset", "Use a provider-authorized asset", "Register a genuine provider asset URI already authorized. This does not authorize a likeness by itself. Supply provider-verified duration for video/audio.", ProviderAssetInput, "director:write", False, False, False, False, False, False),
    ("augurama_list_assets", "Read private references", "List only references belonging to the current account, including immutable IDs and metadata.", ListInput, "director:read", True, False, False, True, False, False),
    ("augurama_prepare_generation", "Prepare a frozen video contract", "Compile the user's approved direction and ordered references into a reviewable contract and approximate API cost. Never calls the paid generation endpoint. Show the review card or review_url for human approval.", PrepareInput, "director:write", False, False, False, False, True, False),
    ("augurama_get_contract", "Review a video contract", "Read an existing immutable contract. Show its exact prompt, model, settings, references and estimate. The human approves in the card or secure review URL.", ContractInput, "director:read", True, False, False, True, True, False),
    ("augurama_invalidate_contract", "Invalidate an unused approval", "Expire a prepared contract after the user requests a revision or cancellation. Does not stop an already submitted generation.", ContractInput, "director:write", False, False, False, True, False, False),
    ("augurama_submit_generation", "Approve and generate video", "Paid action, only for a direct human click in the review app. Requires its private approval token, exact fingerprint and rights/billing acknowledgement. One provider task maximum per contract. Never infer consent.", SubmitInput, "director:write", False, False, True, True, True, True),
    ("augurama_get_generation", "Read generation status", "Check the same provider task, and archive finished output into private media storage. Does not create or retry a generation. Provider media expires, so retrieve results promptly.", GenerationInput, "director:read", False, False, True, True, True, False),
    ("augurama_list_generations", "Read recent generations", "List recorded jobs without polling the provider or starting any generation.", ListInput, "director:read", True, False, False, True, False, False),
    ("augurama_cancel_generation", "Request queued-task cancellation", "Only on explicit human approval: checks queued state then sends provider DELETE. A race with completion may delete the provider record. Running tasks cannot be cancelled; no refund is assumed.", CancelInput, "director:write", False, True, True, False, True, True),
]


def tool_descriptors() -> list[dict]:
    result = []
    for name, title, description, model, scope, readonly, destructive, external, idem, ui, private in TOOLS:
        schema = model.model_json_schema()
        if model is ImportInput:
            # OpenAI file-input contract: optional file metadata must be declared as strings.
            schema["properties"]["file"] = {"type": "object", "properties": {p: {"type": "string"} for p in ("download_url", "file_id", "mime_type", "file_name")}, "required": ["download_url", "file_id"], "additionalProperties": False}
        schemes = [{"type": "oauth2", "scopes": [scope]}]
        meta = {"securitySchemes": schemes}
        if ui:
            meta.update({"ui": {"resourceUri": UI_URI, "visibility": ["app"] if private else ["model", "app"]}, "openai/outputTemplate": UI_URI, "openai/widgetAccessible": True})
        if private:
            meta["openai/visibility"] = "private"
        if model is ImportInput:
            meta["openai/fileParams"] = ["file"]
        if name in ("augurama_get_account", "dreamina_get_account"):
            meta["openai/profile"] = True
        result.append({"name": name, "title": title, "description": description, "inputSchema": schema, "outputSchema": {"type": "object", "additionalProperties": True}, "annotations": {"readOnlyHint": readonly, "destructiveHint": destructive, "openWorldHint": external, "idempotentHint": idem}, "securitySchemes": schemes, "_meta": meta})
    return sorted(result, key=lambda t: t["name"])


def safe_asset(asset: dict) -> dict:
    return {k: v for k, v in asset.items() if k not in ("provider_original_url", "provider_original_expires", "extension")}


class MCP:
    def __init__(self, director: Director):
        self.d = director

    def tool(self, principal: Principal, name: str, arguments: dict) -> dict:
        canonical_name = name.replace("dreamina_", "augurama_")
        spec = next((t for t in TOOLS if t[0] in (name, canonical_name)), None)
        if not spec:
            raise RPCError(-32602, "Unknown tool")
        try:
            principal.require(spec[4])
            if not isinstance(arguments, dict):
                raise RPCError(-32602, "Tool arguments must be an object")
            args = spec[3].model_validate(arguments)
            uid = principal.user_id
            private = {}
            if canonical_name == "augurama_get_capabilities":
                data = self.d.capabilities()
            elif canonical_name == "augurama_get_account":
                user = self.d.db.one("SELECT provider_key FROM users WHERE id=?", (uid,))
                data = {"username": principal.username, "provider_key_configured": bool(user["provider_key"]), "provider_access_verified": False, "account_url": self.d.settings.base_url + "/#account", "billing": "Separate Fal.ai API billing (FAL_KEY)."}
            elif canonical_name == "augurama_import_reference":
                asset = self.d.assets.import_url(uid, args.file.download_url, args.file.file_name or args.file.file_id, args.likeness)
                data = {"asset": safe_asset(asset)}
            elif canonical_name == "augurama_register_provider_asset":
                data = {"asset": safe_asset(self.d.assets.register_provider_asset(uid, args.uri, args.name, args.kind, args.duration))}
            elif canonical_name == "augurama_list_assets":
                data = {"assets": [safe_asset(a) for a in self.d.assets.list(uid, args.limit)]}
            elif canonical_name == "augurama_prepare_generation":
                data, private = self.d.prepare(uid, args.plan)
            elif canonical_name == "augurama_get_contract":
                data, private = self.d.review(uid, args.contract_id)
            elif canonical_name == "augurama_invalidate_contract":
                self.d.invalidate(uid, args.contract_id)
                data = {"contract_id": args.contract_id, "invalidated": True}
            elif canonical_name == "augurama_submit_generation":
                data = self.d.submit(uid, args)
            elif canonical_name == "augurama_get_generation":
                data = self.d.get(uid, args.generation_id)
            elif canonical_name == "augurama_list_generations":
                data = {"generations": self.d.list(uid, args.limit)}
            elif canonical_name == "augurama_cancel_generation":
                data = self.d.cancel(uid, args.generation_id, args.accept_completed_record_deletion)
            else:
                raise RPCError(-32601, "Tool implementation not found")

            return {"content": [{"type": "text", "text": dumps(data)}], "structuredContent": data, "_meta": private, "isError": False}
        except ValidationError as exc:
            errors = [{"path": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors(include_input=False, include_url=False)]
            return {"content": [{"type": "text", "text": "Invalid input: " + dumps(errors)}], "structuredContent": {"error": {"code": "VALIDATION_ERROR", "details": errors}}, "isError": True}
        except DirectorError as exc:
            return {"content": [{"type": "text", "text": exc.message}], "structuredContent": {"error": {"code": exc.code, "message": exc.message}}, "isError": True}

    def resource(self) -> dict:
        web = Path(__file__).parent / "web"
        html = (web / "widget.html").read_text().replace("/*__STYLES__*/", (web / "style.css").read_text()).replace("/*__SCRIPT__*/", (web / "widget.js").read_text())
        base = self.d.settings.base_url
        meta = {"ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": [base]}}, "openai/widgetDescription": "Review the exact video contract, explicitly approve paid generation, and inspect the result.", "openai/widgetCSP": {"connect_domains": [], "resource_domains": [base], "redirect_domains": [base]}, "openai/ui": {"availableDisplayModes": ["inline", "fullscreen"]}}
        if self.d.settings.widget_origin:
            meta["ui"]["domain"] = self.d.settings.widget_origin
            meta["openai/widgetDomain"] = self.d.settings.widget_origin
        return {"uri": UI_URI, "mimeType": "text/html;profile=mcp-app", "text": html, "_meta": meta}

    def handle(self, principal: Principal, message: dict, headers: dict) -> tuple[dict | None, int]:
        rid = message.get("id") if isinstance(message, dict) else None
        try:
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str) or ("id" in message and (not isinstance(rid, (int, str)) or isinstance(rid, bool))):
                raise RPCError(-32600, "Invalid JSON-RPC request", http_status=400)
            method, params = message["method"], message.get("params", {})
            if not isinstance(params, dict):
                raise RPCError(-32602, "params must be an object", http_status=400)
            meta = params.get("_meta", {})
            if not isinstance(meta, dict):
                raise RPCError(-32602, "_meta must be an object", http_status=400)
            requested = meta.get("io.modelcontextprotocol/protocolVersion", headers.get("mcp-protocol-version", "2025-11-25"))
            if method != "initialize" and requested not in VERSIONS:
                raise RPCError(-32022, "Unsupported protocol version", {"supported": VERSIONS, "requested": requested}, 400)
            modern = requested == MODERN and method != "initialize"
            if modern:
                if meta.get("io.modelcontextprotocol/protocolVersion") != headers.get("mcp-protocol-version") or not isinstance(meta.get("io.modelcontextprotocol/clientCapabilities"), dict):
                    raise RPCError(-32602, "Modern requests require matching header/_meta protocolVersion and clientCapabilities", http_status=400)
                client = meta.get("io.modelcontextprotocol/clientInfo")
                if client is not None and (not isinstance(client, dict) or not isinstance(client.get("name"), str) or not isinstance(client.get("version"), str)):
                    raise RPCError(-32602, "Malformed clientInfo", http_status=400)
                if headers.get("mcp-method") != method:
                    raise RPCError(-32602, "Mcp-Method must match the body", http_status=400)
                if method in ("tools/call", "prompts/get") and headers.get("mcp-name") != params.get("name"):
                    raise RPCError(-32602, "Mcp-Name must match the body", http_status=400)
            if "id" not in message:
                if method not in ("notifications/initialized", "notifications/cancelled"):
                    raise RPCError(-32600, "Requests require an id; notification cannot invoke a tool", http_status=400)
                return None, 202
            principal.require("director:read")
            if method == "initialize":
                pv = params.get("protocolVersion")
                if not isinstance(pv, str) or not isinstance(params.get("capabilities"), dict) or not isinstance(params.get("clientInfo"), dict):
                    raise RPCError(-32602, "initialize requires protocolVersion, capabilities and clientInfo")
                result = {"protocolVersion": pv if pv in VERSIONS[1:] else "2025-11-25", "serverInfo": INFO, "capabilities": {"tools": {}, "resources": {}}, "instructions": INSTRUCTIONS}
            elif method == "server/discover":
                result = {"supportedVersions": VERSIONS, "capabilities": CAPABILITIES, "instructions": INSTRUCTIONS, "ttlMs": 0, "cacheScope": "private"}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                if params.get("cursor"):
                    raise RPCError(-32602, "No cursor is valid for this complete tool list")
                result = {"tools": tool_descriptors(), "ttlMs": 0, "cacheScope": "private"}
            elif method == "resources/list":
                result = {"resources": [{"uri": UI_URI, "name": "Video review card", "mimeType": "text/html;profile=mcp-app"}], "ttlMs": 0, "cacheScope": "private"}
            elif method == "resources/templates/list":
                result = {"resourceTemplates": [], "ttlMs": 0, "cacheScope": "private"}
            elif method == "resources/read":
                if params.get("uri") not in (UI_URI, LEGACY_UI_URI):
                    raise RPCError(-32002, "Resource not found")
                result = {"contents": [self.resource()], "ttlMs": 0, "cacheScope": "private"}
            elif method == "tools/call":
                self.d.db.rate_limit("mcp:" + principal.user_id, 300, 60)
                result = self.tool(principal, params.get("name"), params.get("arguments", {}))
            else:
                raise RPCError(-32601, "Method not found")
            if modern:
                result["resultType"] = "complete"
                result.setdefault("_meta", {})["io.modelcontextprotocol/serverInfo"] = INFO
            return {"jsonrpc": "2.0", "id": rid, "result": result}, 200
        except RPCError as exc:
            error = {"code": exc.code, "message": exc.message}
            if exc.data is not None:
                error["data"] = exc.data
            return {"jsonrpc": "2.0", "id": rid, "error": error}, exc.http_status
