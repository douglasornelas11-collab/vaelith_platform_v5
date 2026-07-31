from __future__ import annotations

import hashlib
from urllib.parse import quote

from fastapi import FastAPI, HTTPException

TOKEN_SHA256 = "dbcf82a753974f393b168be4559d9926e45984dc51169b48848f74751aaac3df"

OBJECTS = [
    "projects/55e3cd4a6bad4e16b370b8c2788a7c40/4c58e1e235db4faa8cce63cab565b527/3547e33bbd3f46aba760da4dcfeb6871.ifc",
    "projects/55e3cd4a6bad4e16b370b8c2788a7c40/4c58e1e235db4faa8cce63cab565b527/719dde8e46ab426fb06cc681587af2ec.ifc",
    "projects/55e3cd4a6bad4e16b370b8c2788a7c40/4c58e1e235db4faa8cce63cab565b527/e2d6cd0587ed427f9f4692463e29301b.pdf",
    "projects/55e3cd4a6bad4e16b370b8c2788a7c40/4c58e1e235db4faa8cce63cab565b527/5c9d6417c33d44ca9302b84036057f7a.pdf",
    "projects/55e3cd4a6bad4e16b370b8c2788a7c40/54bf2f33916742c0b0618e66c3aa5581/0d28de4e194442878e4434f3865fac20.ifc",
    "projects/55e3cd4a6bad4e16b370b8c2788a7c40/54bf2f33916742c0b0618e66c3aa5581/0921d8881c2a4876b52bbb3b651b4f35.ifc",
    "projects/55e3cd4a6bad4e16b370b8c2788a7c40/54bf2f33916742c0b0618e66c3aa5581/78198f49929045b99ef76ba9c0d4b5fa.pdf",
    "projects/55e3cd4a6bad4e16b370b8c2788a7c40/54bf2f33916742c0b0618e66c3aa5581/0c166934b155434a89346285f6d02806.pdf",
]


def install(app: FastAPI) -> None:
    @app.get("/api/internal/orphan-storage-cleanup", include_in_schema=False)
    def cleanup(token: str):
        if hashlib.sha256(token.encode()).hexdigest() != TOKEN_SHA256:
            raise HTTPException(404, "Not Found")
        import supabase_runtime as storage

        results = []
        for path in OBJECTS:
            response = storage._request(
                "DELETE",
                f"/object/{quote(storage.BUCKET, safe='')}/{quote(path, safe='/')}",
            )
            results.append(
                {
                    "path": path,
                    "status": response.status_code,
                    "ok": response.status_code in {200, 204, 404},
                    "detail": response.text[:180],
                }
            )
        return {
            "ok": all(item["ok"] for item in results),
            "attempted": len(results),
            "results": results,
        }
