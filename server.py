from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from compatibility_engine import DISCIPLINES, build_analysis, file_checksum, infer_discipline, infer_revision

BASE = Path(__file__).resolve().parent
DATA = Path(os.getenv("VAELITH_DATA_DIR") or ("/tmp/vaelith-v7" if os.getenv("VERCEL") else BASE / "data"))
UPLOADS = DATA / "uploads"
DATA.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)
DB = DATA / "vaelith.db"
APP_VERSION = "7.1-upload-and-budget"
COOKIE_SECURE = bool(os.getenv("VERCEL")) or os.getenv("COOKIE_SECURE") == "1"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "4" if os.getenv("VERCEL") else "100"))
app = FastAPI(title="VAELITH LABS", version=APP_VERSION)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def hash_pw(password: str, salt: str | None = None) -> tuple[str, str]:
    import hashlib
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 180000).hex()
    return salt, digest


def ensure_column(c: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    cols = {row[1] for row in c.execute(f"PRAGMA table_info({table})")}
    if name not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def init_db() -> None:
    with conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT,email TEXT UNIQUE,salt TEXT,pw TEXT);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT,expires TEXT);
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,user_id TEXT,name TEXT,client TEXT,location TEXT,phase TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY,project_id TEXT,name TEXT,ext TEXT,size INTEGER,discipline TEXT,revision TEXT,uploaded TEXT);
            CREATE TABLE IF NOT EXISTS analyses(id TEXT PRIMARY KEY,project_id TEXT,result TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS budget_items(id TEXT PRIMARY KEY,project_id TEXT,file_id TEXT,description TEXT,unit TEXT,quantity REAL,unit_price REAL,total REAL,category TEXT,created TEXT);
        """)
        for definition in ["discipline_code TEXT DEFAULT 'UNK'", "checksum TEXT DEFAULT ''", "storage_path TEXT DEFAULT ''", "mime TEXT DEFAULT 'application/octet-stream'"]:
            ensure_column(c, "files", definition)
        user = c.execute("SELECT * FROM users WHERE email=?", ("demo@vaelithlabs.com.br",)).fetchone()
        if not user:
            uid = uuid4().hex
            salt, pw = hash_pw("vaelith")
            c.execute("INSERT INTO users VALUES(?,?,?,?,?)", (uid, "Douglas Demo", "demo@vaelithlabs.com.br", salt, pw))
        else:
            uid = user["id"]
        project = c.execute("SELECT * FROM projects WHERE user_id=?", (uid,)).fetchone()
        if not project:
            pid = uuid4().hex
            c.execute("INSERT INTO projects VALUES(?,?,?,?,?,?,?)", (pid, uid, "Empreendimento demonstrativo", "Cliente exemplo", "Betim/MG", "Pré-obra", now()))
            demo = [("ARQ_R02.ifc", "ARQ"), ("EST_R03.ifc", "EST"), ("HID_R01.ifc", "HID"), ("ELE_R01.dwg", "ELE"), ("ORC_R01.xlsx", "ORC"), ("CRONO_R01.mpp", "PLA"), ("MEMORIAL_R01.pdf", "ESC")]
            for filename, code in demo:
                ext = Path(filename).suffix.lower()
                c.execute("INSERT INTO files(id,project_id,name,ext,size,discipline,revision,uploaded,discipline_code,checksum,storage_path,mime) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (uuid4().hex, pid, filename, ext, 1024, DISCIPLINES[code]["name"], infer_revision(filename), now(), code, "", "", mimetypes.guess_type(filename)[0] or "application/octet-stream"))


init_db()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    return response


def current_user(token: str | None):
    if not token:
        return None
    with conn() as c:
        row = c.execute("SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=? AND expires>?", (token, now())).fetchone()
    return dict(row) if row else None


def require_user(token: str | None):
    user = current_user(token)
    if not user:
        raise HTTPException(401, "Sessão expirada. Entre novamente.")
    return user


def owns(project_id: str, user_id: str):
    with conn() as c:
        return c.execute("SELECT * FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()


def require_project(project_id: str, user_id: str):
    project = owns(project_id, user_id)
    if not project:
        raise HTTPException(404, "Empreendimento não encontrado.")
    return project


def safe_json(body: bytes) -> dict:
    try:
        parsed = json.loads(body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, "JSON inválido.")
    if not isinstance(parsed, dict):
        raise HTTPException(400, "O corpo da requisição deve ser um objeto JSON.")
    return parsed


def _number(value):
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _budget_category(description: str) -> str:
    text = description.upper()
    rules = [
        ("ARQ", ["ALVENARIA", "REVESTIMENTO", "PISO", "FORRO", "PINTURA", "ESQUADRIA", "ARQUIT"]),
        ("EST", ["CONCRETO", "ARMAÇÃO", "ACO", "FUNDAÇÃO", "ESTRUT"]),
        ("HID", ["HIDR", "TUBO", "ÁGUA", "AGUA", "BOMBA"]),
        ("SAN", ["ESGOTO", "SANIT", "DRENO"]),
        ("ELE", ["ELÉTR", "ELETR", "CABO", "QUADRO", "LUMIN"]),
        ("HVAC", ["AR COND", "CLIMAT", "DUTO", "HVAC", "CHILLER"]),
        ("PCI", ["INCÊND", "INCEND", "SPRINKLER", "HIDRANTE"]),
    ]
    for code, words in rules:
        if any(word in text for word in words):
            return code
    return "OUT"


def parse_budget(raw: bytes, ext: str) -> list[dict]:
    if ext == ".csv":
        text = raw.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;") if text.strip() else csv.excel
        except csv.Error:
            dialect = csv.excel
        data = list(csv.reader(io.StringIO(text), dialect))
    elif ext == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError:
            return []
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        data = [list(row) for row in workbook.active.iter_rows(values_only=True)]
    else:
        return []
    if not data:
        return []
    header = [str(value or "").strip().lower() for value in data[0]]
    def column(names, default=None):
        for name in names:
            for index, value in enumerate(header):
                if name in value:
                    return index
        return default
    description_index = column(["descr", "serviço", "servico", "item"], 0)
    unit_index = column(["unid"], 1)
    quantity_index = column(["quant"], 2)
    unit_price_index = column(["preço unit", "preco unit", "valor unit"], 3)
    total_index = column(["total", "valor total"], 4)
    rows = []
    for row in data[1:]:
        if not row or description_index is None or description_index >= len(row):
            continue
        description = str(row[description_index] or "").strip()
        if not description:
            continue
        quantity = _number(row[quantity_index] if quantity_index is not None and quantity_index < len(row) else 0)
        unit_price = _number(row[unit_price_index] if unit_price_index is not None and unit_price_index < len(row) else 0)
        total = _number(row[total_index] if total_index is not None and total_index < len(row) else quantity * unit_price) or quantity * unit_price
        rows.append({"description": description, "unit": str(row[unit_index] or "") if unit_index is not None and unit_index < len(row) else "", "quantity": quantity, "unit_price": unit_price, "total": total, "category": _budget_category(description)})
    return rows[:10000]


def files_for(project_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM files WHERE project_id=? ORDER BY uploaded DESC", (project_id,)).fetchall()
    return [dict(row) for row in rows]


@app.get("/")
def home(request: Request):
    if request.headers.get("host", "").split(":")[0].lower().startswith("app."):
        return RedirectResponse("/login", 307)
    return FileResponse(BASE / "index.html")


@app.get("/login")
def login_page():
    return FileResponse(BASE / "login.html")


@app.get("/app")
def app_page(vaelith_session: str | None = Cookie(None)):
    if not current_user(vaelith_session):
        return RedirectResponse("/login", 307)
    return FileResponse(BASE / "app.html")


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION, "environment": "vercel" if os.getenv("VERCEL") else "local", "maxUploadMb": MAX_UPLOAD_MB, "storage": "temporary" if os.getenv("VERCEL") else "local", "engine": "document-interface-and-budget-coordination-v1"}


@app.get("/api/catalog/disciplines")
def discipline_catalog(vaelith_session: str | None = Cookie(None)):
    require_user(vaelith_session)
    return [{"code": code, "name": cfg["name"], "core": cfg["core"]} for code, cfg in DISCIPLINES.items()]


@app.post("/api/auth/login")
async def login(request: Request):
    body = safe_json(await request.body())
    email = str(body.get("email", "")).lower().strip()
    password = str(body.get("password", ""))
    with conn() as c:
        user = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user:
        raise HTTPException(401, "E-mail ou senha inválidos.")
    _, digest = hash_pw(password, user["salt"])
    if not secrets.compare_digest(digest, user["pw"]):
        raise HTTPException(401, "E-mail ou senha inválidos.")
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    with conn() as c:
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (token, user["id"], expires))
    response = Response(status_code=204)
    response.set_cookie("vaelith_session", token, httponly=True, secure=COOKIE_SECURE, samesite="lax", max_age=1209600, path="/")
    return response


@app.post("/api/auth/logout")
def logout(vaelith_session: str | None = Cookie(None)):
    if vaelith_session:
        with conn() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (vaelith_session,))
    response = Response(status_code=204)
    response.delete_cookie("vaelith_session", path="/")
    return response


@app.get("/api/me")
def me(vaelith_session: str | None = Cookie(None)):
    user = require_user(vaelith_session)
    return {"id": user["id"], "name": user["name"], "email": user["email"]}


@app.get("/api/projects")
def projects(vaelith_session: str | None = Cookie(None)):
    user = require_user(vaelith_session)
    with conn() as c:
        rows = c.execute("SELECT p.*,COUNT(f.id) file_count FROM projects p LEFT JOIN files f ON f.project_id=p.id WHERE p.user_id=? GROUP BY p.id ORDER BY p.created DESC", (user["id"],)).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/projects")
async def create_project(request: Request, vaelith_session: str | None = Cookie(None)):
    user = require_user(vaelith_session)
    body = safe_json(await request.body())
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "Informe o nome do empreendimento.")
    pid = uuid4().hex
    with conn() as c:
        c.execute("INSERT INTO projects VALUES(?,?,?,?,?,?,?)", (pid, user["id"], name, str(body.get("client", "")).strip(), str(body.get("location", "")).strip(), str(body.get("phase", "Pré-obra")).strip(), now()))
    return {"id": pid, "name": name}


@app.get("/api/projects/{pid}/files")
def list_files(pid: str, vaelith_session: str | None = Cookie(None)):
    user = require_user(vaelith_session)
    require_project(pid, user["id"])
    return files_for(pid)


@app.post("/api/projects/{pid}/upload")
async def upload(pid: str, uploads: list[UploadFile] = File(...), vaelith_session: str | None = Cookie(None)):
    user = require_user(vaelith_session)
    require_project(pid, user["id"])
    project_dir = UPLOADS / pid
    project_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for upload_file in uploads:
        raw = await upload_file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
        filename = Path(upload_file.filename or "arquivo").name
        if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"{filename}: limite atual de {MAX_UPLOAD_MB} MB por arquivo.")
        ext = Path(filename).suffix.lower()
        if ext not in {".pdf", ".dwg", ".dxf", ".ifc", ".rvt", ".xlsx", ".csv", ".mpp", ".doc", ".docx", ".png", ".jpg", ".jpeg"}:
            raise HTTPException(415, f"{filename}: formato ainda não aceito.")
        code, discipline = infer_discipline(filename)
        revision = infer_revision(filename)
        fid = uuid4().hex
        checksum = file_checksum(raw)
        stored = project_dir / f"{fid}{ext}"
        stored.write_bytes(raw)
        mime = upload_file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        with conn() as c:
            c.execute("INSERT INTO files(id,project_id,name,ext,size,discipline,revision,uploaded,discipline_code,checksum,storage_path,mime) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (fid, pid, filename, ext, len(raw), discipline, revision, now(), code, checksum, str(stored), mime))
            if ext in {".xlsx", ".csv"}:
                for item in parse_budget(raw, ext):
                    c.execute("INSERT INTO budget_items VALUES(?,?,?,?,?,?,?,?,?,?)", (uuid4().hex, pid, fid, item["description"], item["unit"], item["quantity"], item["unit_price"], item["total"], item["category"], now()))
        saved.append({"id": fid, "name": filename, "discipline": discipline, "discipline_code": code, "revision": revision, "checksum": checksum})
    return {"saved": saved}


@app.patch("/api/projects/{pid}/files/{fid}")
async def classify_file(pid: str, fid: str, request: Request, vaelith_session: str | None = Cookie(None)):
    user = require_user(vaelith_session)
    require_project(pid, user["id"])
    body = safe_json(await request.body())
    code = str(body.get("discipline_code", "")).upper()
    if code not in DISCIPLINES:
        raise HTTPException(400, "Disciplina inválida.")
    revision = str(body.get("revision", "Não informada")).strip() or "Não informada"
    with conn() as c:
        row = c.execute("SELECT id FROM files WHERE id=? AND project_id=?", (fid, pid)).fetchone()
        if not row:
            raise HTTPException(404, "Arquivo não encontrado.")
        c.execute("UPDATE files SET discipline_code=?,discipline=?,revision=? WHERE id=?", (code, DISCIPLINES[code]["name"], revision, fid))
    return {"ok": True}


@app.delete("/api/projects/{pid}/files/{fid}")
def delete_file(pid: str, fid: str, vaelith_session: str | None = Cookie(None)):
    user = require_user(vaelith_session)
    require_project(pid, user["id"])
    with conn() as c:
        row = c.execute("SELECT storage_path FROM files WHERE id=? AND project_id=?", (fid, pid)).fetchone()
        if not row:
            raise HTTPException(404, "Arquivo não encontrado.")
        c.execute("DELETE FROM files WHERE id=?", (fid,))
        c.execute("DELETE FROM budget_items WHERE file_id=?", (fid,))
    if row["storage_path"]:
        Path(row["storage_path"]).unlink(missing_ok=True)
    return Response(status_code=204)


@app.get("/api/projects/{pid}/files/{fid}/download")
def download_file(pid: str, fid: str, vaelith_session: str | None = Cookie(None)):
    user = require_user(vaelith_session)
    require_project(pid, user["id"])
    with conn() as c:
        row = c.execute("SELECT * FROM files WHERE id=? AND project_id=?", (fid, pid)).fetchone()
    if not row or not row["storage_path"] or not Path(row["storage_path"]).exists():
        raise HTTPException(404, "Arquivo físico não está disponível nesta instância.")
    return FileResponse(row["storage_path"], media_type=row["mime"], filename=row["name"])


@app.get("/api/projects/{pid}/budget/equalization")
def budget_equalization(pid: str, vaelith_session: str | None = Cookie(None)):
    user = require_user(vaelith_session)
    require_project(pid, user["id"])
    with conn() as c:
        rows = [dict(row) for row in c.execute("SELECT * FROM budget_items WHERE project_id=? ORDER BY description", (pid,)).fetchall()]
    totals = {}
    for item in rows:
        totals[item["category"]] = totals.get(item["category"], 0) + float(item["total"] or 0)
    present = {item.get("discipline_code") for item in files_for(pid)}
    mapping = {"ARQ": "Arquitetura", "EST": "Estrutura", "HID": "Hidráulica", "SAN": "Sanitária", "ELE": "Elétrica", "HVAC": "Climatização", "PCI": "Incêndio", "OUT": "Outros"}
    categories = []
    for code, total in sorted(totals.items(), key=lambda item: -item[1]):
        categories.append({"code": code, "name": mapping.get(code, code), "total": round(total, 2), "projectReceived": code in present, "status": "Coberto" if code in present else "Sem projeto relacionado"})
    return {"items": len(rows), "total": round(sum(float(item["total"] or 0) for item in rows), 2), "categories": categories, "unmatched": sum(1 for item in rows if item["category"] == "OUT")}


@app.post("/api/projects/{pid}/compatibility")
def compatibility(pid: str, vaelith_session: str | None = Cookie(None)):
    user = require_user(vaelith_session)
    require_project(pid, user["id"])
    result = build_analysis(pid, files_for(pid))
    result["id"] = uuid4().hex
    result["createdAt"] = now()
    with conn() as c:
        c.execute("INSERT INTO analyses VALUES(?,?,?,?)", (result["id"], pid, json.dumps(result, ensure_ascii=False), result["createdAt"]))
    return result


@app.get("/api/projects/{pid}/compatibility/latest")
def latest_compatibility(pid: str, vaelith_session: str | None = Cookie(None)):
    user = require_user(vaelith_session)
    require_project(pid, user["id"])
    with conn() as c:
        row = c.execute("SELECT result FROM analyses WHERE project_id=? ORDER BY created DESC LIMIT 1", (pid,)).fetchone()
    if not row:
        return JSONResponse({"detail": "Nenhuma análise executada."}, status_code=404)
    return json.loads(row["result"])


@app.get("/api/projects/{pid}/export")
def export(pid: str, vaelith_session: str | None = Cookie(None)):
    user = require_user(vaelith_session)
    require_project(pid, user["id"])
    with conn() as c:
        row = c.execute("SELECT result FROM analyses WHERE project_id=? ORDER BY created DESC LIMIT 1", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, "Execute a compatibilização primeiro.")
    return JSONResponse(json.loads(row["result"]), headers={"Content-Disposition": f"attachment; filename=vaelith-{pid[:8]}-coordenacao.json"})
