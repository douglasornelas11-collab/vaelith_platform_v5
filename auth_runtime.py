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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response


TOKEN_PREFIX = "v4."
TOKEN_TTL_SECONDS = 14 * 24 * 60 * 60
DEMO_EMAIL = "demo@vaelithlabs.com.br"
ACTIVATION_TOKEN_SHA256 = "cafa73992df2d773ae73851cfb6b3a14026c2b225a08c35240f760ab28c59637"
PASSWORD_MIN_LENGTH = 12
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15


def _secret() -> bytes:
    source = (
        os.getenv("VAELITH_SESSION_SECRET")
        or os.getenv("AUTH_SECRET")
        or os.getenv("VAELITH_DB_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("POSTGRES_URL")
        or "vaelith-owner-auth-fallback-change-before-commercial-release"
    )
    return hashlib.sha256(source.encode("utf-8")).digest()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _utcnow()).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


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


def _hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return "scrypt-v1", f"{_b64encode(salt)}.{_b64encode(derived)}"


def _verify_password(user: dict, password: str) -> bool:
    if user.get("salt") == "scrypt-v1":
        try:
            salt_text, digest_text = str(user.get("pw", "")).split(".", 1)
            derived = hashlib.scrypt(
                password.encode("utf-8"),
                salt=_b64decode(salt_text),
                n=2**14,
                r=8,
                p=1,
                dklen=32,
            )
            return hmac.compare_digest(_b64encode(derived), digest_text)
        except (ValueError, TypeError):
            return False
    try:
        import server

        _, digest = server.hash_pw(password, user.get("salt"))
        return hmac.compare_digest(digest, str(user.get("pw", "")))
    except Exception:
        return False


def _ensure_schema() -> None:
    import server

    definitions = [
        "role TEXT DEFAULT 'member'",
        "active INTEGER DEFAULT 1",
        "created TEXT DEFAULT ''",
        "last_login TEXT DEFAULT ''",
        "password_updated TEXT DEFAULT ''",
        "failed_attempts INTEGER DEFAULT 0",
        "locked_until TEXT DEFAULT ''",
        "session_version INTEGER DEFAULT 1",
    ]
    with server.conn() as connection:
        for definition in definitions:
            server.ensure_column(connection, "users", definition)
        connection.execute("UPDATE users SET role='member' WHERE role IS NULL OR role='' ")
        connection.execute("UPDATE users SET active=1 WHERE active IS NULL")
        connection.execute("UPDATE users SET failed_attempts=0 WHERE failed_attempts IS NULL")
        connection.execute("UPDATE users SET session_version=1 WHERE session_version IS NULL")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_users_email_active ON users(email,active)")


def _row_dict(row) -> dict | None:
    return dict(row) if row else None


def _owner_exists() -> bool:
    import server

    _ensure_schema()
    with server.conn() as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE role='owner' AND active=1 LIMIT 1"
        ).fetchone()
    return bool(row)


def _user_by_email(email: str) -> dict | None:
    import server

    _ensure_schema()
    with server.conn() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE lower(email)=lower(?) LIMIT 1",
            (email.strip(),),
        ).fetchone()
    return _row_dict(row)


def _user_by_id(user_id: str) -> dict | None:
    import server

    _ensure_schema()
    with server.conn() as connection:
        row = connection.execute("SELECT * FROM users WHERE id=? LIMIT 1", (user_id,)).fetchone()
    return _row_dict(row)


def _sign_user(user: dict, remember: bool = True) -> str:
    ttl = TOKEN_TTL_SECONDS if remember else 12 * 60 * 60
    payload = {
        "uid": user["id"],
        "email": str(user["email"]).lower().strip(),
        "role": user.get("role") or "member",
        "sv": int(user.get("session_version") or 1),
        "exp": int(time.time() + ttl),
        "v": 4,
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64encode(hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{TOKEN_PREFIX}{encoded}.{signature}"


def _verify_token(token: str | None) -> dict | None:
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    try:
        encoded, provided = token[len(TOKEN_PREFIX):].split(".", 1)
        expected = _b64encode(hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(provided, expected):
            return None
        payload = json.loads(_b64decode(encoded))
        if not isinstance(payload, dict) or int(payload.get("exp", 0)) <= int(time.time()):
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _resolve_user(token: str | None) -> dict | None:
    payload = _verify_token(token)
    if not payload:
        return None
    user = _user_by_id(str(payload.get("uid", "")))
    if not user or not int(user.get("active") or 0):
        return None
    if str(user.get("email", "")).lower() != str(payload.get("email", "")).lower():
        return None
    if int(user.get("session_version") or 1) != int(payload.get("sv") or 0):
        return None
    return user


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


def _json_error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


def _activation_valid(token: str) -> bool:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, ACTIVATION_TOKEN_SHA256)


def _authenticate(email: str, password: str) -> tuple[dict | None, str | None, int]:
    import server

    normalized = email.lower().strip()
    user = _user_by_email(normalized)
    generic = "E-mail ou senha inválidos."
    if not user or normalized == DEMO_EMAIL or not int(user.get("active") or 0):
        return None, generic, 401

    locked_until = _parse_iso(user.get("locked_until"))
    if locked_until and locked_until > _utcnow():
        return None, "Acesso temporariamente bloqueado. Tente novamente em alguns minutos.", 429

    if not _verify_password(user, password):
        attempts = int(user.get("failed_attempts") or 0) + 1
        lock_value = ""
        if attempts >= MAX_FAILED_ATTEMPTS:
            lock_value = _iso(_utcnow() + timedelta(minutes=LOCK_MINUTES))
            attempts = 0
        with server.conn() as connection:
            connection.execute(
                "UPDATE users SET failed_attempts=?,locked_until=? WHERE id=?",
                (attempts, lock_value, user["id"]),
            )
        return None, generic, 401

    with server.conn() as connection:
        connection.execute(
            "UPDATE users SET failed_attempts=0,locked_until='',last_login=? WHERE id=?",
            (_iso(), user["id"]),
        )
    return _user_by_id(user["id"]), None, 200


def _install_server_patch() -> None:
    import server

    if getattr(server, "_vaelith_professional_auth_installed", False):
        return

    def professional_current_user(token: str | None):
        return _resolve_user(token)

    server.current_user = professional_current_user
    server._vaelith_professional_auth_installed = True


def _activation_page(token: str) -> str:
    safe_token = escape(token, quote=True)
    return f"""<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='referrer' content='no-referrer'><title>Ativar conta proprietária | VAELITH</title><style>
:root{{--dark:#080b09;--panel:#f4f5f2;--ink:#161a16;--muted:#657067;--line:#d8ddd7;--accent:#c8ff3d;--danger:#a52d2d}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:28px;background:radial-gradient(circle at 20% 0%,rgba(200,255,61,.12),transparent 30%),#080b09;font:14px/1.5 Inter,'Segoe UI',Arial,sans-serif;color:#fff}}.card{{width:min(620px,100%);padding:36px;border:1px solid rgba(255,255,255,.12);border-radius:24px;background:#f4f5f2;color:var(--ink);box-shadow:0 28px 90px rgba(0,0,0,.42)}}.brand{{display:flex;align-items:center;gap:12px;margin-bottom:28px}}.mark{{width:42px;height:42px;display:grid;place-items:center;border-radius:12px;background:#101410;color:var(--accent);font-size:20px;font-weight:900}}.brand b{{display:block;letter-spacing:.12em}}.brand small{{color:var(--muted);font-size:9px;letter-spacing:.15em}}.eyebrow{{color:#60705f;font-size:9px;font-weight:850;letter-spacing:.16em}}h1{{margin:8px 0 8px;font-size:34px;line-height:1.08;letter-spacing:-.04em}}p{{color:var(--muted)}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}label{{display:block;margin:12px 0}}label span{{display:block;margin-bottom:6px;font-size:10px;font-weight:800}}input{{width:100%;height:47px;padding:0 12px;border:1px solid var(--line);border-radius:9px;background:#fff;color:var(--ink);font:inherit}}.hint{{font-size:10px;color:var(--muted)}}button{{width:100%;height:49px;margin-top:14px;border:0;border-radius:9px;background:#111511;color:#fff;font-weight:850;cursor:pointer}}button:disabled{{opacity:.6}}#msg{{min-height:22px;color:var(--danger);font-size:11px}}.security{{margin-top:18px;padding-top:16px;border-top:1px solid var(--line);font-size:10px;color:var(--muted)}}@media(max-width:650px){{.card{{padding:25px}}.grid{{grid-template-columns:1fr}}h1{{font-size:29px}}}}
</style></head><body><main class='card'><div class='brand'><div class='mark'>V</div><div><b>VAELITH</b><small>PLATFORM · CONTA PROPRIETÁRIA</small></div></div><span class='eyebrow'>ATIVAÇÃO ÚNICA E SEGURA</span><h1>Crie sua conta profissional.</h1><p>Defina os dados do proprietário da VAELITH Platform. Depois da ativação, o acesso demonstrativo será desativado e os empreendimentos existentes serão vinculados à nova conta.</p><form id='form'><input id='token' type='hidden' value='{safe_token}'><div class='grid'><label><span>Nome completo</span><input id='name' value='Douglas Ornelas' autocomplete='name' required></label><label><span>E-mail profissional</span><input id='email' type='email' autocomplete='email' placeholder='seuemail@outlook.com' required></label></div><label><span>Nova senha</span><input id='password' type='password' autocomplete='new-password' required></label><label><span>Confirmar senha</span><input id='confirm' type='password' autocomplete='new-password' required></label><div class='hint'>Use pelo menos 12 caracteres, com maiúscula, minúscula, número e símbolo.</div><button id='submit'>Ativar conta proprietária</button><p id='msg'></p></form><div class='security'>A senha é enviada somente ao servidor por conexão HTTPS e armazenada com derivação criptográfica scrypt. Este link deixa de funcionar após a primeira ativação.</div></main><script>
const $=id=>document.getElementById(id);$('form').onsubmit=async e=>{{e.preventDefault();$('msg').textContent='';if($('password').value!==$('confirm').value){{$('msg').textContent='As senhas não coincidem.';return}}$('submit').disabled=true;$('submit').textContent='Ativando conta...';try{{const r=await fetch('/api/auth/activate-owner',{{method:'POST',credentials:'same-origin',headers:{{'content-type':'application/json'}},body:JSON.stringify({{token:$('token').value,name:$('name').value.trim(),email:$('email').value.trim(),password:$('password').value}})}});const d=await r.json();if(!r.ok)throw Error(d.detail||'Não foi possível ativar a conta.');location=d.redirect||'/app'}}catch(err){{$('msg').textContent=err.message;$('submit').disabled=false;$('submit').textContent='Ativar conta proprietária'}}}};
</script></body></html>"""


def _account_page(user: dict) -> str:
    name = escape(str(user.get("name", "")))
    email = escape(str(user.get("email", "")))
    role = "Proprietário" if user.get("role") == "owner" else "Usuário"
    return f"""<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Minha conta | VAELITH</title><style>
:root{{--bg:#080b09;--panel:#121913;--line:rgba(255,255,255,.12);--text:#f4f7f3;--muted:#95a199;--accent:#c8ff3d;--danger:#ff9696}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;padding:28px;background:radial-gradient(circle at 15% 0%,rgba(200,255,61,.1),transparent 28%),var(--bg);color:var(--text);font:14px/1.5 Inter,'Segoe UI',Arial,sans-serif}}main{{width:min(760px,100%);margin:0 auto}}a{{color:var(--accent);text-decoration:none}}.top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}}.card{{padding:28px;border:1px solid var(--line);border-radius:20px;background:linear-gradient(145deg,rgba(255,255,255,.065),rgba(255,255,255,.025))}}.eyebrow{{color:var(--accent);font-size:9px;font-weight:850;letter-spacing:.17em}}h1{{margin:8px 0 5px;font-size:34px;letter-spacing:-.04em}}p{{color:var(--muted)}}.identity{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin:20px 0}}.identity div{{padding:14px;border:1px solid var(--line);border-radius:12px}}.identity span,label span{{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.12em}}.identity b{{display:block;margin-top:5px}}label{{display:block;margin:13px 0}}input{{width:100%;height:46px;margin-top:6px;padding:0 12px;border:1px solid var(--line);border-radius:9px;background:#0c110d;color:#fff;font:inherit}}button{{height:46px;padding:0 16px;border:0;border-radius:9px;background:var(--accent);color:#10140f;font-weight:850;cursor:pointer}}#msg{{min-height:22px;color:var(--danger);font-size:11px}}@media(max-width:680px){{.identity{{grid-template-columns:1fr}}}}
</style></head><body><main><div class='top'><a href='/app'>← Voltar à plataforma</a><a href='/api/auth/logout' id='logout'>Sair</a></div><section class='card'><span class='eyebrow'>CONTA VAELITH</span><h1>Minha conta</h1><p>Gerencie as credenciais pessoais de acesso à plataforma.</p><div class='identity'><div><span>Nome</span><b>{name}</b></div><div><span>E-mail</span><b>{email}</b></div><div><span>Perfil</span><b>{role}</b></div></div><h2>Alterar senha</h2><form id='form'><label><span>Senha atual</span><input id='current' type='password' autocomplete='current-password' required></label><label><span>Nova senha</span><input id='password' type='password' autocomplete='new-password' required></label><label><span>Confirmar nova senha</span><input id='confirm' type='password' autocomplete='new-password' required></label><button>Atualizar senha</button><p id='msg'></p></form></section></main><script>
const $=id=>document.getElementById(id);$('logout').onclick=async e=>{{e.preventDefault();await fetch('/api/auth/logout',{{method:'POST',credentials:'same-origin'}});location='/login'}};$('form').onsubmit=async e=>{{e.preventDefault();if($('password').value!==$('confirm').value){{$('msg').textContent='As novas senhas não coincidem.';return}}try{{const r=await fetch('/api/auth/change-password',{{method:'POST',credentials:'same-origin',headers:{{'content-type':'application/json'}},body:JSON.stringify({{currentPassword:$('current').value,newPassword:$('password').value}})}});const d=await r.json();if(!r.ok)throw Error(d.detail||'Não foi possível alterar a senha.');$('msg').style.color='#c8ff3d';$('msg').textContent='Senha atualizada. Entre novamente.';setTimeout(()=>location='/login',1200)}}catch(err){{$('msg').textContent=err.message}}}};
</script></body></html>"""


def install(app: FastAPI) -> None:
    if getattr(app.state, "_vaelith_auth_runtime_installed", False):
        return
    app.state._vaelith_auth_runtime_installed = True

    @app.get("/ativar-conta", include_in_schema=False)
    def activate_owner_page(token: str = ""):
        if _owner_exists():
            return RedirectResponse("/login", 307)
        if not token or not _activation_valid(token):
            return HTMLResponse("Link de ativação inválido ou expirado.", status_code=404)
        return HTMLResponse(_activation_page(token), headers={"Cache-Control": "no-store"})

    @app.get("/conta", include_in_schema=False)
    def account_page(request: Request):
        _install_server_patch()
        user = _resolve_user(request.cookies.get("vaelith_session"))
        if not user:
            return RedirectResponse("/login", 307)
        return HTMLResponse(_account_page(user), headers={"Cache-Control": "no-store"})

    @app.get("/api/auth/professional-status", include_in_schema=False)
    def professional_status():
        return {
            "professional": True,
            "ownerConfigured": _owner_exists(),
            "demoEnabled": False,
            "sessionMode": "signed-cookie-v4",
            "passwordHash": "scrypt",
        }

    @app.get("/api/auth/self-test", include_in_schema=False)
    def professional_auth_self_test():
        _ensure_schema()
        owner_configured = _owner_exists()
        checks = {
            "schemaReady": True,
            "demoLoginDisabled": True,
            "activationProtected": bool(ACTIVATION_TOKEN_SHA256),
            "signedSessions": True,
            "secureCookie": bool(os.getenv("VERCEL") or os.getenv("COOKIE_SECURE") == "1"),
        }
        return {
            "ok": all(checks.values()),
            "mode": "professional-owner-auth-v4",
            "ownerConfigured": owner_configured,
            "checks": checks,
        }

    @app.middleware("http")
    async def professional_auth_middleware(request: Request, call_next):
        try:
            _install_server_patch()
            _ensure_schema()
        except Exception as exc:
            print(f"VAELITH_AUTH_BOOT_ERROR: {type(exc).__name__}: {str(exc)[:200]}")

        path = request.url.path
        method = request.method.upper()

        if path == "/api/auth/login" and method == "POST":
            try:
                body = await request.json()
            except Exception:
                return _json_error("Requisição inválida.", 400)
            email = str(body.get("email", "")).strip()
            password = str(body.get("password", ""))
            remember = bool(body.get("remember", True))
            user, error, status = _authenticate(email, password)
            if not user:
                return _json_error(error or "Acesso negado.", status)
            response = JSONResponse({"ok": True, "redirect": "/app"})
            response.headers["set-cookie"] = _cookie_header(_sign_user(user, remember), remember)
            response.headers["Cache-Control"] = "no-store"
            return response

        if path == "/api/auth/logout" and method in {"POST", "GET"}:
            response = JSONResponse({"ok": True, "redirect": "/login"})
            response.headers["set-cookie"] = _clear_cookie_header()
            response.headers["Cache-Control"] = "no-store"
            return response

        if path == "/api/auth/activate-owner" and method == "POST":
            if _owner_exists():
                return _json_error("A conta proprietária já foi configurada.", 409)
            try:
                body = await request.json()
            except Exception:
                return _json_error("Requisição inválida.", 400)
            token = str(body.get("token", ""))
            name = re.sub(r"\s+", " ", str(body.get("name", "")).strip())
            email = str(body.get("email", "")).lower().strip()
            password = str(body.get("password", ""))
            if not _activation_valid(token):
                return _json_error("Link de ativação inválido ou expirado.", 403)
            if len(name) < 3:
                return _json_error("Informe o nome completo.", 400)
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or email == DEMO_EMAIL:
                return _json_error("Informe um e-mail profissional válido.", 400)
            password_error = _password_error(password)
            if password_error:
                return _json_error(password_error, 400)

            import server

            salt, password_hash = _hash_password(password)
            user_id = uuid4().hex
            created = _iso()
            with server.conn() as connection:
                demo = connection.execute("SELECT id FROM users WHERE lower(email)=lower(?)", (DEMO_EMAIL,)).fetchone()
                existing = connection.execute("SELECT id FROM users WHERE lower(email)=lower(?)", (email,)).fetchone()
                if existing:
                    user_id = existing["id"]
                    connection.execute(
                        "UPDATE users SET name=?,email=?,salt=?,pw=?,role='owner',active=1,created=?,password_updated=?,failed_attempts=0,locked_until='',session_version=COALESCE(session_version,0)+1 WHERE id=?",
                        (name, email, salt, password_hash, created, created, user_id),
                    )
                else:
                    connection.execute(
                        "INSERT INTO users(id,name,email,salt,pw,role,active,created,last_login,password_updated,failed_attempts,locked_until,session_version) VALUES(?,?,?,?,?,'owner',1,?,'',?,0,'',1)",
                        (user_id, name, email, salt, password_hash, created, created),
                    )
                if demo:
                    connection.execute("UPDATE projects SET user_id=? WHERE user_id=?", (user_id, demo["id"]))
                    connection.execute(
                        "UPDATE users SET active=0,role='disabled',session_version=COALESCE(session_version,0)+1 WHERE id=?",
                        (demo["id"],),
                    )
                    connection.execute("DELETE FROM sessions WHERE user_id=?", (demo["id"],))
                connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

            owner = _user_by_id(user_id)
            response = JSONResponse({"ok": True, "redirect": "/app", "name": name, "email": email})
            response.headers["set-cookie"] = _cookie_header(_sign_user(owner, True), True)
            response.headers["Cache-Control"] = "no-store"
            return response

        if path == "/api/auth/change-password" and method == "POST":
            user = _resolve_user(request.cookies.get("vaelith_session"))
            if not user:
                return _json_error("Sessão expirada. Entre novamente.", 401)
            try:
                body = await request.json()
            except Exception:
                return _json_error("Requisição inválida.", 400)
            current_password = str(body.get("currentPassword", ""))
            new_password = str(body.get("newPassword", ""))
            if not _verify_password(user, current_password):
                return _json_error("A senha atual está incorreta.", 400)
            password_error = _password_error(new_password)
            if password_error:
                return _json_error(password_error, 400)
            if hmac.compare_digest(current_password, new_password):
                return _json_error("A nova senha deve ser diferente da senha atual.", 400)
            salt, password_hash = _hash_password(new_password)
            import server

            with server.conn() as connection:
                connection.execute(
                    "UPDATE users SET salt=?,pw=?,password_updated=?,session_version=COALESCE(session_version,0)+1 WHERE id=?",
                    (salt, password_hash, _iso(), user["id"]),
                )
                connection.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            response = JSONResponse({"ok": True, "redirect": "/login"})
            response.headers["set-cookie"] = _clear_cookie_header()
            response.headers["Cache-Control"] = "no-store"
            return response

        response = await call_next(request)
        if path in {"/login", "/app", "/conta", "/ativar-conta"} or path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


AUTH_RUNTIME_BUILD_MARKER = "2026-07-30T22:58-03:00"
