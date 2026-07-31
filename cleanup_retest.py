from __future__ import annotations

import hashlib

from fastapi import FastAPI, HTTPException

TOKEN_SHA256 = "59d9de9dc57b1cf47f67a4e44f496818ae26df007999e7c917b760bf7d08f3b2"


def install(app: FastAPI) -> None:
    @app.get("/api/internal/retest-cleanup", include_in_schema=False)
    def cleanup_retest(token: str):
        if hashlib.sha256(token.encode("utf-8")).hexdigest() != TOKEN_SHA256:
            raise HTTPException(404, "Not Found")
        from persistent_runtime import database_url
        import psycopg
        with psycopg.connect(database_url(), autocommit=True, connect_timeout=12) as connection:
            connection.execute("DROP TABLE IF EXISTS vaelith_retest_probe")
        return {"ok": True, "tableRemoved": True}
