from __future__ import annotations

from server import app
from professional_auth_v3 import install as install_professional_auth
from demo_runtime import seed_realistic_demo
from supabase_runtime import install
from storage_selftest import install as install_storage_selftest

# Install professional authentication only after server.py has initialized. The
# account is stored in its own PostgreSQL table and no longer depends on a
# temporary serverless instance.
if not any(
    getattr(route, "path", None) == "/api/auth/persistence-self-test-v3"
    for route in app.routes
):
    install_professional_auth(app)

seed_realistic_demo()

if not any(getattr(route, "path", None) == "/api/storage/status" for route in app.routes):
    install(app)
if not any(getattr(route, "path", None) == "/api/storage/self-test" for route in app.routes):
    install_storage_selftest(app)


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
