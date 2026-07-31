from __future__ import annotations

import hashlib
import hmac

# Temporary compatibility shim used only by the isolated stress-test runtime.
if not hasattr(hashlib, "compare_digest"):
    hashlib.compare_digest = hmac.compare_digest

from server import app
from professional_auth_v3 import install as install_professional_auth
from demo_runtime import seed_realistic_demo
from supabase_runtime import install
from storage_selftest import install as install_storage_selftest
from extreme_test_runtime_v1 import install as install_extreme_test
from deep_probe_runtime_v1 import install as install_deep_probe

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

# Temporary, token-protected and non-destructive validation endpoints. They are
# removed after the final report is collected.
install_extreme_test(app)
install_deep_probe(app)


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


PROFESSIONAL_AUTH_BUILD = "2026-07-31T09:01-03:00"
