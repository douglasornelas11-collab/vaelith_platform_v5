"""Runtime database bridge for Vaelith.

Python imports sitecustomize automatically during startup. When a PostgreSQL
connection URL is available, this module replaces sqlite3.connect with a small
compatibility layer so the existing application persists its records in Neon
without a risky all-at-once rewrite of every query.
"""
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
