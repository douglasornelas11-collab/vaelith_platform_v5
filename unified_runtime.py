from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Cookie, FastAPI, HTTPException, Request


ISSUE_STATUSES = {
    "identificada",
    "em_analise",
    "aguardando_responsavel",
    "solucao_proposta",
    "solucao_aprovada",
    "projeto_revisado",
    "liberada_execucao",
    "executada",
    "verificada",
    "encerrada",
}
SEVERITIES = {"baixa", "media", "alta", "critica"}
ISSUE_TYPES = {
    "incompatibilidade",
    "nao_conformidade",
    "risco",
    "mudanca",
    "restricao",
    "pendencia",
    "solicitacao_informacao",
    "problema_campo",
}


def _server():
    import server

    return server


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _body(request_body: bytes) -> dict:
    try:
        data = json.loads(request_body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "JSON inválido.") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "O corpo deve ser um objeto JSON.")
    return data


def _init_schema() -> None:
    srv = _server()
    with srv.conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS operational_issues(
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                analysis_id TEXT,
                code TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                location TEXT,
                disciplines TEXT NOT NULL,
                assignee TEXT,
                due_date TEXT,
                created_by TEXT NOT NULL,
                created TEXT NOT NULL,
                updated TEXT NOT NULL,
                closed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS issue_history(
                id TEXT PRIMARY KEY,
                issue_id TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT NOT NULL,
                actor TEXT NOT NULL,
                comment TEXT,
                created TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS issue_decisions(
                id TEXT PRIMARY KEY,
                issue_id TEXT NOT NULL,
                title TEXT NOT NULL,
                rationale TEXT NOT NULL,
                decided_by TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0,
                created TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS issue_impacts(
                id TEXT PRIMARY KEY,
                issue_id TEXT NOT NULL,
                cost_amount REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'BRL',
                schedule_days INTEGER NOT NULL DEFAULT 0,
                activity_reference TEXT,
                basis TEXT NOT NULL,
                confidence TEXT NOT NULL DEFAULT 'estimado',
                created TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_operational_issues_project ON operational_issues(project_id);
            CREATE INDEX IF NOT EXISTS idx_operational_issues_status ON operational_issues(status);
            CREATE INDEX IF NOT EXISTS idx_issue_history_issue ON issue_history(issue_id);
            CREATE INDEX IF NOT EXISTS idx_issue_impacts_issue ON issue_impacts(issue_id);
            """
        )


def _project_user(pid: str, token: str | None):
    srv = _server()
    user = srv.require_user(token)
    srv.require_project(pid, user["id"])
    return srv, user


def _issue(c, pid: str, issue_id: str):
    row = c.execute(
        "SELECT * FROM operational_issues WHERE id=? AND project_id=?",
        (issue_id, pid),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Ocorrência não encontrada.")
    return row


def _serialize_issue(row) -> dict:
    data = dict(row)
    try:
        data["disciplines"] = json.loads(data.get("disciplines") or "[]")
    except json.JSONDecodeError:
        data["disciplines"] = []
    return data


def install(app: FastAPI) -> None:
    _init_schema()

    @app.get("/api/projects/{pid}/operational/dashboard")
    def operational_dashboard(pid: str, vaelith_session: str | None = Cookie(None)):
        srv, _ = _project_user(pid, vaelith_session)
        with srv.conn() as c:
            issues = c.execute(
                "SELECT * FROM operational_issues WHERE project_id=? ORDER BY created DESC",
                (pid,),
            ).fetchall()
            impacts = c.execute(
                "SELECT i.cost_amount,i.schedule_days FROM issue_impacts i "
                "JOIN operational_issues o ON o.id=i.issue_id WHERE o.project_id=?",
                (pid,),
            ).fetchall()
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {"baixa": 0, "media": 0, "alta": 0, "critica": 0}
        for issue in issues:
            by_status[issue["status"]] = by_status.get(issue["status"], 0) + 1
            by_severity[issue["severity"]] = by_severity.get(issue["severity"], 0) + 1
        return {
            "projectId": pid,
            "totalIssues": len(issues),
            "openIssues": sum(1 for issue in issues if issue["status"] != "encerrada"),
            "criticalIssues": by_severity.get("critica", 0),
            "estimatedCost": round(sum(float(item["cost_amount"] or 0) for item in impacts), 2),
            "estimatedDays": sum(int(item["schedule_days"] or 0) for item in impacts),
            "byStatus": by_status,
            "bySeverity": by_severity,
            "recent": [_serialize_issue(row) for row in issues[:6]],
        }

    @app.get("/api/projects/{pid}/operational/issues")
    def list_operational_issues(pid: str, vaelith_session: str | None = Cookie(None)):
        srv, _ = _project_user(pid, vaelith_session)
        with srv.conn() as c:
            rows = c.execute(
                "SELECT * FROM operational_issues WHERE project_id=? ORDER BY created DESC",
                (pid,),
            ).fetchall()
        return [_serialize_issue(row) for row in rows]

    @app.post("/api/projects/{pid}/operational/issues")
    async def create_operational_issue(pid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        srv, user = _project_user(pid, vaelith_session)
        data = _body(await request.body())
        title = str(data.get("title", "")).strip()
        description = str(data.get("description", "")).strip()
        issue_type = str(data.get("issueType", "incompatibilidade")).strip()
        severity = str(data.get("severity", "media")).strip()
        if not title or not description:
            raise HTTPException(400, "Informe título e descrição.")
        if issue_type not in ISSUE_TYPES:
            raise HTTPException(400, "Tipo de ocorrência inválido.")
        if severity not in SEVERITIES:
            raise HTTPException(400, "Criticidade inválida.")
        issue_id = uuid4().hex
        created = _now()
        code = f"VLT-{created[:4]}-{issue_id[:6].upper()}"
        disciplines = data.get("disciplines") or []
        if not isinstance(disciplines, list):
            raise HTTPException(400, "Disciplinas devem ser uma lista.")
        with srv.conn() as c:
            c.execute(
                "INSERT INTO operational_issues VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    issue_id,
                    pid,
                    str(data.get("analysisId") or "") or None,
                    code,
                    title,
                    description,
                    issue_type,
                    severity,
                    "identificada",
                    str(data.get("location") or "").strip() or None,
                    json.dumps(disciplines, ensure_ascii=False),
                    str(data.get("assignee") or "").strip() or None,
                    str(data.get("dueDate") or "").strip() or None,
                    user["id"],
                    created,
                    created,
                    None,
                ),
            )
            c.execute(
                "INSERT INTO issue_history VALUES(?,?,?,?,?,?,?)",
                (uuid4().hex, issue_id, None, "identificada", user["name"], "Ocorrência criada.", created),
            )
            row = _issue(c, pid, issue_id)
        return _serialize_issue(row)

    @app.patch("/api/projects/{pid}/operational/issues/{issue_id}/status")
    async def update_operational_status(pid: str, issue_id: str, request: Request, vaelith_session: str | None = Cookie(None)):
        srv, user = _project_user(pid, vaelith_session)
        data = _body(await request.body())
        target = str(data.get("status", "")).strip()
        if target not in ISSUE_STATUSES:
            raise HTTPException(400, "Status inválido.")
        changed = _now()
        with srv.conn() as c:
            row = _issue(c, pid, issue_id)
            previous = row["status"]
            closed_at = changed if target == "encerrada" else None
            c.execute(
                "UPDATE operational_issues SET status=?,updated=?,closed_at=? WHERE id=?",
                (target, changed, closed_at, issue_id),
            )
            c.execute(
                "INSERT INTO issue_history VALUES(?,?,?,?,?,?,?)",
                (
                    uuid4().hex,
                    issue_id,
                    previous,
                    target,
                    user["name"],
                    str(data.get("comment") or "").strip() or None,
                    changed,
                ),
            )
            updated = _issue(c, pid, issue_id)
        return _serialize_issue(updated)

    @app.post("/api/projects/{pid}/operational/issues/{issue_id}/decisions")
    async def create_decision(pid: str, issue_id: str, request: Request, vaelith_session: str | None = Cookie(None)):
        srv, user = _project_user(pid, vaelith_session)
        data = _body(await request.body())
        title = str(data.get("title", "")).strip()
        rationale = str(data.get("rationale", "")).strip()
        if not title or not rationale:
            raise HTTPException(400, "Informe título e justificativa da decisão.")
        decision_id = uuid4().hex
        with srv.conn() as c:
            _issue(c, pid, issue_id)
            c.execute(
                "INSERT INTO issue_decisions VALUES(?,?,?,?,?,?,?)",
                (decision_id, issue_id, title, rationale, user["name"], 1 if data.get("approved") else 0, _now()),
            )
        return {"id": decision_id, "issueId": issue_id, "approved": bool(data.get("approved"))}

    @app.post("/api/projects/{pid}/operational/issues/{issue_id}/impacts")
    async def create_impact(pid: str, issue_id: str, request: Request, vaelith_session: str | None = Cookie(None)):
        srv, _ = _project_user(pid, vaelith_session)
        data = _body(await request.body())
        try:
            cost = float(data.get("costAmount") or 0)
            days = int(data.get("scheduleDays") or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Valores de impacto inválidos.") from exc
        basis = str(data.get("basis", "")).strip()
        if not basis:
            raise HTTPException(400, "Informe a memória ou base do impacto.")
        impact_id = uuid4().hex
        with srv.conn() as c:
            _issue(c, pid, issue_id)
            c.execute(
                "INSERT INTO issue_impacts VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    impact_id,
                    issue_id,
                    max(cost, 0),
                    str(data.get("currency") or "BRL")[:3].upper(),
                    max(days, 0),
                    str(data.get("activityReference") or "").strip() or None,
                    basis,
                    str(data.get("confidence") or "estimado").strip(),
                    _now(),
                ),
            )
        return {"id": impact_id, "issueId": issue_id, "costAmount": max(cost, 0), "scheduleDays": max(days, 0)}

    @app.get("/api/projects/{pid}/operational/workflow")
    def operational_workflow(pid: str, vaelith_session: str | None = Cookie(None)):
        _project_user(pid, vaelith_session)
        return {
            "projectId": pid,
            "steps": [
                {"id": "project", "name": "Empreendimento", "order": 1},
                {"id": "documents", "name": "Base documental", "order": 2},
                {"id": "compatibility", "name": "Compatibilização", "order": 3},
                {"id": "issues", "name": "Ocorrências", "order": 4},
                {"id": "revisions", "name": "Revisões", "order": 5},
                {"id": "impacts", "name": "Impactos", "order": 6},
                {"id": "budget", "name": "Orçamento", "order": 7},
                {"id": "planning", "name": "Planejamento", "order": 8},
                {"id": "changes", "name": "Mudanças", "order": 9},
                {"id": "report", "name": "Relatório e liberação", "order": 10},
                {"id": "intelligence", "name": "VAELITH Intelligence", "order": 11},
            ],
        }
