from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

BUCKET = os.getenv("SUPABASE_BUCKET", "vaelith-project-files")
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "250"))
ALLOWED = {".pdf", ".dwg", ".dxf", ".ifc", ".rvt", ".xlsx", ".csv", ".mpp", ".doc", ".docx", ".png", ".jpg", ".jpeg"}


def configured() -> bool:
    return bool(os.getenv("SUPABASE_URL", "").strip() and os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip())


def client():
    if not configured():
        raise HTTPException(503, "Supabase Storage ainda não está conectado às variáveis de produção.")
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def _server():
    import server
    return server


def _signed_value(data, *keys):
    if hasattr(data, "model_dump"):
        data = data.model_dump()
    if not isinstance(data, dict):
        data = getattr(data, "data", data)
    if hasattr(data, "model_dump"):
        data = data.model_dump()
    if not isinstance(data, dict):
        return None
    for key in keys:
        if data.get(key):
            return data[key]
    return None


def install(app: FastAPI) -> None:
    @app.get("/api/storage/status")
    def storage_status():
        return {
            "configured": configured(),
            "provider": "supabase" if configured() else "temporary",
            "bucket": BUCKET if configured() else None,
            "maxFileMb": MAX_FILE_MB if configured() else 4,
            "directUpload": configured(),
        }

    @app.get("/api/health")
    def persistent_health():
        return {
            "ok": True,
            "version": "7.2-persistent-storage",
            "environment": "vercel" if os.getenv("VERCEL") else "local",
            "maxUploadMb": MAX_FILE_MB if configured() else 4,
            "storage": "supabase-private" if configured() else "temporary",
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
        try:
            result = client().storage.from_(BUCKET).create_signed_upload_url(object_path)
        except Exception as exc:
            raise HTTPException(502, f"Não foi possível autorizar o upload no Supabase: {exc}")
        signed_url = _signed_value(result, "signed_url", "signedUrl", "url")
        token = _signed_value(result, "token")
        path = _signed_value(result, "path") or object_path
        if not signed_url:
            raise HTTPException(502, "O Supabase não retornou uma URL assinada de upload.")
        if signed_url.startswith("/"):
            signed_url = os.environ["SUPABASE_URL"].rstrip("/") + "/storage/v1" + signed_url
        return {"fileId": fid, "path": path, "signedUrl": signed_url, "token": token, "bucket": BUCKET, "mime": mime, "maxFileMb": MAX_FILE_MB}

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
        try:
            folder, object_name = object_path.rsplit("/", 1)
            objects = client().storage.from_(BUCKET).list(folder, {"search": object_name, "limit": 10})
            found = any((item.get("name") if isinstance(item, dict) else getattr(item, "name", None)) == object_name for item in (objects or []))
        except Exception as exc:
            raise HTTPException(502, f"Não foi possível confirmar o arquivo no Supabase: {exc}")
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
        try:
            data = client().storage.from_(BUCKET).create_signed_url(object_path, 300, {"download": row["name"]})
        except Exception as exc:
            raise HTTPException(502, f"Não foi possível autorizar o download: {exc}")
        signed_url = _signed_value(data, "signed_url", "signedUrl", "url")
        if not signed_url:
            raise HTTPException(502, "O Supabase não retornou uma URL de download.")
        if signed_url.startswith("/"):
            signed_url = os.environ["SUPABASE_URL"].rstrip("/") + "/storage/v1" + signed_url
        return RedirectResponse(signed_url, status_code=307)
