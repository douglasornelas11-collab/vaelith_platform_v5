from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from http.cookies import SimpleCookie

from fastapi import FastAPI, Request


TOKEN_PREFIX = "v2."
TOKEN_TTL_SECONDS = 14 * 24 * 60 * 60


def _secret() -> bytes:
    source = (
        os.getenv("VAELITH_SESSION_SECRET")
        or os.getenv("AUTH_SECRET")
        or os.getenv("VAELITH_DB_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("POSTGRES_URL")
        or "vaelith-beta-session-fallback-change-before-commercial-release"
    )
    return hashlib.sha256(source.encode("utf-8")).digest()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(email: str, expires_at: int | None = None) -> str:
    payload = {
        "email": email.lower().strip(),
        "exp": int(expires_at or (time.time() + TOKEN_TTL_SECONDS)),
        "v": 2,
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64encode(hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{TOKEN_PREFIX}{encoded}.{signature}"


def _verify(token: str) -> dict | None:
    if not token.startswith(TOKEN_PREFIX):
        return None
    try:
        encoded, provided = token[len(TOKEN_PREFIX):].split(".", 1)
        expected = _b64encode(hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(provided, expected):
            return None
        payload = json.loads(_b64decode(encoded))
        if not isinstance(payload, dict) or int(payload.get("exp", 0)) <= int(time.time()):
            return None
        email = str(payload.get("email", "")).lower().strip()
        if not email:
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _cookie_value(set_cookie_header: str) -> str | None:
    try:
        parsed = SimpleCookie()
        parsed.load(set_cookie_header)
        morsel = parsed.get("vaelith_session")
        return morsel.value if morsel else None
    except Exception:
        match = re.search(r"(?:^|;\s*)vaelith_session=([^;]+)", set_cookie_header)
        return match.group(1) if match else None


def _signed_cookie_header(token: str) -> str:
    cookie = SimpleCookie()
    cookie["vaelith_session"] = token
    cookie["vaelith_session"]["path"] = "/"
    cookie["vaelith_session"]["max-age"] = str(TOKEN_TTL_SECONDS)
    cookie["vaelith_session"]["httponly"] = True
    cookie["vaelith_session"]["samesite"] = "Lax"
    if os.getenv("VERCEL") or os.getenv("COOKIE_SECURE") == "1":
        cookie["vaelith_session"]["secure"] = True
    return cookie.output(header="").strip()


def _install_server_patch() -> None:
    import server

    if getattr(server, "_vaelith_stateless_auth_installed", False):
        return

    original_current_user = server.current_user

    def stateless_current_user(token: str | None):
        if not token:
            return None
        payload = _verify(token)
        if payload:
            with server.conn() as connection:
                row = connection.execute(
                    "SELECT * FROM users WHERE email=?",
                    (payload["email"],),
                ).fetchone()
            return dict(row) if row else None
        return original_current_user(token)

    server._vaelith_original_current_user = original_current_user
    server.current_user = stateless_current_user
    server._vaelith_stateless_auth_installed = True


def install(app: FastAPI) -> None:
    if getattr(app.state, "_vaelith_auth_runtime_installed", False):
        return
    app.state._vaelith_auth_runtime_installed = True

    @app.middleware("http")
    async def stateless_auth_middleware(request: Request, call_next):
        try:
            _install_server_patch()
        except Exception as exc:
            print(f"VAELITH_AUTH_PATCH_ERROR: {exc}")

        response = await call_next(request)

        if request.url.path == "/api/auth/login" and response.status_code in {200, 204}:
            try:
                import server

                opaque_token = _cookie_value(response.headers.get("set-cookie", ""))
                if opaque_token:
                    with server.conn() as connection:
                        row = connection.execute(
                            "SELECT users.email FROM sessions "
                            "JOIN users ON users.id=sessions.user_id WHERE sessions.token=?",
                            (opaque_token,),
                        ).fetchone()
                    if row:
                        response.headers["set-cookie"] = _signed_cookie_header(_sign(row["email"]))
            except Exception as exc:
                print(f"VAELITH_AUTH_COOKIE_ERROR: {exc}")

        if request.url.path in {"/login", "/app"} or request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.get("/api/auth/self-test", include_in_schema=False)
    def stateless_auth_self_test():
        import server

        _install_server_patch()
        deterministic_token = _sign("demo@vaelithlabs.com.br", 4102444800)
        payload = _verify(deterministic_token)
        user = server.current_user(deterministic_token)
        cookie_header = _signed_cookie_header(deterministic_token)
        fingerprint = hashlib.sha256(deterministic_token.encode("utf-8")).hexdigest()[:16]
        checks = {
            "tokenSigned": deterministic_token.startswith(TOKEN_PREFIX),
            "tokenVerified": bool(payload and payload.get("email") == "demo@vaelithlabs.com.br"),
            "userResolved": bool(user and user.get("email") == "demo@vaelithlabs.com.br"),
            "cookieHttpOnly": "HttpOnly" in cookie_header,
            "cookieSecure": "Secure" in cookie_header if os.getenv("VERCEL") else True,
            "cookiePath": "Path=/" in cookie_header,
            "cookieSameSite": "SameSite=Lax" in cookie_header,
        }
        return {
            "ok": all(checks.values()),
            "mode": "stateless-signed-cookie-v2",
            "fingerprint": fingerprint,
            "checks": checks,
        }


AUTH_RUNTIME_BUILD_MARKER = "2026-07-30T22:38-03:00"
