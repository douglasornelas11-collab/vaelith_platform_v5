from __future__ import annotations

from pathlib import Path

from fastapi import Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import server
from server import app
from persistent_runtime import install as install_persistent_runtime
from professional_auth_v3 import install as install_professional_auth
from storage_bucket_fix import install as install_bucket_fix
from supabase_runtime import install as install_storage
from storage_selftest import install as install_storage_selftest
from complete_runtime_v1 import install as install_complete_runtime
from complete_runtime_patch import install as install_complete_runtime_patch
from pdf_runtime import install as install_pdf_runtime
from complete_status import install as install_complete_status

BASE = Path(__file__).resolve().parent

# server.py still initializes its legacy local structures while importing. From
# this point onward, every operational request uses the shared PostgreSQL.
install_persistent_runtime()
install_bucket_fix()

# Remove legacy endpoints that write to /tmp, stale health metadata, the legacy
# /app response and the static script path intercepted by Vercel.
_LEGACY_ENDPOINT_NAMES = {"health", "upload", "delete_file", "download_file"}
app.router.routes = [
    route
    for route in app.router.routes
    if (
        getattr(getattr(route, "endpoint", None), "__name__", "")
        not in _LEGACY_ENDPOINT_NAMES
        and getattr(route, "path", None)
        not in {"/app", "/supabase-upload.js", "/api/health"}
    )
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

# The storage runtime also registers legacy health metadata. Remove it after
# storage installation so the single authoritative route can be registered below.
app.router.routes = [
    route for route in app.router.routes
    if getattr(route, "path", None) != "/api/health"
]

# Complete platform modules: revision control, impact consolidation, planning,
# change control, controlled reports, intelligence, audit trail, IFC BIM and PDF analysis.
install_complete_runtime(app)
install_complete_runtime_patch()
install_pdf_runtime(app)
install_complete_status(app)

# Publish the same product identity in diagnostics and OpenAPI.
app.title = "VAELITH Platform"
app.version = "9.1-pdf-intelligence"
app.description = (
    "Plataforma de compatibilização, controle documental, ocorrências, impactos, "
    "planejamento, mudanças, relatórios, coordenação BIM IFC e inteligência documental PDF."
)
app.openapi_schema = None


@app.get("/api/health", include_in_schema=False)
def current_health():
    return {
        "ok": True,
        "version": "9.1-pdf-intelligence",
        "environment": "vercel",
        "maxUploadMb": 50,
        "storage": "supabase-private",
        "bucketReady": True,
        "database": "postgresql-shared",
        "documentEngine": "coordination-document-and-interface-v1",
        "pdfEngine": "pypdf-6.1.1",
        "geometricEngine": "ifcopenshell-0.8.5",
        "reports": "reportlab-5.0.0",
        "completeStatus": "/api/platform/complete-status",
    }


# Stable compatibility alias for the professional login screen.
@app.get("/api/auth/professional-status", include_in_schema=False)
def professional_status_compatibility_alias():
    import professional_auth_v3 as auth
    return {
        "professional": True,
        "ownerConfigured": bool(auth._owner()),
        "database": "postgresql",
        "sessionMode": "signed-cookie-v6",
        "passwordHash": "scrypt-v1",
    }


@app.get("/supabase-upload-v2.js", include_in_schema=False)
def current_supabase_upload_client():
    return Response(
        (BASE / "supabase-upload.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, max-age=0, must-revalidate"},
    )


@app.get("/complete-ui.js", include_in_schema=False)
def complete_platform_client():
    return Response(
        (BASE / "complete-ui.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, max-age=0, must-revalidate"},
    )


@app.get("/complete-ui.css", include_in_schema=False)
def complete_platform_styles():
    return Response(
        (BASE / "complete-ui.css").read_text(encoding="utf-8"),
        media_type="text/css",
        headers={"Cache-Control": "no-store, max-age=0, must-revalidate"},
    )


@app.get("/pdf-ui.js", include_in_schema=False)
def pdf_platform_client():
    return Response(
        (BASE / "pdf-ui.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, max-age=0, must-revalidate"},
    )


@app.get("/pdf-ui.css", include_in_schema=False)
def pdf_platform_styles():
    return Response(
        (BASE / "pdf-ui.css").read_text(encoding="utf-8"),
        media_type="text/css",
        headers={"Cache-Control": "no-store, max-age=0, must-revalidate"},
    )


@app.get("/app", include_in_schema=False)
def current_app_page(vaelith_session: str | None = Cookie(None)):
    if not server.current_user(vaelith_session):
        return RedirectResponse("/login", status_code=307)
    html = (BASE / "app.html").read_text(encoding="utf-8")
    html = html.replace(
        '/supabase-upload.js?v=20260729-2315',
        '/supabase-upload-v2.js?v=20260731-0938',
    )
    html = html.replace(
        "</head>",
        '<link rel="stylesheet" href="/complete-ui.css?v=20260802-0001"><link rel="stylesheet" href="/pdf-ui.css?v=20260802-0001"></head>',
    )
    html = html.replace(
        "</body>",
        '<script src="/complete-ui.js?v=20260802-0001"></script><script src="/pdf-ui.js?v=20260802-0001"></script></body>',
    )
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-store, max-age=0, must-revalidate"},
    )


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


PRODUCTION_RUNTIME_BUILD = "2026-08-02T00:01-03:00-pdf-intelligence"
