from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI


PLACEHOLDER_HOSTS = {
    "seu-id-do-projeto.supabase.co",
    "seu-projeto.supabase.co",
    "project-ref.supabase.co",
    "xxxxxxxxxxxx.supabase.co",
}


def _key_type(key: str) -> str:
    if key.startswith("sb_secret_"):
        return "secret"
    if key.startswith("sb_publishable_"):
        return "publishable"
    if key.startswith("eyJ") and key.count(".") == 2:
        return "legacy-jwt"
    return "unknown"


def _jwt_role(key: str) -> str | None:
    if not (key.startswith("eyJ") and key.count(".") == 2):
        return None
    try:
        payload = key.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
        role = data.get("role")
        return str(role) if role else None
    except Exception:
        return None


def install(app: FastAPI) -> None:
    @app.get("/api/storage/self-test")
    def storage_self_test():
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        bucket = os.getenv("SUPABASE_BUCKET", "vaelith-project-files").strip()
        parsed = urlparse(url) if url else None
        host = (parsed.hostname or "").lower() if parsed else ""
        key_type = _key_type(key)
        jwt_role = _jwt_role(key)
        result = {
            "ok": False,
            "testedAt": datetime.now(timezone.utc).isoformat(),
            "variables": {
                "SUPABASE_URL": bool(url),
                "SUPABASE_SERVICE_ROLE_KEY": bool(key),
                "SUPABASE_BUCKET": bool(bucket),
            },
            "urlHost": host or None,
            "bucket": bucket if url and key else None,
            "keyType": key_type,
            "jwtRole": jwt_role,
            "connection": "not-tested",
            "detail": None,
        }
        if not url or not key:
            result["connection"] = "blocked"
            result["detail"] = "As credenciais do Supabase não estão disponíveis no ambiente de produção."
            return result
        if parsed.scheme != "https" or not host or not host.endswith(".supabase.co"):
            result["connection"] = "invalid-url"
            result["detail"] = "SUPABASE_URL inválida. Use a Project URL real no formato https://ID-REAL.supabase.co."
            return result
        if host in PLACEHOLDER_HOSTS or any(token in host for token in ("seu-id", "seu-projeto", "xxxxxxxx", "project-ref")):
            result["connection"] = "placeholder-url"
            result["detail"] = "SUPABASE_URL ainda contém um endereço de exemplo. Copie a Project URL real no painel do Supabase."
            return result
        if key_type == "publishable":
            result["connection"] = "invalid-key-type"
            result["detail"] = "Foi configurada uma chave pública. Use uma Secret key (sb_secret_...) ou a service_role legada no backend."
            return result
        if key_type == "legacy-jwt" and jwt_role != "service_role":
            result["connection"] = "invalid-jwt-role"
            result["detail"] = f"A chave JWT configurada possui role '{jwt_role or 'desconhecida'}'. Use a chave service_role, não a anon key."
            return result
        if key_type == "unknown":
            result["connection"] = "invalid-key-format"
            result["detail"] = "A chave não tem formato reconhecido. Use uma Secret key (sb_secret_...) ou a service_role legada em formato JWT."
            return result

        endpoint = f"{url}/storage/v1/object/list/{bucket}"
        payload = {"prefix": "", "limit": 1, "offset": 0}
        headers = {
            "apikey": key,
            "Content-Type": "application/json",
        }
        if key_type == "legacy-jwt":
            headers["Authorization"] = f"Bearer {key}"

        try:
            with httpx.Client(timeout=20.0, trust_env=False, follow_redirects=False) as client:
                response = client.post(endpoint, json=payload, headers=headers)
            if response.status_code >= 400:
                text = response.text[:240]
                result["connection"] = "unauthorized" if response.status_code in {401, 403} or "Unauthorized" in text else "failed"
                result["detail"] = f"HTTP {response.status_code}: {text}"
                return result
            body = response.json()
            result["ok"] = True
            result["connection"] = "connected"
            result["detail"] = "Conexão administrativa autenticada e bucket acessível."
            result["sampleCount"] = len(body) if isinstance(body, list) else 0
        except Exception as exc:
            result["connection"] = "failed"
            result["detail"] = f"{type(exc).__name__}: {str(exc)[:260]}"
        return result
