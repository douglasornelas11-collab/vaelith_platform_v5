from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request


def _endpoint(app: FastAPI, path: str, method: str = "POST"):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route.endpoint
    raise RuntimeError(f"Validation endpoint not found: {method} {path}")


def install(app: FastAPI) -> None:
    cross = _endpoint(app, "/api/internal/postfix/cross-instance")
    api_cycle = _endpoint(app, "/api/internal/postfix/api-cycle")
    storage_cycle = _endpoint(app, "/api/internal/postfix/storage-cycle")

    @app.get("/api/internal/postfix/run-cross-instance", include_in_schema=False)
    async def run_cross_instance(request: Request, token: str):
        return await cross(request, token)

    @app.get("/api/internal/postfix/run-api-cycle", include_in_schema=False)
    async def run_api_cycle(request: Request, token: str):
        return await api_cycle(request, token)

    @app.get("/api/internal/postfix/run-storage-cycle", include_in_schema=False)
    async def run_storage_cycle(token: str):
        return await storage_cycle(token)
