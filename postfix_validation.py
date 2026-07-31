from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
from collections import Counter
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request

TOKEN_SHA256 = "fe3fb70a4c32a809a3238cf8079912ddabb94f184ac1b41240e7602127ffc4f4"


def _authorized(token: str) -> None:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(digest, TOKEN_SHA256):
        raise HTTPException(404, "Not found")


def _instance() -> str:
    return f"{os.getenv('VERCEL_REGION','local')}:{os.getpid()}:{id(_instance)}"


def _origin(request: Request) -> str:
    host = request.headers.get("host") or "vaelith-platform-v5.vercel.app"
    scheme = request.headers.get("x-forwarded-proto") or "https"
    return f"{scheme}://{host}"


def _cleanup_project(project_id: str) -> None:
    import server

    with server.conn() as c:
        issue_ids = [row[0] for row in c.execute(
            "SELECT id FROM operational_issues WHERE project_id=?", (project_id,)
        ).fetchall()]
        for issue_id in issue_ids:
            c.execute("DELETE FROM issue_history WHERE issue_id=?", (issue_id,))
            c.execute("DELETE FROM issue_decisions WHERE issue_id=?", (issue_id,))
            c.execute("DELETE FROM issue_impacts WHERE issue_id=?", (issue_id,))
        c.execute("DELETE FROM operational_issues WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM budget_items WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM analyses WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM files WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM projects WHERE id=?", (project_id,))


def install(app: FastAPI) -> None:
    @app.get("/api/internal/postfix/read", include_in_schema=False)
    def read_marker(project_id: str, token: str, nonce: str = ""):
        _authorized(token)
        import server

        with server.conn() as c:
            row = c.execute("SELECT id,name FROM projects WHERE id=?", (project_id,)).fetchone()
        return {
            "found": bool(row),
            "name": row["name"] if row else None,
            "instance": _instance(),
            "nonce": nonce,
        }

    @app.get("/api/internal/postfix/route-audit", include_in_schema=False)
    def route_audit(token: str):
        _authorized(token)
        entries = []
        for route in app.routes:
            methods = sorted(getattr(route, "methods", set()) or set())
            path = getattr(route, "path", "")
            endpoint = getattr(getattr(route, "endpoint", None), "__name__", "")
            for method in methods:
                if method not in {"HEAD", "OPTIONS"}:
                    entries.append((method, path, endpoint))
        counts = Counter((method, path) for method, path, _ in entries)
        duplicates = [
            {"method": method, "path": path, "count": count,
             "endpoints": [e for m, p, e in entries if m == method and p == path]}
            for (method, path), count in counts.items() if count > 1
        ]
        forbidden_legacy = [
            {"method": method, "path": path, "endpoint": endpoint}
            for method, path, endpoint in entries
            if endpoint in {"health", "upload", "delete_file", "download_file"}
        ]
        return {
            "ok": not duplicates and not forbidden_legacy,
            "routeCount": len(entries),
            "duplicates": duplicates,
            "legacyTemporaryRoutes": forbidden_legacy,
        }

    @app.post("/api/internal/postfix/cross-instance", include_in_schema=False)
    async def cross_instance(request: Request, token: str):
        _authorized(token)
        import server

        project_id = "validation-" + uuid4().hex
        name = "VAELITH CROSS INSTANCE " + uuid4().hex[:10]
        with server.conn() as c:
            c.execute(
                "INSERT INTO projects(id,user_id,name,client,location,phase,created) VALUES(?,?,?,?,?,?,?)",
                (project_id, "__validation__", name, "Synthetic", "Validation", "Test", server.now()),
            )
        try:
            base = _origin(request)
            async with httpx.AsyncClient(timeout=25.0, trust_env=False, follow_redirects=True) as client:
                calls = [
                    client.get(
                        f"{base}/api/internal/postfix/read",
                        params={"project_id": project_id, "token": token, "nonce": str(i)},
                        headers={"cache-control": "no-cache", "x-vaelith-validation": str(uuid4())},
                    )
                    for i in range(32)
                ]
                responses = await asyncio.gather(*calls, return_exceptions=True)
            parsed = []
            errors = []
            for response in responses:
                if isinstance(response, Exception):
                    errors.append(f"{type(response).__name__}: {str(response)[:120]}")
                    continue
                try:
                    parsed.append(response.json())
                except Exception:
                    errors.append(f"HTTP {response.status_code}: {response.text[:100]}")
            instances = sorted({item.get("instance") for item in parsed if item.get("instance")})
            misses = sum(1 for item in parsed if not item.get("found"))
            wrong = sum(1 for item in parsed if item.get("found") and item.get("name") != name)
            return {
                "ok": len(parsed) == 32 and misses == 0 and wrong == 0 and not errors,
                "requests": 32,
                "responses": len(parsed),
                "instances": instances,
                "instanceCount": len(instances),
                "misses": misses,
                "wrongValues": wrong,
                "errors": errors,
            }
        finally:
            _cleanup_project(project_id)

    @app.post("/api/internal/postfix/api-cycle", include_in_schema=False)
    async def api_cycle(request: Request, token: str):
        _authorized(token)
        import professional_auth_v3 as auth

        owner = auth._owner()
        if not owner:
            raise HTTPException(409, "Owner not configured")
        session = auth._sign_user(owner, False)
        base = _origin(request)
        project_id = None
        results = {}
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                trust_env=False,
                follow_redirects=True,
                cookies={"vaelith_session": session},
            ) as client:
                create = await client.post(
                    f"{base}/api/projects",
                    json={"name": "VALIDAÇÃO TEMPORÁRIA " + uuid4().hex[:8], "client": "Synthetic", "location": "Test"},
                )
                results["createProject"] = create.status_code
                if create.status_code >= 400:
                    return {"ok": False, "results": results, "detail": create.text[:300]}
                project_id = create.json()["id"]
                listed = await client.get(f"{base}/api/projects")
                results["listProjects"] = listed.status_code
                results["projectVisible"] = any(p.get("id") == project_id for p in listed.json()) if listed.status_code == 200 else False
                issue = await client.post(
                    f"{base}/api/projects/{project_id}/operational/issues",
                    json={
                        "title": "Ocorrência sintética de validação",
                        "description": "Registro temporário criado pelo teste pós-correção.",
                        "issueType": "risco",
                        "severity": "alta",
                        "location": "Ambiente de teste",
                        "disciplines": ["ARQ", "EST"],
                        "assignee": "Validação automática",
                    },
                )
                results["createIssue"] = issue.status_code
                dashboard = await client.get(f"{base}/api/projects/{project_id}/operational/dashboard")
                results["dashboard"] = dashboard.status_code
                results["issueCount"] = dashboard.json().get("totalIssues") if dashboard.status_code == 200 else None
                compatibility = await client.post(f"{base}/api/projects/{project_id}/compatibility")
                results["compatibility"] = compatibility.status_code
                latest = await client.get(f"{base}/api/projects/{project_id}/compatibility/latest")
                results["latestCompatibility"] = latest.status_code
            ok = (
                results.get("createProject") == 200
                and results.get("listProjects") == 200
                and results.get("projectVisible") is True
                and results.get("createIssue") == 200
                and results.get("dashboard") == 200
                and results.get("issueCount") == 1
                and results.get("compatibility") == 200
                and results.get("latestCompatibility") == 200
            )
            return {"ok": ok, "results": results}
        finally:
            if project_id:
                _cleanup_project(project_id)

    @app.post("/api/internal/postfix/storage-cycle", include_in_schema=False)
    async def storage_cycle(token: str):
        _authorized(token)
        import supabase_runtime as storage

        info = storage.ensure_bucket()
        path = f"_vaelith_validation/{uuid4().hex}.txt"
        payload = ("VAELITH-STORAGE-" + uuid4().hex).encode("utf-8")
        encoded_path = httpx.URL(path).raw_path.decode("ascii")
        bucket = storage.BUCKET
        headers = storage._storage_headers(json_content=False)
        headers["Content-Type"] = "text/plain"
        headers["x-upsert"] = "false"
        base = storage._base_url()
        uploaded = read_ok = deleted = False
        detail = None
        try:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False, follow_redirects=False) as client:
                upload = await client.post(
                    f"{base}/object/{bucket}/{encoded_path}", headers=headers, content=payload
                )
                uploaded = upload.status_code in {200, 201}
                if not uploaded:
                    detail = f"upload HTTP {upload.status_code}: {upload.text[:220]}"
                    return {"ok": False, "bucket": info, "uploaded": False, "detail": detail}
                download = await client.get(
                    f"{base}/object/authenticated/{bucket}/{encoded_path}",
                    headers=storage._storage_headers(json_content=False),
                )
                read_ok = download.status_code == 200 and download.content == payload
                delete = await client.delete(
                    f"{base}/object/{bucket}/{encoded_path}",
                    headers=storage._storage_headers(json_content=False),
                )
                deleted = delete.status_code in {200, 204}
            return {
                "ok": uploaded and read_ok and deleted,
                "bucket": info,
                "uploaded": uploaded,
                "readBack": read_ok,
                "deleted": deleted,
                "bytes": len(payload),
            }
        finally:
            if uploaded and not deleted:
                try:
                    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
                        await client.delete(
                            f"{base}/object/{bucket}/{encoded_path}",
                            headers=storage._storage_headers(json_content=False),
                        )
                except Exception:
                    pass
