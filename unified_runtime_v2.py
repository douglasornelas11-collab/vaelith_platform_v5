from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Cookie, FastAPI, HTTPException, Request

STATUSES = {"identificada", "em_analise", "aguardando_responsavel", "solucao_proposta", "solucao_aprovada", "projeto_revisado", "liberada_execucao", "executada", "verificada", "encerrada"}
SEVERITIES = {"baixa", "media", "alta", "critica"}
TYPES = {"incompatibilidade", "nao_conformidade", "risco", "mudanca", "restricao", "pendencia", "solicitacao_informacao", "problema_campo"}


def srv():
    import server
    return server


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse(raw: bytes) -> dict:
    try:
        data = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "JSON inválido.") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "O corpo deve ser um objeto JSON.")
    return data


def ensure_schema() -> None:
    with srv().conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS operational_issues(
          id TEXT PRIMARY KEY,project_id TEXT NOT NULL,analysis_id TEXT,code TEXT NOT NULL,
          title TEXT NOT NULL,description TEXT NOT NULL,issue_type TEXT NOT NULL,severity TEXT NOT NULL,
          status TEXT NOT NULL,location TEXT,disciplines TEXT NOT NULL,assignee TEXT,due_date TEXT,
          created_by TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,closed_at TEXT);
        CREATE TABLE IF NOT EXISTS issue_history(
          id TEXT PRIMARY KEY,issue_id TEXT NOT NULL,from_status TEXT,to_status TEXT NOT NULL,
          actor TEXT NOT NULL,comment TEXT,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS issue_decisions(
          id TEXT PRIMARY KEY,issue_id TEXT NOT NULL,title TEXT NOT NULL,rationale TEXT NOT NULL,
          decided_by TEXT NOT NULL,approved INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS issue_impacts(
          id TEXT PRIMARY KEY,issue_id TEXT NOT NULL,cost_amount REAL NOT NULL DEFAULT 0,
          currency TEXT NOT NULL DEFAULT 'BRL',schedule_days INTEGER NOT NULL DEFAULT 0,
          activity_reference TEXT,basis TEXT NOT NULL,confidence TEXT NOT NULL DEFAULT 'estimado',created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_operational_issues_project ON operational_issues(project_id);
        CREATE INDEX IF NOT EXISTS idx_operational_issues_status ON operational_issues(status);
        CREATE INDEX IF NOT EXISTS idx_issue_history_issue ON issue_history(issue_id);
        CREATE INDEX IF NOT EXISTS idx_issue_impacts_issue ON issue_impacts(issue_id);
        """)


def context(pid: str, token: str | None):
    server = srv()
    user = server.require_user(token)
    server.require_project(pid, user["id"])
    ensure_schema()
    return server, user


def find_issue(c, pid: str, issue_id: str):
    row = c.execute("SELECT * FROM operational_issues WHERE id=? AND project_id=?", (issue_id, pid)).fetchone()
    if not row:
        raise HTTPException(404, "Ocorrência não encontrada.")
    return row


def issue_json(row) -> dict:
    data = dict(row)
    try:
        data["disciplines"] = json.loads(data.get("disciplines") or "[]")
    except json.JSONDecodeError:
        data["disciplines"] = []
    return data


def install(app: FastAPI) -> None:
    @app.get("/api/projects/{pid}/operational/dashboard")
    def dashboard(pid: str, vaelith_session: str | None = Cookie(None)):
        server, _ = context(pid, vaelith_session)
        with server.conn() as c:
            issues = c.execute("SELECT * FROM operational_issues WHERE project_id=? ORDER BY created DESC", (pid,)).fetchall()
            impacts = c.execute("SELECT i.cost_amount,i.schedule_days FROM issue_impacts i JOIN operational_issues o ON o.id=i.issue_id WHERE o.project_id=?", (pid,)).fetchall()
        by_status, by_severity = {}, {"baixa": 0, "media": 0, "alta": 0, "critica": 0}
        for item in issues:
            by_status[item["status"]] = by_status.get(item["status"], 0) + 1
            by_severity[item["severity"]] = by_severity.get(item["severity"], 0) + 1
        return {"projectId": pid, "totalIssues": len(issues), "openIssues": sum(i["status"] != "encerrada" for i in issues), "criticalIssues": by_severity["critica"], "estimatedCost": round(sum(float(i["cost_amount"] or 0) for i in impacts), 2), "estimatedDays": sum(int(i["schedule_days"] or 0) for i in impacts), "byStatus": by_status, "bySeverity": by_severity, "recent": [issue_json(i) for i in issues[:6]]}

    @app.get("/api/projects/{pid}/operational/issues")
    def list_issues(pid: str, vaelith_session: str | None = Cookie(None)):
        server, _ = context(pid, vaelith_session)
        with server.conn() as c:
            rows = c.execute("SELECT * FROM operational_issues WHERE project_id=? ORDER BY created DESC", (pid,)).fetchall()
        return [issue_json(row) for row in rows]

    @app.post("/api/projects/{pid}/operational/issues")
    async def create_issue(pid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        server, user = context(pid, vaelith_session)
        data = parse(await request.body())
        title, description = str(data.get("title", "")).strip(), str(data.get("description", "")).strip()
        issue_type, severity = str(data.get("issueType", "incompatibilidade")), str(data.get("severity", "media"))
        if not title or not description:
            raise HTTPException(400, "Informe título e descrição.")
        if issue_type not in TYPES or severity not in SEVERITIES:
            raise HTTPException(400, "Tipo ou criticidade inválidos.")
        disciplines = data.get("disciplines") or []
        if not isinstance(disciplines, list):
            raise HTTPException(400, "Disciplinas devem ser uma lista.")
        issue_id, created = uuid4().hex, now()
        code = f"VLT-{created[:4]}-{issue_id[:6].upper()}"
        values = (issue_id, pid, data.get("analysisId") or None, code, title, description, issue_type, severity, "identificada", str(data.get("location") or "").strip() or None, json.dumps(disciplines, ensure_ascii=False), str(data.get("assignee") or "").strip() or None, str(data.get("dueDate") or "").strip() or None, user["id"], created, created, None)
        with server.conn() as c:
            c.execute("INSERT INTO operational_issues VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
            c.execute("INSERT INTO issue_history VALUES(?,?,?,?,?,?,?)", (uuid4().hex, issue_id, None, "identificada", user["name"], "Ocorrência criada.", created))
            row = find_issue(c, pid, issue_id)
        return issue_json(row)

    @app.patch("/api/projects/{pid}/operational/issues/{issue_id}/status")
    async def change_status(pid: str, issue_id: str, request: Request, vaelith_session: str | None = Cookie(None)):
        server, user = context(pid, vaelith_session)
        data, changed = parse(await request.body()), now()
        target = str(data.get("status", ""))
        if target not in STATUSES:
            raise HTTPException(400, "Status inválido.")
        with server.conn() as c:
            row = find_issue(c, pid, issue_id)
            c.execute("UPDATE operational_issues SET status=?,updated=?,closed_at=? WHERE id=?", (target, changed, changed if target == "encerrada" else None, issue_id))
            c.execute("INSERT INTO issue_history VALUES(?,?,?,?,?,?,?)", (uuid4().hex, issue_id, row["status"], target, user["name"], str(data.get("comment") or "").strip() or None, changed))
            row = find_issue(c, pid, issue_id)
        return issue_json(row)

    @app.post("/api/projects/{pid}/operational/issues/{issue_id}/decisions")
    async def decision(pid: str, issue_id: str, request: Request, vaelith_session: str | None = Cookie(None)):
        server, user = context(pid, vaelith_session)
        data = parse(await request.body())
        title, rationale = str(data.get("title", "")).strip(), str(data.get("rationale", "")).strip()
        if not title or not rationale:
            raise HTTPException(400, "Informe título e justificativa.")
        decision_id = uuid4().hex
        with server.conn() as c:
            find_issue(c, pid, issue_id)
            c.execute("INSERT INTO issue_decisions VALUES(?,?,?,?,?,?,?)", (decision_id, issue_id, title, rationale, user["name"], 1 if data.get("approved") else 0, now()))
        return {"id": decision_id, "issueId": issue_id, "approved": bool(data.get("approved"))}

    @app.post("/api/projects/{pid}/operational/issues/{issue_id}/impacts")
    async def impact(pid: str, issue_id: str, request: Request, vaelith_session: str | None = Cookie(None)):
        server, _ = context(pid, vaelith_session)
        data = parse(await request.body())
        try:
            cost, days = max(float(data.get("costAmount") or 0), 0), max(int(data.get("scheduleDays") or 0), 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Valores de impacto inválidos.") from exc
        basis = str(data.get("basis", "")).strip()
        if not basis:
            raise HTTPException(400, "Informe a memória ou base do impacto.")
        impact_id = uuid4().hex
        with server.conn() as c:
            find_issue(c, pid, issue_id)
            c.execute("INSERT INTO issue_impacts VALUES(?,?,?,?,?,?,?,?,?)", (impact_id, issue_id, cost, str(data.get("currency") or "BRL")[:3].upper(), days, str(data.get("activityReference") or "").strip() or None, basis, str(data.get("confidence") or "estimado"), now()))
        return {"id": impact_id, "issueId": issue_id, "costAmount": cost, "scheduleDays": days}

    @app.get("/api/projects/{pid}/operational/workflow")
    def workflow(pid: str, vaelith_session: str | None = Cookie(None)):
        context(pid, vaelith_session)
        names = ["Empreendimento", "Base documental", "Compatibilização", "Ocorrências", "Revisões", "Impactos", "Orçamento", "Planejamento", "Mudanças", "Relatório e liberação", "VAELITH Intelligence"]
        return {"projectId": pid, "steps": [{"order": i + 1, "name": name} for i, name in enumerate(names)]}
