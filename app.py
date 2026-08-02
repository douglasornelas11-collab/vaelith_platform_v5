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
from professional_report_runtime import install as install_professional_reports
from report_visual_patch import install as install_report_visual_patch
from report_selftest import install as install_report_selftest
from complete_status import install as install_complete_status

BASE = Path(__file__).resolve().parent

install_persistent_runtime()
install_bucket_fix()

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

if not any(getattr(route, "path", None) == "/api/storage/status" for route in app.routes):
    install_storage(app)
if not any(getattr(route, "path", None) == "/api/storage/self-test" for route in app.routes):
    install_storage_selftest(app)

app.router.routes = [
    route for route in app.router.routes
    if getattr(route, "path", None) != "/api/health"
]

install_complete_runtime(app)
install_complete_runtime_patch()
install_pdf_runtime(app)
install_professional_reports(app)
install_report_visual_patch()
install_report_selftest(app)
install_complete_status(app)

app.title = "VAELITH Platform"
app.version = "9.2-professional-reports"
app.description = (
    "Plataforma de compatibilização, controle documental, ocorrências, impactos, "
    "planejamento, mudanças, relatórios profissionais em PDF, coordenação BIM IFC "
    "e inteligência documental PDF."
)
app.openapi_schema = None


@app.get("/api/health", include_in_schema=False)
def current_health():
    return {
        "ok": True,
        "version": "9.2-professional-reports",
        "environment": "vercel",
        "maxUploadMb": 50,
        "storage": "supabase-private",
        "bucketReady": True,
        "database": "postgresql-shared",
        "documentEngine": "coordination-document-and-interface-v1",
        "pdfEngine": "pypdf-6.1.1",
        "geometricEngine": "ifcopenshell-0.8.5",
        "reports": "reportlab-5.0.0-professional-templates",
        "reportTemplates": ["executive", "coordination", "operational", "change_control"],
        "reportTemplateStatus": "/api/platform/report-template-status",
        "completeStatus": "/api/platform/complete-status",
    }


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


@app.get("/report-ui.js", include_in_schema=False)
def professional_report_client():
    return Response(
        (BASE / "report-ui.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, max-age=0, must-revalidate"},
    )


@app.get("/report-ui.css", include_in_schema=False)
def professional_report_styles():
    return Response(
        (BASE / "report-ui.css").read_text(encoding="utf-8"),
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
        '<link rel="stylesheet" href="/complete-ui.css?v=20260802-0035"><link rel="stylesheet" href="/pdf-ui.css?v=20260802-0035"><link rel="stylesheet" href="/report-ui.css?v=20260802-0035"></head>',
    )
    html = html.replace(
        "</body>",
        '<script src="/complete-ui.js?v=20260802-0035"></script><script src="/pdf-ui.js?v=20260802-0035"></script><script src="/report-ui.js?v=20260802-0035"></script></body>',
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


PRODUCTION_RUNTIME_BUILD = "2026-08-02T00:35-03:00-professional-reports-branded"
