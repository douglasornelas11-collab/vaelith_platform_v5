from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections import Counter
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request

TOKEN_SHA256 = "59d9de9dc57b1cf47f67a4e44f496818ae26df007999e7c917b760bf7d08f3b2"


def _allowed(token: str) -> bool:
    return hashlib.sha256(token.encode("utf-8")).hexdigest() == TOKEN_SHA256


def _cleanup_project(pid: str) -> None:
    import server
    with server.conn() as c:
        issue_rows = c.execute("SELECT id FROM operational_issues WHERE project_id=?", (pid,)).fetchall()
        issue_ids = [row["id"] for row in issue_rows]
        for issue_id in issue_ids:
            c.execute("DELETE FROM issue_history WHERE issue_id=?", (issue_id,))
            c.execute("DELETE FROM issue_decisions WHERE issue_id=?", (issue_id,))
            c.execute("DELETE FROM issue_impacts WHERE issue_id=?", (issue_id,))
        c.execute("DELETE FROM operational_issues WHERE project_id=?", (pid,))
        c.execute("DELETE FROM budget_items WHERE project_id=?", (pid,))
        c.execute("DELETE FROM analyses WHERE project_id=?", (pid,))
        c.execute("DELETE FROM files WHERE project_id=?", (pid,))
        c.execute("DELETE FROM projects WHERE id=?", (pid,))


def install(app: FastAPI) -> None:
    @app.get("/api/internal/retest/read", include_in_schema=False)
    def read_probe(token: str, probe_id: str):
        if not _allowed(token):
            raise HTTPException(404, "Not Found")
        from persistent_runtime import database_url
        import psycopg
        instance = f"{os.getenv('VERCEL_REGION', 'local')}:{os.getpid()}:{id(app)}"
        with psycopg.connect(database_url(), autocommit=True, connect_timeout=10) as connection:
            row = connection.execute(
                "SELECT value FROM vaelith_retest_probe WHERE id=%s", (probe_id,)
            ).fetchone()
        return {"found": bool(row), "value": row[0] if row else None, "instance": instance}

    @app.get("/api/internal/retest", include_in_schema=False)
    async def run_retest(request: Request, token: str):
        if not _allowed(token):
            raise HTTPException(404, "Not Found")

        import professional_auth_v3 as auth
        import server
        import supabase_runtime as storage
        from persistent_runtime import database_url
        import psycopg

        started = time.perf_counter()
        probe_id = uuid4().hex
        project_id = ""
        file_id = ""
        object_uploaded = False
        actual_payload = (b"VAELITH-RETEST-2026\n" * 100000)[:2 * 1024 * 1024]
        result: dict = {"ok": False, "tests": {}, "cleanup": {}}

        try:
            # Route audit: method + path must be unique and no legacy /tmp handlers may remain.
            pairs = []
            legacy = []
            for route in app.routes:
                path = getattr(route, "path", None)
                methods = sorted(getattr(route, "methods", set()) or set())
                endpoint = getattr(getattr(route, "endpoint", None), "__name__", "")
                for method in methods:
                    pairs.append((method, path))
                if endpoint in {"health", "upload", "delete_file", "download_file"}:
                    legacy.append({"path": path, "endpoint": endpoint})
            duplicates = [
                {"method": method, "path": path, "count": count}
                for (method, path), count in Counter(pairs).items()
                if count > 1
            ]
            result["tests"]["routes"] = {
                "ok": not duplicates and not legacy,
                "routeCount": len(pairs),
                "duplicates": duplicates,
                "legacyHandlers": legacy,
            }

            # PostgreSQL load and checksum.
            with psycopg.connect(database_url(), autocommit=True, connect_timeout=12) as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS vaelith_retest_probe(id TEXT PRIMARY KEY,value TEXT NOT NULL,n INTEGER NOT NULL DEFAULT 0)"
                )
                rows = [(f"{probe_id}-{i}", f"value-{i}", i) for i in range(2000)]
                with connection.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO vaelith_retest_probe(id,value,n) VALUES(%s,%s,%s)", rows
                    )
                count, checksum = connection.execute(
                    "SELECT COUNT(*),COALESCE(SUM(n),0) FROM vaelith_retest_probe WHERE id LIKE %s",
                    (probe_id + "-%",),
                ).fetchone()
                connection.execute(
                    "UPDATE vaelith_retest_probe SET n=n+1 WHERE id LIKE %s", (probe_id + "-%",)
                )
                updated_checksum = connection.execute(
                    "SELECT COALESCE(SUM(n),0) FROM vaelith_retest_probe WHERE id LIKE %s",
                    (probe_id + "-%",),
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO vaelith_retest_probe(id,value,n) VALUES(%s,%s,0)",
                    (probe_id, "shared-value"),
                )
            result["tests"]["postgresLoad"] = {
                "ok": count == 2000 and checksum == 1999000 and updated_checksum == 2001000,
                "inserted": count,
                "checksum": checksum,
                "updatedChecksum": updated_checksum,
            }

            # Cross-instance reads against the real production hostname.
            base = str(request.base_url).rstrip("/")
            read_url = f"{base}/api/internal/retest/read"
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, trust_env=False) as client:
                responses = await asyncio.gather(*[
                    client.get(read_url, params={"token": token, "probe_id": probe_id}, headers={"cache-control": "no-cache"})
                    for _ in range(48)
                ], return_exceptions=True)
            parsed = []
            errors = []
            for response in responses:
                if isinstance(response, Exception):
                    errors.append(f"{type(response).__name__}: {response}")
                    continue
                try:
                    data = response.json()
                except Exception:
                    errors.append(f"HTTP {response.status_code}: resposta inválida")
                    continue
                parsed.append(data)
                if response.status_code != 200:
                    errors.append(f"HTTP {response.status_code}: {data}")
            instances = sorted({item.get("instance") for item in parsed if item.get("instance")})
            misses = sum(1 for item in parsed if not item.get("found"))
            wrong = sum(1 for item in parsed if item.get("found") and item.get("value") != "shared-value")
            result["tests"]["crossInstance"] = {
                "ok": len(parsed) == 48 and not errors and misses == 0 and wrong == 0,
                "requests": 48,
                "responses": len(parsed),
                "instanceCount": len(instances),
                "misses": misses,
                "wrongValues": wrong,
                "errors": errors[:5],
            }

            owner = auth._owner()
            if not owner:
                raise RuntimeError("Conta proprietária não encontrada.")
            session = auth._sign_user(owner, True)
            cookies = {"vaelith_session": session}

            # Unauthenticated protection plus authenticated end-to-end operational flow.
            async with httpx.AsyncClient(timeout=45.0, follow_redirects=False, trust_env=False) as client:
                unauth = await client.get(f"{base}/api/projects")
                created = await client.post(
                    f"{base}/api/projects",
                    cookies=cookies,
                    json={"name": "VAELITH RETEST TEMPORÁRIO", "client": "Teste automático", "location": "Ambiente isolado"},
                )
                created_data = created.json() if created.headers.get("content-type", "").startswith("application/json") else {}
                project_id = str(created_data.get("id", ""))
                listed = await client.get(f"{base}/api/projects", cookies=cookies)
                listed_data = listed.json() if listed.status_code == 200 else []
                issue = await client.post(
                    f"{base}/api/projects/{project_id}/operational/issues",
                    cookies=cookies,
                    json={
                        "title": "Ocorrência sintética do reteste",
                        "description": "Registro temporário para validar o fluxo completo.",
                        "issueType": "risco",
                        "severity": "alta",
                        "location": "Ambiente de teste",
                        "disciplines": ["ARQ", "EST"],
                        "assignee": "Validação automática",
                    },
                )
                dashboard = await client.get(
                    f"{base}/api/projects/{project_id}/operational/dashboard", cookies=cookies
                )
                compatibility = await client.post(
                    f"{base}/api/projects/{project_id}/compatibility", cookies=cookies
                )
                latest = await client.get(
                    f"{base}/api/projects/{project_id}/compatibility/latest", cookies=cookies
                )

                # Verify the actual configured limit: exact 50 MB accepted for signing,
                # 50 MB + 1 byte and 250 MB rejected before upload.
                exact_limit = storage.MAX_FILE_MB * 1024 * 1024
                sign_exact = await client.post(
                    f"{base}/api/projects/{project_id}/uploads/sign",
                    cookies=cookies,
                    json={"name": "LIMITE_R01.ifc", "size": exact_limit, "mime": "application/octet-stream"},
                )
                sign_over = await client.post(
                    f"{base}/api/projects/{project_id}/uploads/sign",
                    cookies=cookies,
                    json={"name": "ACIMA_R01.ifc", "size": exact_limit + 1, "mime": "application/octet-stream"},
                )
                sign_250 = await client.post(
                    f"{base}/api/projects/{project_id}/uploads/sign",
                    cookies=cookies,
                    json={"name": "250MB_R01.ifc", "size": 250 * 1024 * 1024, "mime": "application/octet-stream"},
                )

                # Real physical lifecycle in Supabase with 2 MB.
                sign_real = await client.post(
                    f"{base}/api/projects/{project_id}/uploads/sign",
                    cookies=cookies,
                    json={"name": "ARQ_RETEST_R01.pdf", "size": len(actual_payload), "mime": "application/pdf"},
                )
                sign_data = sign_real.json() if sign_real.status_code == 200 else {}
                file_id = str(sign_data.get("fileId", ""))
                signed_url = str(sign_data.get("signedUrl", ""))
                object_path = str(sign_data.get("path", ""))
                put = await client.put(
                    signed_url,
                    content=actual_payload,
                    headers={"content-type": "application/pdf"},
                    follow_redirects=True,
                ) if signed_url else None
                object_uploaded = bool(put and 200 <= put.status_code < 300)
                confirm = await client.post(
                    f"{base}/api/projects/{project_id}/uploads/confirm",
                    cookies=cookies,
                    json={
                        "fileId": file_id,
                        "path": object_path,
                        "name": "ARQ_RETEST_R01.pdf",
                        "size": len(actual_payload),
                        "mime": "application/pdf",
                    },
                ) if object_uploaded else None
                download = await client.get(
                    f"{base}/api/projects/{project_id}/files/{file_id}/download",
                    cookies=cookies,
                    follow_redirects=True,
                ) if confirm and confirm.status_code == 200 else None
                delete = await client.delete(
                    f"{base}/api/projects/{project_id}/files/{file_id}", cookies=cookies
                ) if download and download.status_code == 200 else None

            dashboard_data = dashboard.json() if dashboard.status_code == 200 else {}
            result["tests"]["operationalFlow"] = {
                "ok": all([
                    unauth.status_code == 401,
                    created.status_code == 200,
                    listed.status_code == 200,
                    any(item.get("id") == project_id for item in listed_data),
                    issue.status_code == 200,
                    dashboard.status_code == 200,
                    int(dashboard_data.get("openIssues", 0)) >= 1,
                    compatibility.status_code == 200,
                    latest.status_code == 200,
                ]),
                "unauthenticated": unauth.status_code,
                "createProject": created.status_code,
                "listProjects": listed.status_code,
                "createIssue": issue.status_code,
                "dashboard": dashboard.status_code,
                "openIssues": dashboard_data.get("openIssues"),
                "compatibility": compatibility.status_code,
                "latestCompatibility": latest.status_code,
            }
            result["tests"]["fileLimit"] = {
                "ok": sign_exact.status_code == 200 and sign_over.status_code == 413 and sign_250.status_code == 413,
                "configuredMb": storage.MAX_FILE_MB,
                "exactLimitStatus": sign_exact.status_code,
                "oneByteOverStatus": sign_over.status_code,
                "twoHundredFiftyMbStatus": sign_250.status_code,
            }
            result["tests"]["storageLifecycle"] = {
                "ok": all([
                    sign_real.status_code == 200,
                    object_uploaded,
                    confirm is not None and confirm.status_code == 200,
                    download is not None and download.status_code == 200,
                    download is not None and download.content == actual_payload,
                    delete is not None and delete.status_code == 204,
                ]),
                "signed": sign_real.status_code,
                "uploaded": object_uploaded,
                "confirmed": confirm.status_code if confirm else None,
                "downloaded": download.status_code if download else None,
                "bytesVerified": len(download.content) if download and download.content == actual_payload else 0,
                "deleted": delete.status_code if delete else None,
            }

            result["ok"] = all(test.get("ok") for test in result["tests"].values())
            result["durationSeconds"] = round(time.perf_counter() - started, 3)
            return result
        finally:
            try:
                if project_id:
                    _cleanup_project(project_id)
                    result["cleanup"]["project"] = True
            except Exception as exc:
                result["cleanup"]["project"] = f"{type(exc).__name__}: {exc}"
            try:
                with psycopg.connect(database_url(), autocommit=True, connect_timeout=12) as connection:
                    connection.execute("DELETE FROM vaelith_retest_probe WHERE id=%s OR id LIKE %s", (probe_id, probe_id + "-%"))
                result["cleanup"]["databaseProbe"] = True
            except Exception as exc:
                result["cleanup"]["databaseProbe"] = f"{type(exc).__name__}: {exc}"
