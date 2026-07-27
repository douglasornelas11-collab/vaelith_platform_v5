from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI


def install(app: FastAPI) -> None:
    @app.get("/api/storage/self-test")
    def storage_self_test():
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        bucket = os.getenv("SUPABASE_BUCKET", "vaelith-project-files").strip()
        parsed = urlparse(url) if url else None
        result = {
            "ok": False,
            "testedAt": datetime.now(timezone.utc).isoformat(),
            "variables": {
                "SUPABASE_URL": bool(url),
                "SUPABASE_SERVICE_ROLE_KEY": bool(key),
                "SUPABASE_BUCKET": bool(bucket),
            },
            "urlHost": parsed.hostname if parsed else None,
            "bucket": bucket if url and key else None,
            "connection": "not-tested",
            "detail": None,
        }
        if not url or not key:
            result["connection"] = "blocked"
            result["detail"] = "As credenciais do Supabase não estão disponíveis no ambiente de produção."
            return result
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".supabase.co"):
            result["connection"] = "invalid-url"
            result["detail"] = "SUPABASE_URL inválida. Use a Project URL no formato https://ID.supabase.co."
            return result

        endpoint = f"{url}/storage/v1/object/list/{bucket}"
        payload = {"prefix": "", "limit": 1, "offset": 0}
        headers = {
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "Content-Type": "application/json",
        }
        try:
            # trust_env=False ignores malformed proxy variables inherited by the runtime.
            with httpx.Client(timeout=20.0, trust_env=False, follow_redirects=False) as client:
                response = client.post(endpoint, json=payload, headers=headers)
            if response.status_code >= 400:
                result["connection"] = "failed"
                result["detail"] = f"HTTP {response.status_code}: {response.text[:240]}"
                return result
            body = response.json()
            result["ok"] = True
            result["connection"] = "connected"
            result["detail"] = "Conexão autenticada e bucket acessível."
            result["sampleCount"] = len(body) if isinstance(body, list) else 0
        except Exception as exc:
            result["connection"] = "failed"
            result["detail"] = f"{type(exc).__name__}: {str(exc)[:260]}"
        return result
