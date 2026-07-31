from __future__ import annotations

import hashlib
import traceback
from uuid import uuid4

from fastapi import FastAPI, HTTPException

TOKEN_SHA256 = "dbcf82a753974f393b168be4559d9926e45984dc51169b48848f74751aaac3df"


def install(app: FastAPI) -> None:
    @app.get("/api/internal/pdf-transaction-test", include_in_schema=False)
    def test(token: str):
        if hashlib.sha256(token.encode()).hexdigest() != TOKEN_SHA256:
            raise HTTPException(404, "Not Found")
        import professional_auth_v3 as auth
        import server
        import complete_runtime_v1 as runtime

        owner = auth._owner()
        pid = uuid4().hex
        try:
            with server.conn() as c:
                c.execute(
                    "INSERT INTO projects VALUES(?,?,?,?,?,?,?)",
                    (pid, owner["id"], "PDF PROBE", "Cliente teste", "Betim/MG", "Coordenação", server.now()),
                )
            snapshot = runtime.report_snapshot(pid)
            try:
                payload = runtime.render_report_pdf(snapshot, "Relatório de teste PDF")
                return {
                    "ok": payload.startswith(b"%PDF"),
                    "bytes": len(payload),
                    "prefix": payload[:8].hex(),
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "exceptionType": type(exc).__name__,
                    "exception": str(exc),
                    "traceback": traceback.format_exc()[-10000:],
                }
        finally:
            with server.conn() as c:
                c.execute("DELETE FROM project_reports WHERE project_id=?", (pid,))
                c.execute("DELETE FROM audit_events WHERE project_id=?", (pid,))
                c.execute("DELETE FROM projects WHERE id=?", (pid,))
