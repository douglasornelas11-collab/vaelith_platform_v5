from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from fastapi import FastAPI


def install(app: FastAPI) -> None:
    @app.get("/api/storage/self-test")
    def storage_self_test():
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        bucket = os.getenv("SUPABASE_BUCKET", "vaelith-project-files").strip()
        result = {
            "ok": False,
            "testedAt": datetime.now(timezone.utc).isoformat(),
            "variables": {
                "SUPABASE_URL": bool(url),
                "SUPABASE_SERVICE_ROLE_KEY": bool(key),
                "SUPABASE_BUCKET": bool(bucket),
            },
            "bucket": bucket if url and key else None,
            "connection": "not-tested",
            "detail": None,
        }
        if not url or not key:
            result["connection"] = "blocked"
            result["detail"] = "As credenciais do Supabase não estão disponíveis no ambiente de produção."
            return result

        endpoint = f"{url}/storage/v1/object/list/{bucket}"
        payload = json.dumps({"prefix": "", "limit": 1, "offset": 0}).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "apikey": key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = json.loads(response.read().decode("utf-8") or "[]")
            result["ok"] = True
            result["connection"] = "connected"
            result["detail"] = "Conexão autenticada e bucket acessível."
            result["sampleCount"] = len(body) if isinstance(body, list) else 0
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            result["connection"] = "failed"
            result["detail"] = f"HTTP {exc.code}: {detail[:240]}"
        except Exception as exc:
            result["connection"] = "failed"
            result["detail"] = str(exc)[:300]
        return result
