from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from html import escape
from http.cookies import SimpleCookie
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

TOKEN_PREFIX = "v6."
TOKEN_TTL_SECONDS = 14 * 24 * 60 * 60
PASSWORD_MIN_LENGTH = 12
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
ACTIVATION_TOKEN_SHA256 = "c9eb7f9d74e4596ea921931a024606c2cbf2befb3811ddd65b9782d2812c15d1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _database_url() -> str:
    for name in (
        "VAELITH_DB_URL",
        "DATABASE_URL",
        "POSTGRES_URL",
        "NEON_DATABASE_URL",
        "STORAGE_URL",
    ):
        value = os.getenv(name, "").strip()
        if value.startswith(("postgres://", "postgresql://")):
            return value
    return ""


def _connect(*, autocommit: bool = False):
    url = _database_url()
    if not url:
        raise RuntimeError("Banco PostgreSQL não configurado.")
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(url, autocommit=autocommit, row_factory=dict_row)


def _ensure_schema() -> None:
    with _connect(autocommit=True) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS professional_users(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'owner',
                active BOOLEAN NOT NULL DEFAULT TRUE,
                session_version INTEGER NOT NULL DEFAULT 1,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_login TIMESTAMPTZ NULL
            )
            """
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS professional_users_email_lower_idx "
            "ON professional_users((LOWER(email)))"
        )


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    source = (
        os.getenv("VAELITH_SESSION_SECRET")
        or os.getenv("AUTH_SECRET")
        or _database_url()
        or "vaelith-professional-auth-v6-change-before-commercial-release"
    )
    return hashlib.sha256(source.encode("utf-8")).digest()


def _email_valid(email: str) -> bool:
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)) and len(email) <= 254


def _password_error(password: str) -> str | None:
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"A senha deve ter pelo menos {PASSWORD_MIN_LENGTH} caracteres."
    if not re.search(r"[a-z]", password):
        return "Inclua pelo menos uma letra minúscula."
    if not re.search(r"[A-Z]", password):
        return "Inclua pelo menos uma letra maiúscula."
    if not re.search(r"\d", password):
        return "Inclua pelo menos um número."
    if not re.search(r"[^A-Za-z0-9]", password):
        return "Inclua pelo menos um símbolo."
    return None


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2**14, 8, 1
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32
    )
    return f"scrypt-v1${n}${r}${p}${_b64encode(salt)}${_b64encode(digest)}"


def _verify_password(stored: str, password: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$", 5)
        if scheme != "scrypt-v1":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=32,
        )
        return hmac.compare_digest(_b64encode(digest), expected)
    except (ValueError, TypeError):
        return False


def _activation_valid(token: str) -> bool:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, ACTIVATION_TOKEN_SHA256)


def _owner() -> dict | None:
    _ensure_schema()
    with _connect(autocommit=True) as connection:
        return connection.execute(
            "SELECT * FROM professional_users WHERE role='owner' AND active=TRUE "
            "ORDER BY created_at LIMIT 1"
        ).fetchone()


def _user_by_email(email: str) -> dict | None:
    _ensure_schema()
    with _connect(autocommit=True) as connection:
        return connection.execute(
            "SELECT * FROM professional_users WHERE LOWER(email)=LOWER(%s) LIMIT 1",
            (email.strip(),),
        ).fetchone()


def _user_by_id(user_id: str) -> dict | None:
    _ensure_schema()
    with _connect(autocommit=True) as connection:
        return connection.execute(
            "SELECT * FROM professional_users WHERE id=%s LIMIT 1", (user_id,)
        ).fetchone()


def _sign_user(user: dict, remember: bool = True) -> str:
    ttl = TOKEN_TTL_SECONDS if remember else 12 * 60 * 60
    payload = {
        "uid": user["id"],
        "email": str(user["email"]).lower(),
        "role": user.get("role") or "owner",
        "sv": int(user.get("session_version") or 1),
        "exp": int(time.time() + ttl),
        "v": 6,
    }
    encoded = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = _b64encode(
        hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{TOKEN_PREFIX}{encoded}.{signature}"


def _verify_token(token: str | None) -> dict | None:
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    try:
        encoded, supplied = token[len(TOKEN_PREFIX) :].split(".", 1)
        expected = _b64encode(
            hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied, expected):
            return None
        payload = json.loads(_b64decode(encoded))
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _resolve_user(token: str | None) -> dict | None:
    payload = _verify_token(token)
    if not payload:
        return None
    user = _user_by_id(str(payload.get("uid", "")))
    if not user or not user.get("active"):
        return None
    if str(user["email"]).lower() != str(payload.get("email", "")).lower():
        return None
    if int(user.get("session_version") or 1) != int(payload.get("sv") or 0):
        return None
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user.get("role") or "owner",
    }


def _cookie_header(token: str, remember: bool = True) -> str:
    cookie = SimpleCookie()
    cookie["vaelith_session"] = token
    cookie["vaelith_session"]["path"] = "/"
    cookie["vaelith_session"]["httponly"] = True
    cookie["vaelith_session"]["samesite"] = "Lax"
    if remember:
        cookie["vaelith_session"]["max-age"] = str(TOKEN_TTL_SECONDS)
    if os.getenv("VERCEL") or os.getenv("COOKIE_SECURE") == "1":
        cookie["vaelith_session"]["secure"] = True
    return cookie.output(header="").strip()


def _clear_cookie_header() -> str:
    cookie = SimpleCookie()
    cookie["vaelith_session"] = ""
    cookie["vaelith_session"]["path"] = "/"
    cookie["vaelith_session"]["max-age"] = "0"
    cookie["vaelith_session"]["httponly"] = True
    cookie["vaelith_session"]["samesite"] = "Lax"
    if os.getenv("VERCEL") or os.getenv("COOKIE_SECURE") == "1":
        cookie["vaelith_session"]["secure"] = True
    return cookie.output(header="").strip()


def _authenticate(email: str, password: str) -> tuple[dict | None, str, int]:
    generic = "E-mail ou senha inválidos."
    user = _user_by_email(email)
    if not user or not user.get("active"):
        return None, generic, 401
    locked_until = user.get("locked_until")
    if locked_until and locked_until > _utcnow():
        return None, "Acesso temporariamente bloqueado. Aguarde 15 minutos.", 429
    if not _verify_password(str(user.get("password_hash", "")), password):
        attempts = int(user.get("failed_attempts") or 0) + 1
        lock_until = None
        if attempts >= MAX_FAILED_ATTEMPTS:
            attempts = 0
            lock_until = _utcnow() + timedelta(minutes=LOCK_MINUTES)
        with _connect(autocommit=True) as connection:
            connection.execute(
                "UPDATE professional_users SET failed_attempts=%s,locked_until=%s,updated_at=NOW() "
                "WHERE id=%s",
                (attempts, lock_until, user["id"]),
            )
        return None, generic, 401
    with _connect(autocommit=True) as connection:
        connection.execute(
            "UPDATE professional_users SET failed_attempts=0,locked_until=NULL,last_login=NOW(),"
            "updated_at=NOW() WHERE id=%s",
            (user["id"],),
        )
    return _user_by_id(user["id"]), "", 200


def _activate_owner(name: str, email: str, password: str) -> dict:
    _ensure_schema()
    if _owner():
        raise ValueError("A conta proprietária já foi ativada.")
    user_id = uuid4().hex
    with _connect(autocommit=True) as connection:
        connection.execute(
            "INSERT INTO professional_users(id,name,email,password_hash,role,active,session_version) "
            "VALUES(%s,%s,%s,%s,'owner',TRUE,1)",
            (user_id, name, email, _hash_password(password)),
        )
    user = _user_by_id(user_id)
    if not user:
        raise RuntimeError("A conta não permaneceu gravada no PostgreSQL.")
    return user


def _activation_page(token: str) -> str:
    safe_token = escape(token, quote=True)
    return f"""<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='referrer' content='no-referrer'><title>Ativar conta | VAELITH Platform</title><style>
:root{{--bg:#080b09;--paper:#f3f5f1;--ink:#151915;--muted:#687269;--line:#d7ddd5;--accent:#c8ff3d;--danger:#a43232}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:radial-gradient(circle at 18% 0%,rgba(200,255,61,.13),transparent 30%),var(--bg);font:14px/1.5 'Segoe UI Variable Text','Segoe UI',Arial,sans-serif}}.card{{width:min(620px,100%);padding:38px;border-radius:24px;background:var(--paper);color:var(--ink);box-shadow:0 30px 100px rgba(0,0,0,.44)}}.brand{{color:#536054;font-size:10px;font-weight:900;letter-spacing:.18em}}h1{{margin:12px 0 8px;font-size:38px;line-height:1.05;letter-spacing:-.04em}}p{{color:var(--muted)}}label{{display:block;margin:15px 0;font-size:10px;font-weight:800}}input{{width:100%;height:47px;margin-top:6px;padding:0 12px;border:1px solid var(--line);border-radius:9px;background:#fff;font:inherit}}input:focus{{outline:0;border-color:#91b72c;box-shadow:0 0 0 3px rgba(145,183,44,.14)}}button{{width:100%;height:50px;margin-top:12px;border:0;border-radius:9px;background:#111511;color:#fff;font-weight:850;cursor:pointer}}button:disabled{{opacity:.6}}.msg{{min-height:24px;color:var(--danger);font-size:11px}}.note{{margin-top:18px;padding:13px;border:1px solid var(--line);border-radius:10px;background:#e9ede7;font-size:10px;line-height:1.6}}</style></head><body><main class='card'><div class='brand'>VAELITH PLATFORM · CONTA PROPRIETÁRIA</div><h1>Ative seu acesso profissional</h1><p>Use qualquer e-mail válido e defina sua senha pessoal.</p><form id='form'><label>Nome completo<input id='name' autocomplete='name' value='Douglas Ornelas' required></label><label>E-mail<input id='email' type='email' autocomplete='email' required></label><label>Senha<input id='password' type='password' autocomplete='new-password' required></label><label>Confirmar senha<input id='confirm' type='password' autocomplete='new-password' required></label><button id='submit'>Ativar conta proprietária</button><div class='msg' id='msg'></div></form><div class='note'>A senha deve ter ao menos 12 caracteres, com letra maiúscula, minúscula, número e símbolo. Ela não é enviada ao chat.</div></main><script>
const $=id=>document.getElementById(id);$('form').onsubmit=async e=>{{e.preventDefault();$('submit').disabled=true;$('msg').textContent='Registrando e validando a conta...';try{{const r=await fetch('/api/auth/activate-owner-v3',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{token:'{safe_token}',name:$('name').value.trim(),email:$('email').value.trim(),password:$('password').value,confirm:$('confirm').value}})}});let d={{}};try{{d=await r.json()}}catch{{}}if(!r.ok)throw Error(d.detail||'Não foi possível ativar a conta.');location.replace('/app')}}catch(err){{$('msg').textContent=err.message;$('submit').disabled=false}}}};
</script></body></html>"""


def install(app: FastAPI) -> None:
    if getattr(app.state, "_vaelith_professional_auth_v3", False):
        return
    _ensure_schema()
    app.state._vaelith_professional_auth_v3 = True

    import server

    server.current_user = _resolve_user

    @app.middleware("http")
    async def professional_authentication_v3(request: Request, call_next):
        path = request.url.path
        if path == "/api/auth/login" and request.method == "POST":
            try:
                body = await request.json()
            except Exception:
                return JSONResponse({"detail": "Requisição inválida."}, status_code=400)
            user, error, status = _authenticate(
                str(body.get("email", "")).lower().strip(),
                str(body.get("password", "")),
            )
            if not user:
                return JSONResponse({"detail": error}, status_code=status)
            remember = bool(body.get("remember", True))
            response = Response(status_code=204)
            response.headers["set-cookie"] = _cookie_header(
                _sign_user(user, remember), remember
            )
            response.headers["Cache-Control"] = "no-store"
            return response
        if path == "/api/auth/logout" and request.method == "POST":
            response = Response(status_code=204)
            response.headers["set-cookie"] = _clear_cookie_header()
            response.headers["Cache-Control"] = "no-store"
            return response
        response = await call_next(request)
        if path in {"/login", "/app", "/ativar-conta-v3"} or path.startswith("/api/auth"):
            response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.get("/ativar-conta-v3", include_in_schema=False)
    def activation_page_v3(token: str = ""):
        if not token or not _activation_valid(token):
            return HTMLResponse("Link de ativação inválido.", status_code=404)
        if _owner():
            return HTMLResponse("A conta proprietária já foi ativada. Acesse /login.", status_code=409)
        return HTMLResponse(_activation_page(token))

    @app.post("/api/auth/activate-owner-v3", include_in_schema=False)
    async def activate_owner_v3(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"detail": "Requisição inválida."}, status_code=400)
        token = str(body.get("token", ""))
        name = " ".join(str(body.get("name", "")).split())
        email = str(body.get("email", "")).lower().strip()
        password = str(body.get("password", ""))
        confirm = str(body.get("confirm", ""))
        if not _activation_valid(token):
            return JSONResponse({"detail": "Link de ativação inválido."}, status_code=403)
        if _owner():
            return JSONResponse({"detail": "A conta proprietária já foi ativada."}, status_code=409)
        if len(name) < 3:
            return JSONResponse({"detail": "Informe o nome completo."}, status_code=400)
        if not _email_valid(email):
            return JSONResponse({"detail": "Informe um e-mail válido."}, status_code=400)
        error = _password_error(password)
        if error:
            return JSONResponse({"detail": error}, status_code=400)
        if password != confirm:
            return JSONResponse({"detail": "As senhas não coincidem."}, status_code=400)
        try:
            user = _activate_owner(name, email, password)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409)
        except Exception as exc:
            print(f"VAELITH_OWNER_ACTIVATION_V3_ERROR: {type(exc).__name__}: {exc}")
            return JSONResponse(
                {"detail": "A conta não pôde ser persistida. Tente novamente."},
                status_code=500,
            )
        response = JSONResponse({"ok": True, "name": user["name"]})
        response.headers["set-cookie"] = _cookie_header(_sign_user(user, True), True)
        return response

    @app.get("/api/auth/professional-status-v3", include_in_schema=False)
    def professional_status_v3():
        owner = _owner()
        return {
            "professional": True,
            "ownerConfigured": bool(owner),
            "database": "postgresql",
            "sessionMode": "signed-cookie-v6",
            "passwordHash": "scrypt-v1",
        }

    @app.get("/api/auth/persistence-self-test-v3", include_in_schema=False)
    def persistence_self_test_v3():
        _ensure_schema()
        test_password = "Vaelith-Teste#2026"
        stored = _hash_password(test_password)
        return {
            "ok": _verify_password(stored, test_password),
            "databaseConnected": bool(_database_url()),
            "ownerConfigured": bool(_owner()),
            "table": "professional_users",
        }
