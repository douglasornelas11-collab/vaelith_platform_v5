from __future__ import annotations

from server import app
from supabase_runtime import install

if not any(getattr(route, "path", None) == "/api/storage/status" for route in app.routes):
    install(app)


@app.middleware("http")
async def allow_supabase_direct_upload(request, call_next):
    response = await call_next(request)
    csp = response.headers.get("Content-Security-Policy", "")
    if "connect-src 'self'" in csp:
        response.headers["Content-Security-Policy"] = csp.replace(
            "connect-src 'self'",
            "connect-src 'self' https://*.supabase.co",
        )
    return response
