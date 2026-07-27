from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import FastAPI


def install(app: FastAPI) -> None:
    @app.get("/api/storage/self-test")
    def storage_self_test():
        url = os.getenv("SUPABASE_URL", "").strip()
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
        try:
            from supabase import create_client
            client = create_client(url.rstrip("/"), key)
            objects = client.storage.from_(bucket).list("", {"limit": 1})
            result["ok"] = True
            result["connection"] = "connected"
            result["detail"] = "Conexão autenticada e bucket acessível."
            result["sampleCount"] = len(objects or [])
        except Exception as exc:
            result["connection"] = "failed"
            result["detail"] = str(exc)[:300]
        return result
