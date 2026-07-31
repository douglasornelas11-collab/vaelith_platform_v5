from __future__ import annotations

import os
import re
from typing import Any, Iterable


_DB_ENV_NAMES = (
    "VAELITH_DB_URL",
    "DATABASE_URL",
    "POSTGRES_URL",
    "NEON_DATABASE_URL",
    "STORAGE_URL",
)


def database_url() -> str:
    for name in _DB_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value.startswith(("postgres://", "postgresql://")):
            return value
    return ""


class HybridRow(dict):
    """PostgreSQL row compatible with sqlite3.Row and numeric indexes."""

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

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount or 0)

    def _columns(self) -> list[str]:
        if not self._cursor.description:
            return []
        columns = []
        for item in self._cursor.description:
            columns.append(getattr(item, "name", item[0]))
        return columns

    def _row(self, raw):
        if raw is None:
            return None
        if isinstance(raw, dict):
            return HybridRow(list(raw.keys()), list(raw.values()))
        return HybridRow(self._columns(), raw)

    def fetchone(self):
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self._cursor.fetchall()]


class ConnectionBridge:
    def __init__(self):
        url = database_url()
        if not url:
            raise RuntimeError("PostgreSQL compartilhado não está configurado.")
        import psycopg

        self._connection = psycopg.connect(url, autocommit=False, connect_timeout=12)
        self.row_factory = None

    @staticmethod
    def _translate(sql: str) -> str:
        # The application uses SQLite qmark placeholders. Its SQL does not use
        # literal question marks, so this translation is deterministic.
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: Iterable[Any] | None = None):
        cursor = self._connection.cursor()
        normalized = sql.strip()
        pragma = re.fullmatch(r"PRAGMA\s+table_info\(([^)]+)\)", normalized, re.I)
        if pragma:
            table = pragma.group(1).strip().strip('"')
            cursor.execute(
                "SELECT ordinal_position-1 AS cid,column_name AS name,data_type AS type,"
                "CASE WHEN is_nullable='NO' THEN 1 ELSE 0 END AS notnull,"
                "column_default AS dflt_value,0 AS pk "
                "FROM information_schema.columns WHERE table_schema='public' "
                "AND table_name=%s ORDER BY ordinal_position",
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


def connect() -> ConnectionBridge:
    return ConnectionBridge()


def ensure_schema() -> None:
    url = database_url()
    if not url:
        raise RuntimeError("Nenhuma URL PostgreSQL válida foi encontrada.")
    import psycopg

    statements = [
        """CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY,name TEXT,email TEXT UNIQUE,salt TEXT,pw TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS sessions(
            token TEXT PRIMARY KEY,user_id TEXT,expires TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS projects(
            id TEXT PRIMARY KEY,user_id TEXT NOT NULL,name TEXT NOT NULL,
            client TEXT,location TEXT,phase TEXT,created TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS files(
            id TEXT PRIMARY KEY,project_id TEXT NOT NULL,name TEXT NOT NULL,
            ext TEXT,size BIGINT,discipline TEXT,revision TEXT,uploaded TEXT,
            discipline_code TEXT DEFAULT 'UNK',checksum TEXT DEFAULT '',
            storage_path TEXT DEFAULT '',mime TEXT DEFAULT 'application/octet-stream'
        )""",
        """CREATE TABLE IF NOT EXISTS analyses(
            id TEXT PRIMARY KEY,project_id TEXT NOT NULL,result TEXT NOT NULL,created TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS budget_items(
            id TEXT PRIMARY KEY,project_id TEXT NOT NULL,file_id TEXT,
            description TEXT,unit TEXT,quantity DOUBLE PRECISION,
            unit_price DOUBLE PRECISION,total DOUBLE PRECISION,category TEXT,created TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS operational_issues(
            id TEXT PRIMARY KEY,project_id TEXT NOT NULL,analysis_id TEXT,code TEXT NOT NULL,
            title TEXT NOT NULL,description TEXT NOT NULL,issue_type TEXT NOT NULL,
            severity TEXT NOT NULL,status TEXT NOT NULL,location TEXT,disciplines TEXT NOT NULL,
            assignee TEXT,due_date TEXT,created_by TEXT NOT NULL,created TEXT NOT NULL,
            updated TEXT NOT NULL,closed_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS issue_history(
            id TEXT PRIMARY KEY,issue_id TEXT NOT NULL,from_status TEXT,to_status TEXT NOT NULL,
            actor TEXT NOT NULL,comment TEXT,created TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS issue_decisions(
            id TEXT PRIMARY KEY,issue_id TEXT NOT NULL,title TEXT NOT NULL,
            rationale TEXT NOT NULL,decided_by TEXT NOT NULL,
            approved INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS issue_impacts(
            id TEXT PRIMARY KEY,issue_id TEXT NOT NULL,
            cost_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'BRL',schedule_days INTEGER NOT NULL DEFAULT 0,
            activity_reference TEXT,basis TEXT NOT NULL,
            confidence TEXT NOT NULL DEFAULT 'estimado',created TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_files_project ON files(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_analyses_project_created ON analyses(project_id,created DESC)",
        "CREATE INDEX IF NOT EXISTS idx_budget_project ON budget_items(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_operational_issues_project ON operational_issues(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_operational_issues_status ON operational_issues(status)",
        "CREATE INDEX IF NOT EXISTS idx_issue_history_issue ON issue_history(issue_id)",
        "CREATE INDEX IF NOT EXISTS idx_issue_decisions_issue ON issue_decisions(issue_id)",
        "CREATE INDEX IF NOT EXISTS idx_issue_impacts_issue ON issue_impacts(issue_id)",
    ]
    with psycopg.connect(url, autocommit=True, connect_timeout=12) as connection:
        for statement in statements:
            connection.execute(statement)


def install() -> None:
    """Make every operational route use the shared PostgreSQL database."""
    ensure_schema()
    import server

    server.conn = connect
    server.APP_VERSION = "8.0-postgresql-operational"
    server.app.version = server.APP_VERSION
