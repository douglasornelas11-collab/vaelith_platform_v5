from __future__ import annotations

from server import app
from persistent_runtime import install as install_persistent_runtime
from professional_auth_v3 import install as install_professional_auth
from supabase_runtime import install as install_storage
from storage_selftest import install as install_storage_selftest

# server.py still initializes its legacy local structures while importing. From
# this point onward, every operational request uses the shared PostgreSQL.
install_persistent_runtime()

# Remove only the legacy endpoints whose implementation writes to /tmp. The
# persistent Supabase endpoints, installed earlier by the runtime bootstrap,
# remain registered.
_LEGACY_ENDPOINT_NAMES = {"health", "upload", "delete_file", "download_file"}
app.router.routes = [
    route
    for route in app.router.routes
    if getattr(getattr(route, "endpoint", None), "__name__", "")
    not in _LEGACY_ENDPOINT_NAMES
]

if not any(
    getattr(route, "path", None) == "/api/auth/persistence-self-test-v3"
    for route in app.routes
):
    install_professional_auth(app)

# Install storage routes only when the early runtime bootstrap was unavailable.
if not any(getattr(route, "path", None) == "/api/storage/status" for route in app.routes):
    install_storage(app)
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


PRODUCTION_RUNTIME_BUILD = "2026-07-31T09:18-03:00"
