from __future__ import annotations

import hashlib
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException

TOKEN_SHA256 = "dbcf82a753974f393b168be4559d9926e45984dc51169b48848f74751aaac3df"


def install(app: FastAPI) -> None:
    @app.get("/api/internal/revision-transaction-test", include_in_schema=False)
    async def test(token: str):
        if hashlib.sha256(token.encode()).hexdigest() != TOKEN_SHA256:
            raise HTTPException(404, "Not Found")
        import professional_auth_v3 as auth
        import server
        owner = auth._owner()
        cookie = {"vaelith_session": auth._sign_user(owner, True)}
        pid = uuid4().hex
        f1, f2 = uuid4().hex, uuid4().hex
        try:
            with server.conn() as c:
                c.execute("INSERT INTO projects VALUES(?,?,?,?,?,?,?)", (pid, owner["id"], "REVISION PROBE", "", "", "Teste", server.now()))
                for fid, revision in ((f1, "R01"), (f2, "R02")):
                    c.execute(
                        "INSERT INTO files(id,project_id,name,ext,size,discipline,revision,uploaded,discipline_code,checksum,storage_path,mime) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (fid, pid, f"ARQ_TESTE_{revision}.pdf", ".pdf", 100, "Arquitetura", revision, server.now(), "ARQ", "", "", "application/pdf"),
                    )
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="https://vaelith.local", cookies=cookie) as client:
                before = await client.get(f"/api/projects/{pid}/revisions")
                patch = await client.patch(f"/api/projects/{pid}/revisions/{f2}", json={"status":"active","approved":True,"notes":"Teste"})
                after = await client.get(f"/api/projects/{pid}/revisions")
            return {
                "before": {"status": before.status_code, "body": before.text[:3000]},
                "patch": {"status": patch.status_code, "body": patch.text[:3000]},
                "after": {"status": after.status_code, "body": after.text[:3000]},
            }
        finally:
            with server.conn() as c:
                c.execute("DELETE FROM document_controls WHERE project_id=?", (pid,))
                c.execute("DELETE FROM files WHERE project_id=?", (pid,))
                c.execute("DELETE FROM projects WHERE id=?", (pid,))
