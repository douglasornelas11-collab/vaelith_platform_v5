from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx
from fastapi import Cookie, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

BUCKET = os.getenv("SUPABASE_BUCKET", "vaelith-project-files")
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "250"))
ALLOWED = {".pdf", ".dwg", ".dxf", ".ifc", ".rvt", ".xlsx", ".csv", ".mpp", ".doc", ".docx", ".png", ".jpg", ".jpeg"}


def _credential_status() -> tuple[bool, str]:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        return False, "Supabase Storage ainda não está conectado às variáveis de produção."
    if key.startswith("sb_secret_"):
        return True, "secret"
    if key.startswith("sb_publishable_"):
        return False, "A variável SUPABASE_SERVICE_ROLE_KEY contém uma chave pública. Use uma Secret key do backend."
    if key.startswith("eyJ") and key.count(".") == 2:
        try:
            payload = key.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            role = json.loads(base64.urlsafe_b64decode(payload.encode()).decode()).get("role")
        except Exception:
            role = None
        if role == "service_role":
            return True, "legacy-service-role"
        return False, f"A chave configurada possui role '{role or 'desconhecida'}'. Use a service_role, não a anon key."
    return False, "A chave administrativa do Supabase não tem formato reconhecido."


def configured() -> bool:
    return _credential_status()[0]


def _server():
    import server
    return server


def _storage_headers() -> dict[str, str]:
    valid, key_kind = _credential_status()
    if not valid:
        raise HTTPException(503, key_kind)
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip()
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key_kind == "legacy-service-role":
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _storage_request(method: str, endpoint: str, payload: dict | None = None) -> dict | list:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/storage/v1" + endpoint
    try:
        with httpx.Client(timeout=30.0, trust_env=False, follow_redirects=False) as client:
            response = client.request(method, url, headers=_storage_headers(), json=payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Falha de comunicação com o Supabase Storage: {type(exc).__name__}: {str(exc)[:180]}")
    if response.status_code >= 400:
        detail = response.text[:300]
        if "row-level security" in detail.lower():
            raise HTTPException(503, "O Supabase recusou a operação por política RLS. Confirme que SUPABASE_SERVICE_ROLE_KEY contém uma Secret key administrativa válida.")
        raise HTTPException(502, f"Supabase Storage respondeu HTTP {response.status_code}: {detail}")
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


def _signed_value(data, *keys):
    if not isinstance(data, dict):
        return None
    for key in keys:
        if data.get(key):
            return data[key]
    return None


def _absolute_storage_url(value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if not value.startswith("/"):
        value = "/" + value
    if value.startswith("/storage/v1/"):
        return os.environ["SUPABASE_URL"].rstrip("/") + value
    return os.environ["SUPABASE_URL"].rstrip("/") + "/storage/v1" + value


def install(app: FastAPI) -> None:
    @app.get("/api/storage/status")
    def storage_status():
        valid, detail = _credential_status()
        return {
            "configured": valid,
            "provider": "supabase" if valid else "temporary",
            "bucket": BUCKET if valid else None,
            "maxFileMb": MAX_FILE_MB if valid else 4,
            "directUpload": valid,
            "detail": None if valid else detail,
        }

    @app.get("/api/health")
    def persistent_health():
        valid, _ = _credential_status()
        return {
            "ok": True,
            "version": "7.4-storage-rest-secret-key",
            "environment": "vercel" if os.getenv("VERCEL") else "local",
            "maxUploadMb": MAX_FILE_MB if valid else 4,
            "storage": "supabase-private" if valid else "temporary",
            "database": "postgresql" if any(os.getenv(n, "").startswith(("postgres://", "postgresql://")) for n in ("VAELITH_DB_URL", "STORAGE_URL", "DATABASE_URL", "POSTGRES_URL", "NEON_DATABASE_URL")) else "sqlite-temporary",
            "engine": "document-interface-and-budget-coordination-v1",
            "geometricEngine": "not-yet-implemented",
        }

    @app.post("/api/projects/{pid}/uploads/sign")
    async def sign_upload(pid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        srv = _server()
        user = srv.require_user(vaelith_session)
        srv.require_project(pid, user["id"])
        body = srv.safe_json(await request.body())
        filename = Path(str(body.get("name", "arquivo"))).name
        size = int(body.get("size") or 0)
        mime = str(body.get("mime") or mimetypes.guess_type(filename)[0] or "application/octet-stream")
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED:
            raise HTTPException(415, f"{filename}: formato ainda não aceito.")
        if size <= 0:
            raise HTTPException(400, "Tamanho de arquivo inválido.")
        if size > MAX_FILE_MB * 1024 * 1024:
            raise HTTPException(413, f"{filename}: limite de {MAX_FILE_MB} MB por arquivo.")
        fid = uuid4().hex
        object_path = f"projects/{user['id']}/{pid}/{fid}{ext}"
        encoded = quote(object_path, safe="/")
        result = _storage_request("POST", f"/object/upload/sign/{quote(BUCKET, safe='')}/{encoded}", {"upsert": False})
        signed_url = _signed_value(result, "signedURL", "signedUrl", "signed_url", "url")
        token = _signed_value(result, "token")
        path = _signed_value(result, "path") or object_path
        if not signed_url:
            raise HTTPException(502, "O Supabase não retornou uma URL assinada de upload.")
        return {"fileId": fid, "path": path, "signedUrl": _absolute_storage_url(signed_url), "token": token, "bucket": BUCKET, "mime": mime, "maxFileMb": MAX_FILE_MB}

    @app.post("/api/projects/{pid}/uploads/confirm")
    async def confirm_upload(pid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        srv = _server()
        user = srv.require_user(vaelith_session)
        srv.require_project(pid, user["id"])
        body = srv.safe_json(await request.body())
        fid = str(body.get("fileId", "")).strip()
        filename = Path(str(body.get("name", "arquivo"))).name
        object_path = str(body.get("path", "")).strip()
        size = int(body.get("size") or 0)
        mime = str(body.get("mime") or mimetypes.guess_type(filename)[0] or "application/octet-stream")
        ext = Path(filename).suffix.lower()
        expected_prefix = f"projects/{user['id']}/{pid}/"
        if not fid or not object_path.startswith(expected_prefix) or Path(object_path).stem != fid:
            raise HTTPException(400, "Confirmação de arquivo inválida.")
        folder, object_name = object_path.rsplit("/", 1)
        objects = _storage_request("POST", f"/object/list/{quote(BUCKET, safe='')}", {"prefix": folder, "search": object_name, "limit": 10, "offset": 0})
        found = any(isinstance(item, dict) and item.get("name") == object_name for item in (objects if isinstance(objects, list) else []))
        if not found:
            raise HTTPException(409, "O upload terminou no navegador, mas o arquivo não foi encontrado no armazenamento.")
        code, discipline = srv.infer_discipline(filename)
        revision = srv.infer_revision(filename)
        with srv.conn() as c:
            existing = c.execute("SELECT id FROM files WHERE id=? AND project_id=?", (fid, pid)).fetchone()
            if not existing:
                c.execute("INSERT INTO files(id,project_id,name,ext,size,discipline,revision,uploaded,discipline_code,checksum,storage_path,mime) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (fid, pid, filename, ext, size, discipline, revision, srv.now(), code, "", f"supabase://{BUCKET}/{object_path}", mime))
        return {"id": fid, "name": filename, "discipline": discipline, "discipline_code": code, "revision": revision, "persisted": True}

    @app.get("/api/projects/{pid}/files/{fid}/download")
    def persistent_download(pid: str, fid: str, vaelith_session: str | None = Cookie(None)):
        srv = _server()
        user = srv.require_user(vaelith_session)
        srv.require_project(pid, user["id"])
        with srv.conn() as c:
            row = c.execute("SELECT * FROM files WHERE id=? AND project_id=?", (fid, pid)).fetchone()
        if not row:
            raise HTTPException(404, "Arquivo não encontrado.")
        storage_path = row["storage_path"] or ""
        prefix = f"supabase://{BUCKET}/"
        if not storage_path.startswith(prefix):
            raise HTTPException(404, "Arquivo físico antigo não está disponível no armazenamento permanente.")
        object_path = storage_path[len(prefix):]
        encoded = quote(object_path, safe="/")
        data = _storage_request("POST", f"/object/sign/{quote(BUCKET, safe='')}/{encoded}", {"expiresIn": 300, "download": row["name"]})
        signed_url = _signed_value(data, "signedURL", "signedUrl", "signed_url", "url")
        if not signed_url:
            raise HTTPException(502, "O Supabase não retornou uma URL de download.")
        return RedirectResponse(_absolute_storage_url(signed_url), status_code=307)
