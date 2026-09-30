from __future__ import annotations

import hmac
import json
import time
from datetime import datetime, timezone

from .assets import Assets
from .auth import Auth
from .compiler import Registry
from .config import Settings
from .db import Database, dumps
from .errors import DirectorError, SubmissionUncertain
from .models import GenerationPlan, SubmitInput
from .provider import BytePlus, FalAI, ProviderRouter
from .security import Vault, digest, new_id, random_token

ACTIVE = {"submitting", "submission_unknown", "queued", "running", "cancel_outcome_unknown"}


class Director:
    def __init__(self, settings: Settings, *, provider: BytePlus | ProviderRouter | FalAI | None = None, fetcher=None, registry: Registry | None = None):
        self.settings = settings
        self.db = Database(settings.data_dir / "director.sqlite3")
        self.vault = Vault(settings.encryption_key)
        self.auth = Auth(self.db, settings, self.vault)
        self.assets = Assets(self.db, settings, self.vault, fetcher)
        self.registry = registry or Registry()
        self.provider = provider or ProviderRouter(BytePlus(settings.provider_base_url), FalAI())

    def capabilities(self) -> dict:
        return {"product": "Augurama", "publisher": "Corgi-Verse Software", "independent_integration": True, "provider": "Fal.ai", "consumer_dreamina_accounts": False, "consumer_dreamina_credits": False, "operations": ["generate", "edit", "extend"], "generation_requires_human_approval": True, "billing": "Your separately configured Fal.ai API account (FAL_KEY).", "model_registry": self.registry.public(), "account_url": self.settings.base_url + "/#account", "limits": {"estimated_usd_per_job": self.settings.max_estimated_usd_per_job, "generations_per_day": self.settings.daily_generation_limit}, "notes": ["Provider access is account-specific; listed capabilities are not an entitlement check.", "Editing/extension generate new interpretations, not lossless timeline edits.", "Raw real-person face references require the provider's authorized asset workflow."]}

    def prepare(self, uid: str, plan: GenerationPlan) -> tuple[dict, dict]:
        self.db.rate_limit("prepare:" + uid, 60, 3600)
        if plan.parent_generation_id:
            self._job(uid, plan.parent_generation_id)
        assets = [self.assets.get(uid, ref.asset_id) for ref in plan.references]
        for asset in assets:
            if not asset.get("provider_uri"):
                self.assets.path(asset)
        snapshot = self.registry.compile(plan, assets)
        if snapshot["estimate"]["approximate_usd"] > self.settings.max_estimated_usd_per_job:
            raise DirectorError("ESTIMATE_LIMIT", "Estimated usage exceeds the operator's per-generation limit. Reduce duration or choose a less expensive reviewed model.", 409)
        cid, approval, now = new_id("contract"), random_token(), time.time()
        snapshot.update(schema_version=1, created_at=now, contract_id=cid)
        fingerprint = digest(dumps(snapshot))
        with self.db.transaction() as c:
            for asset in snapshot["assets"]:
                if not c.execute("SELECT 1 FROM assets WHERE id=? AND user_id=?", (asset["id"], uid)).fetchone():
                    raise DirectorError("ASSET_MISSING", "A reference was removed while preparing this contract.", 409)
                if not asset.get("provider_uri"):
                    self.assets.path(asset)
            c.execute("INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?)", (cid, uid, fingerprint, dumps(snapshot), digest(approval), self.vault.encrypt(approval, f"approval:{uid}:{cid}"), now, now + 1200))
        self.db.audit(uid, "contract.prepared", cid, {"fingerprint": fingerprint, "model": snapshot["model_card"]["model_id"], "recipe_version": snapshot["recipe_version"]})
        return self.review(uid, cid)

    def _contract(self, uid: str, cid: str) -> dict:
        row = self.db.one("SELECT * FROM contracts WHERE id=? AND user_id=?", (cid, uid))
        if not row:
            raise DirectorError("CONTRACT_NOT_FOUND", "Contract not found in your account.", 404)
        row["snapshot"] = json.loads(row["snapshot"])
        if not hmac.compare_digest(digest(dumps(row["snapshot"])), row["fingerprint"]):
            raise DirectorError("CONTRACT_INTEGRITY", "Contract integrity check failed. Submission is blocked.", 409)
        return row

    def review(self, uid: str, cid: str) -> tuple[dict, dict]:
        row = self._contract(uid, cid)
        s = row["snapshot"]
        job = self.db.one("SELECT id FROM jobs WHERE contract_id=? AND user_id=?", (cid, uid))
        public = {"contract_id": cid, "fingerprint": row["fingerprint"], "expires_at": row["expires_at"], "expired": row["expires_at"] <= time.time(), "plan": s["plan"], "compiled_prompt": s["compiled_prompt"], "reference_map": s["reference_map"], "estimate": s["estimate"], "model_id": s["model_card"]["model_id"], "model_revision": s["model_card"]["revision"], "recipe_version": s["recipe_version"], "warnings": s["warnings"], "review_url": self.settings.base_url + "/?contract=" + cid, "generation_id": job["id"] if job else None}
        # _meta is widget-only. Do not duplicate approval tokens in model-visible text/structuredContent.
        private = {"approval_token": self.vault.decrypt(row["approval_encrypted"], f"approval:{uid}:{cid}"), "preview_assets": [{**{k: v for k, v in m.items() if k not in ("provider_original_url", "provider_original_expires")}, "preview_url": self.assets.media_url(m)} for m in s["assets"] if not m.get("provider_uri")], "account_url": self.settings.base_url + "/#account"}
        return public, private

    def invalidate(self, uid: str, cid: str):
        self._contract(uid, cid)
        self.db.execute("UPDATE contracts SET expires_at=0 WHERE id=? AND user_id=?", (cid, uid))
        self.db.audit(uid, "contract.invalidated", cid)

    def _payload(self, snapshot: dict) -> dict:
        p = snapshot["plan"]
        content = [{"type": "text", "text": snapshot["compiled_prompt"]}]
        for ref, asset in zip(snapshot["reference_map"], snapshot["assets"]):
            key = asset["kind"] + "_url"
            url = asset.get("provider_original_url") if asset.get("trusted_output") else None
            if url and asset.get("provider_original_expires", 0) <= time.time():
                raise DirectorError("TRUSTED_OUTPUT_EXPIRED", "Original provider reference expired. A new authorized reference is required.", 409)
            content.append({"type": key, key: {"url": url or self.assets.media_url(asset, 48 * 3600)}, "role": ref["provider_role"]})
        payload = {"model": snapshot["model_card"]["model_id"], "content": content, "duration": p["duration_seconds"], "ratio": p["aspect_ratio"], "resolution": p["resolution"], "generate_audio": p["audio"]["enabled"], "watermark": p["watermark"], "return_last_frame": True}
        if p["seed"] is not None:
            payload["seed"] = p["seed"]
        return payload

    def submit(self, uid: str, approval: SubmitInput) -> dict:
        row = self._contract(uid, approval.contract_id)
        if not hmac.compare_digest(row["fingerprint"], approval.fingerprint) or not hmac.compare_digest(row["approval_digest"], digest(approval.approval_token)):
            raise DirectorError("APPROVAL_MISMATCH", "Approval does not match this frozen contract.", 403)
        existing = self.db.one("SELECT id FROM jobs WHERE contract_id=? AND user_id=?", (row["id"], uid))
        if existing:
            return self.get(uid, existing["id"], poll=False)
        # Credential validation does not call the provider or spend anything.
        key = self.auth.provider_key(uid)
        s = row["snapshot"]
        for asset in s["assets"]:
            if not asset.get("provider_uri"):
                self.assets.path(asset)
                if self.settings.environment != "test" and not self.settings.base_url.startswith("https://"):
                    raise DirectorError("PUBLIC_MEDIA_URL_REQUIRED", "Reference generation requires a provider-reachable public HTTPS service. Local HTTP works for text-only API calls, not hosted media.", 409)
        payload = self._payload(s)
        now, jid = time.time(), new_id("gen")
        with self.db.transaction() as c:
            existing = c.execute("SELECT id FROM jobs WHERE contract_id=? AND user_id=?", (row["id"], uid)).fetchone()
            if existing:
                existing_id = existing["id"]
            else:
                existing_id = None
                # Re-read expiry inside the write transaction to serialize invalidation.
                expires = c.execute("SELECT expires_at FROM contracts WHERE id=?", (row["id"],)).fetchone()[0]
                if expires <= now:
                    raise DirectorError("APPROVAL_EXPIRED", "This approval expired or was invalidated. Prepare a fresh contract.", 409)
                midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                count = c.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND created_at>=?", (uid, midnight)).fetchone()[0]
                if count >= self.settings.daily_generation_limit:
                    raise DirectorError("DAILY_LIMIT", "The daily generation limit has been reached. No provider request was made.", 429)
                for asset in s["assets"]:
                    if not c.execute("SELECT 1 FROM assets WHERE id=? AND user_id=?", (asset["id"], uid)).fetchone():
                        raise DirectorError("ASSET_MISSING", "An approved reference is missing; no generation was submitted.", 409)
                    if not asset.get("provider_uri"):
                        self.assets.path(asset)
                c.execute("INSERT INTO jobs(id,user_id,contract_id,status,created_at,updated_at) VALUES(?,?,?,'submitting',?,?)", (jid, uid, row["id"], now, now))
        if existing_id:
            return self.get(uid, existing_id, poll=False)
        self.db.audit(uid, "generation.approved", jid, {"fingerprint": row["fingerprint"], "estimated_usd": s["estimate"]["approximate_usd"]})
        try:
            task = self.provider.create(key, payload)
        except SubmissionUncertain as exc:
            self.db.execute("UPDATE jobs SET status='submission_unknown',result=?,updated_at=? WHERE id=?", (dumps({"error": exc.message}), time.time(), jid))
            self.db.audit(uid, "generation.submission_unknown", jid)
        except DirectorError as exc:
            self.db.execute("UPDATE jobs SET status='failed',result=?,updated_at=? WHERE id=?", (dumps({"error": exc.message, "error_code": exc.code}), time.time(), jid))
        except BaseException:
            # System exit, cancelled request or unforeseen error: record uncertainty, never retry a paid POST.
            self.db.execute("UPDATE jobs SET status='submission_unknown',result=?,updated_at=? WHERE id=?", (dumps({"error": "Submission was interrupted. Check the provider console before creating another generation."}), time.time(), jid))
            raise
        else:
            self.db.execute("UPDATE jobs SET status='queued',provider_task_id=?,updated_at=? WHERE id=?", (task, time.time(), jid))
            self.db.audit(uid, "generation.submitted", jid, {"provider_task_id": task})
        return self.get(uid, jid, poll=False)

    def _job(self, uid: str, jid: str) -> dict:
        row = self.db.one("SELECT * FROM jobs WHERE id=? AND user_id=?", (jid, uid))
        if not row:
            raise DirectorError("GENERATION_NOT_FOUND", "Generation not found in your account.", 404)
        row["result"] = json.loads(row["result"])
        return row

    def _archive(self, uid: str, row: dict, result: dict) -> dict:
        # Only an actual succeeded provider task is eligible for a trusted provider-output marker.
        for field, key, name in (("video_url", "video_asset_id", "generated-video.mp4"), ("last_frame_url", "last_frame_asset_id", "last-frame.jpg")):
            if result.get(field) and not result.get(key):
                try:
                    raw, _ = self.assets.fetcher.download(result[field], self.settings.max_upload_bytes)
                    asset = self.assets.ingest(uid, raw, name, "unknown", source="modelark-output", trusted_output=True, provider_original_url=result[field], provider_original_expires=row["created_at"] + 23 * 3600)
                    if (field == "video_url" and asset["kind"] != "video") or (field == "last_frame_url" and asset["kind"] != "image"):
                        self.db.execute("DELETE FROM assets WHERE id=?", (asset["id"],))
                        self.assets.path(asset).unlink(missing_ok=True)
                        raise DirectorError("OUTPUT_TYPE_MISMATCH", "Provider output did not match its declared media type.", 502)
                    result[key] = asset["id"]
                    result.pop("archive_error", None)
                    # Persist each success, so a second-output failure never causes video duplication on retry.
                    self.db.execute("UPDATE jobs SET result=?,updated_at=? WHERE id=?", (dumps(result), time.time(), row["id"]))
                except DirectorError as exc:
                    result["archive_error"] = exc.message
        result["archived"] = bool(result.get("video_asset_id"))
        return result

    def get(self, uid: str, jid: str, *, poll: bool = True) -> dict:
        row = self._job(uid, jid)
        now = time.time()
        # Crash recovery is deliberately conservative.
        if row["status"] == "submitting" and now - row["updated_at"] > 120:
            self.db.execute("UPDATE jobs SET status='submission_unknown',result=? WHERE id=? AND status='submitting'", (dumps({"error": "Submission did not finish recording a task ID. Reconcile it with the provider console; never retry automatically."}), jid))
            row = self._job(uid, jid)
        if poll and row["provider_task_id"] and row["status"] in ("queued", "running", "cancel_outcome_unknown") and now - row["last_polled_at"] >= 3:
            # Acquire a short polling lease. Concurrent client polls cannot multiply provider requests.
            acquired = self.db.execute("UPDATE jobs SET last_polled_at=? WHERE id=? AND last_polled_at<=?", (now, jid, now - 3))
            if acquired:
                try:
                    result = self.provider.get(self.auth.provider_key(uid), row["provider_task_id"])
                    status = result["status"]
                    self.db.execute("UPDATE jobs SET status=?,result=?,updated_at=? WHERE id=?", (status, dumps(result), now, jid))
                    row = self._job(uid, jid)
                except DirectorError as exc:
                    row["result"]["poll_error"] = exc.message
        if poll and row["status"] == "succeeded" and (not row["result"].get("video_asset_id") or (row["result"].get("last_frame_url") and not row["result"].get("last_frame_asset_id"))):
            # Archive lease prevents duplicate imports when two hosts request the same completed task.
            acquired = self.db.execute("UPDATE jobs SET last_polled_at=? WHERE id=? AND last_polled_at<=?", (time.time() + 60, jid, time.time()))
            if acquired:
                result = self._archive(uid, row, row["result"])
                self.db.execute("UPDATE jobs SET result=?,last_polled_at=?,updated_at=? WHERE id=?", (dumps(result), time.time() + (10 if result.get("archive_error") else 0), time.time(), jid))
                row = self._job(uid, jid)
        return self._public_job(uid, row)

    def _public_job(self, uid: str, row: dict) -> dict:
        snapshot = self._contract(uid, row["contract_id"])["snapshot"]
        result = row["result"].copy()
        # Never expose provider signed URLs in audit or prompt history. Return short-lived service URLs.
        result.pop("video_url", None)
        result.pop("last_frame_url", None)
        for asset_key, url_key in (("video_asset_id", "video_url"), ("last_frame_asset_id", "last_frame_url")):
            if result.get(asset_key):
                try:
                    result[url_key] = self.assets.media_url(self.assets.get(uid, result[asset_key]))
                except DirectorError:
                    result["archive_error"] = "Saved media is no longer available; retention or account deletion may have removed it."
        tokens = (result.get("usage") or {}).get("completion_tokens")
        if tokens is not None:
            result["list_rate_usage_usd"] = round(tokens / 1e6 * snapshot["estimate"]["usd_per_million_tokens"], 6)
            result["usage_notice"] = "Token-based list-rate calculation, not an invoice. Actual account pricing may differ."
        return {"generation_id": row["id"], "contract_id": row["contract_id"], "title": snapshot["plan"]["title"], "status": row["status"], "provider_task_id": row["provider_task_id"], "created_at": row["created_at"], "updated_at": row["updated_at"], "result": result, "review_url": self.settings.base_url + "/?generation=" + row["id"]}

    def list(self, uid: str, limit: int = 20) -> list[dict]:
        return [self.get(uid, row["id"], poll=False) for row in self.db.all("SELECT id FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (uid, limit))]

    def cancel(self, uid: str, jid: str, acknowledge: bool) -> dict:
        if acknowledge is not True:
            raise DirectorError("CANCEL_ACK_REQUIRED", "Cancellation can race with completion and delete the provider record. Acknowledge that risk first.")
        row = self._job(uid, jid)
        if not row["provider_task_id"]:
            raise DirectorError("CANCEL_UNAVAILABLE", "There is no confirmed provider task ID. Check its console.", 409)
        latest = self.provider.get(self.auth.provider_key(uid), row["provider_task_id"])
        if latest["status"] != "queued":
            raise DirectorError("CANCEL_UNAVAILABLE", "Only queued tasks can be cancelled. Running tasks cannot be stopped; completed records are not deleted by this tool.", 409)
        self.provider.cancel_or_delete(self.auth.provider_key(uid), row["provider_task_id"])
        # Provider DELETE is also record deletion; do not manufacture a cancellation result.
        try:
            result = self.provider.get(self.auth.provider_key(uid), row["provider_task_id"])
            status = result["status"]
        except DirectorError:
            status, result = "cancel_outcome_unknown", {"error": "The cancellation request returned successfully, but the task status could not be confirmed. It may have completed and its provider record may have been deleted. Check the provider console; no refund is assumed."}
        self.db.execute("UPDATE jobs SET status=?,result=?,updated_at=? WHERE id=?", (status, dumps(result), time.time(), jid))
        self.db.audit(uid, "generation.cancel_requested", jid)
        return self.get(uid, jid, poll=False)

    def reconcile(self, uid: str, jid: str, task_id: str) -> dict:
        row = self._job(uid, jid)
        if row["status"] not in ("submission_unknown", "submitting") or row["provider_task_id"]:
            raise DirectorError("RECONCILE_UNAVAILABLE", "Only an unbound uncertain submission can be reconciled.", 409)
        result = self.provider.get(self.auth.provider_key(uid), task_id)
        snapshot = self._contract(uid, row["contract_id"])["snapshot"]
        if result.get("model") != snapshot["model_card"]["model_id"]:
            raise DirectorError("RECONCILE_MODEL_MISMATCH", "That provider task does not match the frozen model.")
        # Exact prompt match cannot be proven by GET; operator must check original console timestamps/content.
        self.db.execute("UPDATE jobs SET provider_task_id=?,status=?,result=?,updated_at=? WHERE id=?", (task_id, result["status"], dumps(result), time.time(), jid))
        self.db.audit(uid, "generation.operator_reconciled", jid, {"provider_task_id": task_id})
        return self.get(uid, jid)
