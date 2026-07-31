"""Runtime database and storage bridge for Vaelith."""
from __future__ import annotations

import os
import re
import sqlite3 as _sqlite3
from typing import Any, Iterable


def _database_url() -> str:
    for name in (
        "VAELITH_DB_URL",
        "STORAGE_URL",
        "DATABASE_URL",
        "POSTGRES_URL",
        "NEON_DATABASE_URL",
    ):
        value = os.getenv(name, "").strip()
        if value.startswith(("postgres://", "postgresql://")):
            return value
    return ""


_URL = _database_url()
_ORIGINAL_CONNECT = _sqlite3.connect


class HybridRow(dict):
    """Mapping row that also supports SQLite-style numeric indexes."""

    def __init__(self, columns: list[str], values: Iterable[Any]):
        values_list = list(values)
        super().__init__(zip(columns, values_list))
        self._values = values_list

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class CursorBridge:
    def __init__(self, cursor):
        self._cursor = cursor

    def _row(self, raw):
        if raw is None:
            return None
        columns = [item.name for item in self._cursor.description] if self._cursor.description else []
        return HybridRow(columns, raw)

    def fetchone(self):
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self._cursor.fetchall()]


class ConnectionBridge:
    def __init__(self, url: str):
        import psycopg

        self._connection = psycopg.connect(url, autocommit=False)
        self.row_factory = None

    @staticmethod
    def _translate(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: Iterable[Any] | None = None):
        cursor = self._connection.cursor()
        normalized = sql.strip()
        pragma = re.fullmatch(r"PRAGMA\s+table_info\(([^)]+)\)", normalized, re.I)
        if pragma:
            table = pragma.group(1).strip().strip('"')
            cursor.execute(
                "SELECT ordinal_position-1 AS cid, column_name AS name, "
                "data_type AS type, CASE WHEN is_nullable='NO' THEN 1 ELSE 0 END AS notnull, "
                "column_default AS dflt_value, 0 AS pk "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                (table,),
            )
            return CursorBridge(cursor)
        cursor.execute(self._translate(sql), tuple(params or ()))
        return CursorBridge(cursor)

    def executescript(self, script: str):
        cursor = self._connection.cursor()
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                cursor.execute(statement)
        return CursorBridge(cursor)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._connection.commit()
        else:
            self._connection.rollback()
        self._connection.close()
        return False


def connect(database: str, *args, **kwargs):
    if _URL:
        return ConnectionBridge(_URL)
    return _ORIGINAL_CONNECT(database, *args, **kwargs)


if _URL:
    _sqlite3.connect = connect


# FastAPI is patched before server.py creates the application. Authentication
# is installed later by app.py, after the base application has initialized.
try:
    from fastapi import FastAPI

    _original_init = FastAPI.__init__
    _original_middleware = FastAPI.middleware

    def _vaelith_init(self, *args, **kwargs):
        _original_init(self, *args, **kwargs)
        try:
            from static_runtime import install as install_static

            install_static(self)
        except Exception as exc:
            print(f"VAELITH_STATIC_INSTALL_ERROR: {exc}")
        try:
            from supabase_runtime import install as install_storage

            install_storage(self)
        except Exception as exc:
            print(f"VAELITH_STORAGE_INSTALL_ERROR: {exc}")
        try:
            from unified_runtime_v2 import install as install_unified

            install_unified(self)
        except Exception as exc:
            print(f"VAELITH_UNIFIED_INSTALL_ERROR: {exc}")

    def _vaelith_middleware(self, middleware_type: str):
        decorator = _original_middleware(self, middleware_type)

        def register(func):
            if getattr(func, "__name__", "") != "security_headers":
                return decorator(func)

            async def storage_aware_security_headers(request, call_next):
                response = await func(request, call_next)
                csp = response.headers.get("Content-Security-Policy", "")
                if "connect-src 'self'" in csp:
                    csp = csp.replace(
                        "connect-src 'self'",
                        "connect-src 'self' https://*.supabase.co",
                    )
                response.headers["Content-Security-Policy"] = csp
                return response

            storage_aware_security_headers.__name__ = func.__name__
            return decorator(storage_aware_security_headers)

        return register

    FastAPI.__init__ = _vaelith_init
    FastAPI.middleware = _vaelith_middleware
except Exception as exc:
    print(f"VAELITH_FASTAPI_PATCH_ERROR: {exc}")
