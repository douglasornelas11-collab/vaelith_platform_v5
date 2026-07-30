from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

BASE = Path(__file__).resolve().parent

ASSETS: dict[str, tuple[str, str]] = {
    "/platform-v3.css": ("platform-v3.css", "text/css; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/ui-fixes.css": ("ui-fixes.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/supabase-upload.js": ("supabase-upload.js", "application/javascript; charset=utf-8"),
    "/unified-ui.js": ("unified-ui.js", "application/javascript; charset=utf-8"),
}


def _serve(filename: str, media_type: str) -> FileResponse:
    path = BASE / filename
    if not path.is_file():
        raise HTTPException(404, f"Recurso estático não encontrado: {filename}")
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store, max-age=0, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def install(app: FastAPI) -> None:
    @app.get("/platform-v3.css", include_in_schema=False)
    def platform_v3_css():
        return _serve(*ASSETS["/platform-v3.css"])

    @app.get("/app.css", include_in_schema=False)
    def app_css():
        return _serve(*ASSETS["/app.css"])

    @app.get("/ui-fixes.css", include_in_schema=False)
    def ui_fixes_css():
        return _serve(*ASSETS["/ui-fixes.css"])

    @app.get("/app.js", include_in_schema=False)
    def app_js():
        return _serve(*ASSETS["/app.js"])

    @app.get("/supabase-upload.js", include_in_schema=False)
    def supabase_upload_js():
        return _serve(*ASSETS["/supabase-upload.js"])

    @app.get("/unified-ui.js", include_in_schema=False)
    def unified_ui_js():
        return _serve(*ASSETS["/unified-ui.js"])
