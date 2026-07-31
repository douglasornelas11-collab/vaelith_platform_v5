from __future__ import annotations

import hashlib
import hmac
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Query, Request

TOKEN_SHA256 = "0b34786262c958c9f7c3c761ed56f64be7e477dd4c58c6ed2ec77063ac391b58"
INSTANCE_ID = uuid4().hex[:12]


def _authorize(token: str) -> None:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(digest, TOKEN_SHA256):
        raise HTTPException(404, "Not found")


def _storage_headers(content_type: str = "application/json") -> dict[str, str]:
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    headers = {"apikey": key, "Content-Type": content_type}
    if key.startswith("eyJ") and key.count(".") == 2:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _signed_value(data: object) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("signedURL", "signedUrl", "signed_url", "url"):
        value = data.get(key)
        if value:
            return str(value)
    return None


def install(app: FastAPI) -> None:
    if getattr(app.state, "_vaelith_deep_probe_v1", False):
        return
    app.state._vaelith_deep_probe_v1 = True

    @app.get("/api/internal/probe-read-v1", include_in_schema=False)
    def probe_read_v1(
        token: str = Query(...),
        run_id: str = Query(...),
        delay_ms: int = Query(500, ge=0, le=3000),
    ):
        _authorize(token)
        if delay_ms:
            time.sleep(delay_ms / 1000)
        import server

        found = False
        error = None
        try:
            with server.conn() as connection:
                row = connection.execute(
                    "SELECT payload FROM serverless_persistence_probe_v1 WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                found = bool(row and row["payload"] == "cross-instance-ok")
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
        return {
            "found": found,
            "instanceId": INSTANCE_ID,
            "error": error,
        }

    @app.get("/api/internal/deep-probe-v1", include_in_schema=False)
    def deep_probe_v1(
        request: Request,
        token: str = Query(...),
        fanout: int = Query(40, ge=4, le=64),
        delay_ms: int = Query(700, ge=0, le=3000),
    ):
        _authorize(token)
        run_id = uuid4().hex
        started = time.perf_counter()
        import server

        # Write a sentinel using the same database path used by projects,
        # documents, analyses and operational occurrences.
        local_write_ok = False
        local_write_error = None
        try:
            with server.conn() as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS serverless_persistence_probe_v1("
                    "run_id TEXT PRIMARY KEY,payload TEXT NOT NULL,created TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT OR REPLACE INTO serverless_persistence_probe_v1(run_id,payload,created) "
                    "VALUES(?,?,?)",
                    (run_id, "cross-instance-ok", str(time.time())),
                )
                row = connection.execute(
                    "SELECT payload FROM serverless_persistence_probe_v1 WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                local_write_ok = bool(row and row["payload"] == "cross-instance-ok")
        except Exception as exc:
            local_write_error = f"{type(exc).__name__}: {str(exc)[:240]}"

        # Force concurrent external requests so Vercel may distribute them to
        # different warm/cold serverless instances.
        base_url = str(request.base_url).rstrip("/")
        reads: list[dict] = []

        def read_once(index: int) -> dict:
            try:
                with httpx.Client(timeout=25.0, trust_env=False, follow_redirects=True) as client:
                    response = client.get(
                        base_url + "/api/internal/probe-read-v1",
                        params={
                            "token": token,
                            "run_id": run_id,
                            "delay_ms": delay_ms,
                            "nonce": f"{run_id}-{index}",
                        },
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
                    )
                data = response.json() if response.status_code == 200 else {}
                return {
                    "status": response.status_code,
                    "found": bool(data.get("found")),
                    "instanceId": data.get("instanceId"),
                    "error": data.get("error"),
                }
            except Exception as exc:
                return {
                    "status": 0,
                    "found": False,
                    "instanceId": None,
                    "error": f"{type(exc).__name__}: {str(exc)[:180]}",
                }

        with ThreadPoolExecutor(max_workers=min(fanout, 32)) as executor:
            futures = [executor.submit(read_once, index) for index in range(fanout)]
            for future in as_completed(futures):
                reads.append(future.result())

        instances = sorted({item["instanceId"] for item in reads if item.get("instanceId")})
        found_count = sum(1 for item in reads if item.get("found"))
        cross_instance_conclusive = len(instances) > 1
        cross_instance_persistent = bool(reads and found_count == len(reads))

        try:
            with server.conn() as connection:
                connection.execute(
                    "DELETE FROM serverless_persistence_probe_v1 WHERE run_id=?", (run_id,)
                )
        except Exception:
            pass

        # Real Supabase object lifecycle: upload -> sign -> download -> delete.
        storage = {
            "ok": False,
            "upload": None,
            "signedRead": None,
            "contentMatch": False,
            "delete": None,
            "cleanupAttempted": False,
            "error": None,
        }
        supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        bucket = os.getenv("SUPABASE_BUCKET", "vaelith-project-files").strip()
        object_path = f"stress-tests/{run_id}.txt"
        encoded_path = quote(object_path, safe="/")
        payload = f"VAELITH-DEEP-PROBE:{run_id}".encode("utf-8")
        try:
            with httpx.Client(timeout=30.0, trust_env=False, follow_redirects=True) as client:
                upload_response = client.post(
                    f"{supabase_url}/storage/v1/object/{quote(bucket, safe='')}/{encoded_path}",
                    content=payload,
                    headers={**_storage_headers("text/plain"), "x-upsert": "false"},
                )
                storage["upload"] = upload_response.status_code
                if upload_response.status_code >= 400:
                    raise RuntimeError(f"upload HTTP {upload_response.status_code}: {upload_response.text[:180]}")

                sign_response = client.post(
                    f"{supabase_url}/storage/v1/object/sign/{quote(bucket, safe='')}/{encoded_path}",
                    json={"expiresIn": 120},
                    headers=_storage_headers(),
                )
                storage["signedRead"] = sign_response.status_code
                if sign_response.status_code >= 400:
                    raise RuntimeError(f"sign HTTP {sign_response.status_code}: {sign_response.text[:180]}")
                signed = _signed_value(sign_response.json())
                if not signed:
                    raise RuntimeError("Supabase não retornou URL assinada.")
                signed_url = signed if signed.startswith("http") else supabase_url + (
                    signed if signed.startswith("/storage/v1/") else "/storage/v1" + (signed if signed.startswith("/") else "/" + signed)
                )
                download_response = client.get(signed_url)
                storage["download"] = download_response.status_code
                storage["contentMatch"] = download_response.content == payload
                if download_response.status_code >= 400 or not storage["contentMatch"]:
                    raise RuntimeError(
                        f"download HTTP {download_response.status_code}; conteúdo íntegro={storage['contentMatch']}"
                    )
                storage["ok"] = True
        except Exception as exc:
            storage["error"] = f"{type(exc).__name__}: {str(exc)[:280]}"
        finally:
            storage["cleanupAttempted"] = True
            try:
                with httpx.Client(timeout=25.0, trust_env=False, follow_redirects=False) as client:
                    delete_response = client.delete(
                        f"{supabase_url}/storage/v1/object/{quote(bucket, safe='')}/{encoded_path}",
                        headers=_storage_headers(),
                    )
                storage["delete"] = delete_response.status_code
            except Exception as exc:
                storage["deleteError"] = f"{type(exc).__name__}: {str(exc)[:180]}"

        # Validate route uniqueness by method + path, not path alone.
        signatures: list[str] = []
        for route in app.routes:
            path = getattr(route, "path", None)
            methods = sorted(getattr(route, "methods", None) or [])
            if path:
                for method in methods or ["-"]:
                    signatures.append(f"{method} {path}")
        duplicate_signatures = sorted({sig for sig in signatures if signatures.count(sig) > 1})

        return {
            "ok": bool(
                local_write_ok
                and storage["ok"]
                and not duplicate_signatures
                and (cross_instance_persistent if cross_instance_conclusive else True)
            ),
            "runId": run_id,
            "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
            "routeIntegrity": {
                "ok": not duplicate_signatures,
                "duplicateMethodPaths": duplicate_signatures,
                "registeredSignatures": len(signatures),
            },
            "serverlessPersistence": {
                "localWriteOk": local_write_ok,
                "localWriteError": local_write_error,
                "requests": len(reads),
                "successfulResponses": sum(1 for item in reads if item["status"] == 200),
                "found": found_count,
                "notFound": len(reads) - found_count,
                "distinctInstances": len(instances),
                "instanceIds": instances,
                "conclusive": cross_instance_conclusive,
                "persistentAcrossObservedInstances": cross_instance_persistent,
                "sampleErrors": [item["error"] for item in reads if item.get("error")][:5],
            },
            "supabaseObjectLifecycle": storage,
            "cleanup": {
                "localSentinelDeleted": True,
                "supabaseDeleteAttempted": storage["cleanupAttempted"],
                "userDataModified": False,
            },
        }
