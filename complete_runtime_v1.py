from __future__ import annotations

import io
import json
import math
import os
import re
import tempfile
from collections import defaultdict
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

REVISION_STATUSES = {"active", "superseded", "archived", "review"}
PLANNING_STATUSES = {"not_started", "in_progress", "blocked", "completed", "cancelled"}
CHANGE_STATUSES = {"requested", "in_analysis", "approved", "rejected", "implemented", "verified", "closed"}
REPORT_TYPES = {"executive", "coordination", "operational", "change_control"}
BIM_MODES = {"intersection", "collision", "clearance"}


def srv():
    import server
    return server


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_body(raw: bytes) -> dict:
    try:
        data = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "JSON inválido.") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "O corpo deve ser um objeto JSON.")
    return data


def ensure_schema() -> None:
    with srv().conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS document_controls(
              file_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'review',
              approved INTEGER NOT NULL DEFAULT 0,approved_by TEXT,approved_at TEXT,
              supersedes_file_id TEXT,notes TEXT,updated TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS planning_activities(
              id TEXT PRIMARY KEY,project_id TEXT NOT NULL,code TEXT NOT NULL,name TEXT NOT NULL,
              start_date TEXT,end_date TEXT,duration_days INTEGER NOT NULL DEFAULT 0,
              progress DOUBLE PRECISION NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'not_started',
              owner TEXT,critical INTEGER NOT NULL DEFAULT 0,predecessors TEXT NOT NULL DEFAULT '[]',
              issue_id TEXT,source_file_id TEXT,created TEXT NOT NULL,updated TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS change_requests(
              id TEXT PRIMARY KEY,project_id TEXT NOT NULL,code TEXT NOT NULL,title TEXT NOT NULL,
              description TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'requested',
              requested_by TEXT NOT NULL,approved_by TEXT,cost_delta DOUBLE PRECISION NOT NULL DEFAULT 0,
              schedule_delta INTEGER NOT NULL DEFAULT 0,disciplines TEXT NOT NULL DEFAULT '[]',
              issue_id TEXT,decision TEXT,created TEXT NOT NULL,updated TEXT NOT NULL,approved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS project_reports(
              id TEXT PRIMARY KEY,project_id TEXT NOT NULL,report_type TEXT NOT NULL,title TEXT NOT NULL,
              snapshot TEXT NOT NULL,created_by TEXT NOT NULL,created TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events(
              id TEXT PRIMARY KEY,project_id TEXT,actor TEXT NOT NULL,action TEXT NOT NULL,
              entity_type TEXT NOT NULL,entity_id TEXT,detail TEXT NOT NULL DEFAULT '{}',created TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bim_jobs(
              id TEXT PRIMARY KEY,project_id TEXT NOT NULL,status TEXT NOT NULL,mode TEXT NOT NULL,
              tolerance DOUBLE PRECISION NOT NULL DEFAULT 0.002,input_files TEXT NOT NULL,
              result TEXT,error TEXT,created_by TEXT NOT NULL,created TEXT NOT NULL,
              started TEXT,finished TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_document_controls_project ON document_controls(project_id);
            CREATE INDEX IF NOT EXISTS idx_planning_project ON planning_activities(project_id);
            CREATE INDEX IF NOT EXISTS idx_planning_issue ON planning_activities(issue_id);
            CREATE INDEX IF NOT EXISTS idx_changes_project ON change_requests(project_id);
            CREATE INDEX IF NOT EXISTS idx_reports_project ON project_reports(project_id,created DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_project ON audit_events(project_id,created DESC);
            CREATE INDEX IF NOT EXISTS idx_bim_project ON bim_jobs(project_id,created DESC);
            """
        )


def context(pid: str, token: str | None):
    server = srv()
    user = server.require_user(token)
    project = server.require_project(pid, user["id"])
    ensure_schema()
    return server, user, project


def audit(c, pid: str | None, actor: str, action: str, entity_type: str, entity_id: str | None, detail: dict | None = None):
    c.execute(
        "INSERT INTO audit_events VALUES(?,?,?,?,?,?,?)",
        (
            uuid4().hex,
            pid,
            actor,
            action,
            entity_type,
            entity_id,
            json.dumps(detail or {}, ensure_ascii=False),
            now(),
        ),
    )


def decode_json(value, fallback):
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return fallback


def revision_rank(value: str | None) -> tuple[int, int, str]:
    text = str(value or "").upper().strip()
    match = re.fullmatch(r"([RVP])\s*0*(\d+)", text)
    prefix_order = {"P": 0, "V": 1, "R": 2}
    if match:
        return (prefix_order.get(match.group(1), 0), int(match.group(2)), text)
    return (-1, -1, text)


def revision_payload(pid: str) -> dict:
    server = srv()
    with server.conn() as c:
        files = [dict(row) for row in c.execute(
            "SELECT * FROM files WHERE project_id=? ORDER BY discipline_code,uploaded DESC", (pid,)
        ).fetchall()]
        controls = {
            row["file_id"]: dict(row)
            for row in c.execute("SELECT * FROM document_controls WHERE project_id=?", (pid,)).fetchall()
        }
    groups = []
    conflicts = 0
    pending = 0
    for code in sorted({str(f.get("discipline_code") or "UNK") for f in files}):
        versions = [f for f in files if str(f.get("discipline_code") or "UNK") == code]
        versions.sort(key=lambda item: revision_rank(item.get("revision")), reverse=True)
        active_ids = []
        version_payloads = []
        for index, item in enumerate(versions):
            control = controls.get(item["id"])
            status = control["status"] if control else ("review" if len(versions) > 1 else "active")
            if status == "active":
                active_ids.append(item["id"])
            if status == "review":
                pending += 1
            version_payloads.append(
                {
                    **item,
                    "controlStatus": status,
                    "approved": bool(control and control.get("approved")),
                    "approvedBy": control.get("approved_by") if control else None,
                    "approvedAt": control.get("approved_at") if control else None,
                    "notes": control.get("notes") if control else None,
                    "isLatestByName": index == 0,
                }
            )
        distinct_revisions = sorted({str(v.get("revision") or "Não informada") for v in versions})
        group_conflict = len(active_ids) > 1 or (len(versions) > 1 and not active_ids)
        if group_conflict:
            conflicts += 1
        groups.append(
            {
                "disciplineCode": code,
                "discipline": versions[0].get("discipline") if versions else code,
                "versions": version_payloads,
                "distinctRevisions": distinct_revisions,
                "activeCount": len(active_ids),
                "conflict": group_conflict,
            }
        )
    return {
        "projectId": pid,
        "files": len(files),
        "groups": groups,
        "conflicts": conflicts,
        "pendingReview": pending,
        "controlled": len(controls),
    }


def planning_payload(pid: str) -> dict:
    server = srv()
    with server.conn() as c:
        rows = [dict(row) for row in c.execute(
            "SELECT * FROM planning_activities WHERE project_id=? ORDER BY critical DESC,start_date,name", (pid,)
        ).fetchall()]
    today = date.today().isoformat()
    for row in rows:
        row["predecessors"] = decode_json(row.get("predecessors"), [])
        row["critical"] = bool(row.get("critical"))
        row["progress"] = float(row.get("progress") or 0)
        row["delayed"] = bool(
            row.get("end_date")
            and row["end_date"] < today
            and row["status"] not in {"completed", "cancelled"}
            and row["progress"] < 100
        )
    return {
        "projectId": pid,
        "activities": rows,
        "summary": {
            "total": len(rows),
            "completed": sum(r["status"] == "completed" for r in rows),
            "inProgress": sum(r["status"] == "in_progress" for r in rows),
            "blocked": sum(r["status"] == "blocked" for r in rows),
            "critical": sum(bool(r["critical"]) for r in rows),
            "delayed": sum(bool(r["delayed"]) for r in rows),
            "averageProgress": round(sum(r["progress"] for r in rows) / len(rows), 1) if rows else 0,
        },
    }


def changes_payload(pid: str) -> dict:
    server = srv()
    with server.conn() as c:
        rows = [dict(row) for row in c.execute(
            "SELECT * FROM change_requests WHERE project_id=? ORDER BY created DESC", (pid,)
        ).fetchall()]
    for row in rows:
        row["disciplines"] = decode_json(row.get("disciplines"), [])
        row["cost_delta"] = float(row.get("cost_delta") or 0)
        row["schedule_delta"] = int(row.get("schedule_delta") or 0)
    return {
        "projectId": pid,
        "changes": rows,
        "summary": {
            "total": len(rows),
            "open": sum(r["status"] not in {"rejected", "closed"} for r in rows),
            "approved": sum(r["status"] in {"approved", "implemented", "verified", "closed"} for r in rows),
            "costDelta": round(sum(r["cost_delta"] for r in rows if r["status"] != "rejected"), 2),
            "scheduleDelta": sum(r["schedule_delta"] for r in rows if r["status"] != "rejected"),
        },
    }


def impacts_payload(pid: str) -> dict:
    server = srv()
    with server.conn() as c:
        rows = [dict(row) for row in c.execute(
            """
            SELECT i.*,o.code,o.title,o.severity,o.status,o.assignee,o.location
            FROM issue_impacts i JOIN operational_issues o ON o.id=i.issue_id
            WHERE o.project_id=? ORDER BY i.created DESC
            """,
            (pid,),
        ).fetchall()]
    by_issue = defaultdict(lambda: {"cost": 0.0, "days": 0, "records": 0})
    for row in rows:
        row["cost_amount"] = float(row.get("cost_amount") or 0)
        row["schedule_days"] = int(row.get("schedule_days") or 0)
        bucket = by_issue[row["issue_id"]]
        bucket["cost"] += row["cost_amount"]
        bucket["days"] += row["schedule_days"]
        bucket["records"] += 1
        bucket["code"] = row.get("code")
        bucket["title"] = row.get("title")
        bucket["severity"] = row.get("severity")
    return {
        "projectId": pid,
        "records": rows,
        "byIssue": list(by_issue.values()),
        "summary": {
            "records": len(rows),
            "cost": round(sum(r["cost_amount"] for r in rows), 2),
            "days": sum(r["schedule_days"] for r in rows),
            "issuesAffected": len(by_issue),
            "confirmedCost": round(
                sum(r["cost_amount"] for r in rows if str(r.get("confidence")).lower() == "confirmado"), 2
            ),
        },
    }


def latest_analysis(pid: str) -> dict | None:
    server = srv()
    with server.conn() as c:
        row = c.execute(
            "SELECT result FROM analyses WHERE project_id=? ORDER BY created DESC LIMIT 1", (pid,)
        ).fetchone()
    return decode_json(row["result"], None) if row else None


def report_snapshot(pid: str) -> dict:
    server = srv()
    with server.conn() as c:
        project = dict(c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
        files = [dict(row) for row in c.execute("SELECT * FROM files WHERE project_id=? ORDER BY uploaded", (pid,)).fetchall()]
        issues = [dict(row) for row in c.execute(
            "SELECT * FROM operational_issues WHERE project_id=? ORDER BY severity DESC,created DESC", (pid,)
        ).fetchall()]
        decisions = [dict(row) for row in c.execute(
            """
            SELECT d.*,o.code,o.title AS issue_title FROM issue_decisions d
            JOIN operational_issues o ON o.id=d.issue_id WHERE o.project_id=? ORDER BY d.created DESC
            """, (pid,)
        ).fetchall()]
        budget = [dict(row) for row in c.execute(
            "SELECT * FROM budget_items WHERE project_id=? ORDER BY category,description", (pid,)
        ).fetchall()]
    for issue in issues:
        issue["disciplines"] = decode_json(issue.get("disciplines"), [])
    return {
        "generatedAt": now(),
        "project": project,
        "files": files,
        "analysis": latest_analysis(pid),
        "issues": issues,
        "decisions": decisions,
        "impacts": impacts_payload(pid),
        "planning": planning_payload(pid),
        "changes": changes_payload(pid),
        "revisions": revision_payload(pid),
        "budget": {
            "items": len(budget),
            "total": round(sum(float(item.get("total") or 0) for item in budget), 2),
            "rows": budget,
        },
    }


def render_report_html(snapshot: dict, title: str) -> str:
    project = snapshot["project"]
    analysis = snapshot.get("analysis") or {}
    issues = snapshot.get("issues") or []
    impacts = snapshot["impacts"]["summary"]
    planning = snapshot["planning"]["summary"]
    changes = snapshot["changes"]["summary"]
    file_rows = "".join(
        f"<tr><td>{escape(str(f.get('name') or ''))}</td><td>{escape(str(f.get('discipline') or ''))}</td>"
        f"<td>{escape(str(f.get('revision') or ''))}</td><td>{int(f.get('size') or 0):,}</td></tr>"
        for f in snapshot.get("files", [])
    )
    issue_rows = "".join(
        f"<tr><td>{escape(str(i.get('code') or ''))}</td><td>{escape(str(i.get('title') or ''))}</td>"
        f"<td>{escape(str(i.get('severity') or ''))}</td><td>{escape(str(i.get('status') or ''))}</td></tr>"
        for i in issues
    )
    return f"""<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><title>{escape(title)}</title>
    <style>@page{{size:A4;margin:16mm}}body{{font:12px/1.5 Arial;color:#172018;margin:0}}header{{border-bottom:4px solid #b7ed32;padding-bottom:18px;margin-bottom:22px}}h1{{font-size:26px;margin:0}}h2{{font-size:16px;margin-top:24px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.card{{border:1px solid #d9dfd8;border-radius:8px;padding:12px}}.card b{{display:block;font-size:20px}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #e2e6e1;padding:7px;text-align:left}}th{{background:#f1f4ef}}small{{color:#657067}}</style>
    </head><body><header><small>VAELITH PLATFORM · RELATÓRIO CONTROLADO</small><h1>{escape(title)}</h1>
    <p>{escape(str(project.get('name') or ''))} · {escape(str(project.get('client') or ''))} · {escape(str(project.get('location') or ''))}</p></header>
    <div class='grid'><div class='card'><span>Prontidão</span><b>{analysis.get('readiness',0)}%</b></div>
    <div class='card'><span>Ocorrências abertas</span><b>{sum(i.get('status')!='encerrada' for i in issues)}</b></div>
    <div class='card'><span>Impacto financeiro</span><b>R$ {impacts['cost']:,.2f}</b></div>
    <div class='card'><span>Impacto em prazo</span><b>{impacts['days']} dias</b></div></div>
    <h2>Situação executiva</h2><p>Gate de compatibilização: <b>{escape(str(analysis.get('gate') or 'Não executada'))}</b>.
    Planejamento: {planning['total']} atividades, {planning['delayed']} atrasadas e {planning['blocked']} bloqueadas.
    Mudanças: {changes['total']} registros, com variação acumulada de R$ {changes['costDelta']:,.2f} e {changes['scheduleDelta']} dias.</p>
    <h2>Documentos</h2><table><thead><tr><th>Arquivo</th><th>Disciplina</th><th>Revisão</th><th>Bytes</th></tr></thead><tbody>{file_rows}</tbody></table>
    <h2>Ocorrências</h2><table><thead><tr><th>Código</th><th>Título</th><th>Criticidade</th><th>Status</th></tr></thead><tbody>{issue_rows}</tbody></table>
    <p><small>Gerado em {escape(snapshot['generatedAt'])}. A decisão técnica permanece sob responsabilidade dos profissionais habilitados.</small></p></body></html>"""


def render_report_pdf(snapshot: dict, title: str) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise HTTPException(503, "Gerador PDF indisponível no ambiente.") from exc
    stream = io.BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("VAELITH PLATFORM · RELATÓRIO CONTROLADO", styles["Small"]),
        Paragraph(escape(title), styles["Title"]),
        Paragraph(escape(str(snapshot["project"].get("name") or "")), styles["Heading2"]),
        Spacer(1, 6),
    ]
    analysis = snapshot.get("analysis") or {}
    impact = snapshot["impacts"]["summary"]
    summary = [
        ["Prontidão", f"{analysis.get('readiness', 0)}%"],
        ["Gate", str(analysis.get("gate") or "Não executada")],
        ["Arquivos", str(len(snapshot.get("files") or []))],
        ["Ocorrências", str(len(snapshot.get("issues") or []))],
        ["Impacto financeiro", f"R$ {impact['cost']:,.2f}"],
        ["Impacto em prazo", f"{impact['days']} dias"],
    ]
    t = Table(summary, colWidths=[55*mm, 115*mm])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(0,-1),colors.HexColor("#eef5e5")),("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#ccd4ca")),("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("VALIGN",(0,0),(-1,-1),"TOP"),("PADDING",(0,0),(-1,-1),6)]))
    story += [t, Spacer(1, 12), Paragraph("Ocorrências", styles["Heading2"])]
    issue_data = [["Código", "Título", "Criticidade", "Status"]]
    for item in snapshot.get("issues", [])[:100]:
        issue_data.append([str(item.get("code") or ""), str(item.get("title") or "")[:70], str(item.get("severity") or ""), str(item.get("status") or "")])
    it = Table(issue_data, repeatRows=1, colWidths=[28*mm, 85*mm, 28*mm, 30*mm])
    it.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#172018")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#ccd4ca")),("FONTSIZE",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"TOP"),("PADDING",(0,0),(-1,-1),4)]))
    story.append(it)
    doc.build(story)
    return stream.getvalue()


def ifc_metadata(model) -> dict:
    project = model.by_type("IfcProject")
    sites = model.by_type("IfcSite")
    buildings = model.by_type("IfcBuilding")
    storeys = model.by_type("IfcBuildingStorey")
    elements = model.by_type("IfcElement")
    unit_scale = None
    try:
        import ifcopenshell.util.unit
        unit_scale = float(ifcopenshell.util.unit.calculate_unit_scale(model))
    except Exception:
        unit_scale = None
    counts = {}
    for item in elements:
        kind = item.is_a()
        counts[kind] = counts.get(kind, 0) + 1
    top_counts = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:25])
    return {
        "schema": getattr(model, "schema", None),
        "projectName": getattr(project[0], "Name", None) if project else None,
        "sites": len(sites),
        "buildings": len(buildings),
        "storeys": len(storeys),
        "elements": len(elements),
        "unitScaleToMeters": unit_scale,
        "georeferenced": bool(model.by_type("IfcMapConversion") or model.by_type("IfcProjectedCRS")),
        "topClasses": top_counts,
    }


def clash_severity(a_class: str, b_class: str, distance: float) -> str:
    structural = ("Beam", "Column", "Slab", "Footing", "Pile", "Member")
    services = ("Pipe", "Duct", "Cable", "Flow", "Distribution", "Fitting", "Terminal")
    a_struct = any(token in a_class for token in structural)
    b_struct = any(token in b_class for token in structural)
    a_mep = any(token in a_class for token in services)
    b_mep = any(token in b_class for token in services)
    if (a_struct and b_mep) or (b_struct and a_mep):
        return "critica"
    if distance > 0.05:
        return "critica"
    return "alta"


def run_bim_job(pid: str, rows: list[dict], mode: str, tolerance: float, check_all: bool, create_issues: bool, actor: dict) -> dict:
    try:
        import ifcopenshell
        import ifcopenshell.geom
    except ImportError as exc:
        raise HTTPException(503, "IfcOpenShell não está instalado no ambiente de processamento.") from exc
    import supabase_runtime
    temp_paths = []
    models = []
    tree = ifcopenshell.geom.tree()
    geometry_counts = []
    try:
        for row in rows:
            storage_path = str(row.get("storage_path") or "")
            prefix = f"supabase://{supabase_runtime.BUCKET}/"
            if not storage_path.startswith(prefix):
                raise HTTPException(409, f"{row['name']}: arquivo IFC sem referência persistente.")
            raw = supabase_runtime._object_bytes(storage_path[len(prefix):])
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=".ifc")
            handle.write(raw)
            handle.close()
            temp_paths.append(handle.name)
            model = ifcopenshell.open(handle.name)
            settings = ifcopenshell.geom.settings()
            try:
                settings.set("use-world-coords", True)
            except Exception:
                try:
                    settings.set(settings.USE_WORLD_COORDS, True)
                except Exception:
                    pass
            iterator = ifcopenshell.geom.iterator(settings, model, max(1, min(2, os.cpu_count() or 1)))
            count = 0
            if iterator.initialize():
                while True:
                    tree.add_element(iterator.get())
                    count += 1
                    if not iterator.next():
                        break
            models.append({"row": row, "model": model, "elements": model.by_type("IfcElement"), "metadata": ifc_metadata(model)})
            geometry_counts.append({"fileId": row["id"], "name": row["name"], "shapes": count})
        clashes_out = []
        for i in range(len(models)):
            for j in range(i + 1, len(models)):
                a = models[i]
                b = models[j]
                if mode == "clearance":
                    clashes = tree.clash_clearance_many(a["elements"], b["elements"], clearance=tolerance, check_all=check_all)
                elif mode == "collision":
                    clashes = tree.clash_collision_many(a["elements"], b["elements"], allow_touching=False)
                else:
                    clashes = tree.clash_intersection_many(a["elements"], b["elements"], tolerance=tolerance, check_all=check_all)
                for clash in clashes:
                    element_a, element_b = clash.a, clash.b
                    a_class, b_class = element_a.is_a(), element_b.is_a()
                    distance = float(getattr(clash, "distance", 0) or 0)
                    try:
                        clash_type = tree.get_clash_type(int(clash.clash_type))
                    except Exception:
                        clash_type = str(getattr(clash, "clash_type", mode))
                    item = {
                        "id": uuid4().hex,
                        "fileA": a["row"]["id"],
                        "fileAName": a["row"]["name"],
                        "fileB": b["row"]["id"],
                        "fileBName": b["row"]["name"],
                        "guidA": getattr(element_a, "GlobalId", None),
                        "guidB": getattr(element_b, "GlobalId", None),
                        "classA": a_class,
                        "classB": b_class,
                        "nameA": getattr(element_a, "Name", None),
                        "nameB": getattr(element_b, "Name", None),
                        "type": str(clash_type),
                        "distance": distance,
                        "pointA": [float(v) for v in getattr(clash, "p1", [])],
                        "pointB": [float(v) for v in getattr(clash, "p2", [])],
                        "severity": clash_severity(a_class, b_class, distance),
                    }
                    clashes_out.append(item)
                    if len(clashes_out) >= 5000:
                        break
                if len(clashes_out) >= 5000:
                    break
            if len(clashes_out) >= 5000:
                break
        duplicate_guids = defaultdict(list)
        for item in models:
            for element in item["elements"]:
                guid = getattr(element, "GlobalId", None)
                if guid:
                    duplicate_guids[guid].append(item["row"]["name"])
        duplicates = [{"guid": guid, "files": names} for guid, names in duplicate_guids.items() if len(set(names)) > 1]
        result = {
            "engine": "IfcOpenShell-0.8.5",
            "mode": mode,
            "toleranceMeters": tolerance,
            "files": [{"id": x["row"]["id"], "name": x["row"]["name"], **x["metadata"]} for x in models],
            "geometry": geometry_counts,
            "clashes": clashes_out,
            "summary": {
                "files": len(models),
                "shapes": sum(x["shapes"] for x in geometry_counts),
                "clashes": len(clashes_out),
                "critical": sum(x["severity"] == "critica" for x in clashes_out),
                "high": sum(x["severity"] == "alta" for x in clashes_out),
                "duplicateGlobalIds": len(duplicates),
                "truncated": len(clashes_out) >= 5000,
            },
            "duplicateGlobalIds": duplicates[:500],
        }
        if create_issues and clashes_out:
            server = srv()
            with server.conn() as c:
                for clash in clashes_out[:200]:
                    issue_id = uuid4().hex
                    created = now()
                    code = f"BIM-{created[:4]}-{issue_id[:6].upper()}"
                    title = f"{clash['classA']} × {clash['classB']}"
                    description = (
                        f"Colisão geométrica detectada entre {clash.get('nameA') or clash['guidA']} "
                        f"e {clash.get('nameB') or clash['guidB']} nos arquivos "
                        f"{clash['fileAName']} e {clash['fileBName']}."
                    )
                    c.execute(
                        "INSERT INTO operational_issues VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            issue_id, pid, None, code, title, description, "incompatibilidade",
                            clash["severity"], "identificada", None,
                            json.dumps([], ensure_ascii=False), "Coordenação BIM", None,
                            actor["id"], created, created, None,
                        ),
                    )
                    c.execute(
                        "INSERT INTO issue_history VALUES(?,?,?,?,?,?,?)",
                        (uuid4().hex, issue_id, None, "identificada", actor["name"], "Criada pelo motor BIM.", created),
                    )
        return result
    finally:
        for path in temp_paths:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass


def intelligence_answer(pid: str, question: str) -> dict:
    snapshot = report_snapshot(pid)
    q = question.lower().strip()
    analysis = snapshot.get("analysis") or {}
    issues = snapshot.get("issues") or []
    impacts = snapshot["impacts"]["summary"]
    planning = snapshot["planning"]["summary"]
    changes = snapshot["changes"]["summary"]
    revisions = snapshot["revisions"]
    sources = []
    if any(word in q for word in ("crític", "prioridade", "urgente")):
        critical = [i for i in issues if i.get("severity") == "critica" and i.get("status") != "encerrada"]
        answer = f"Há {len(critical)} ocorrência(s) crítica(s) aberta(s)."
        if critical:
            answer += " Prioridades: " + "; ".join(f"{i.get('code')} — {i.get('title')}" for i in critical[:5]) + "."
        sources = [{"module": "Ocorrências", "entityId": i.get("id"), "label": i.get("code")} for i in critical[:5]]
    elif any(word in q for word in ("atras", "prazo", "cronograma")):
        answer = (
            f"O impacto cadastrado soma {impacts['days']} dias. O planejamento possui "
            f"{planning['delayed']} atividade(s) atrasada(s), {planning['blocked']} bloqueada(s) "
            f"e avanço médio de {planning['averageProgress']}%."
        )
        sources = [{"module": "Impactos", "label": f"{impacts['days']} dias"}, {"module": "Planejamento", "label": f"{planning['delayed']} atrasadas"}]
    elif any(word in q for word in ("custo", "financeir", "orçamento", "orcamento")):
        answer = (
            f"Os impactos cadastrados somam R$ {impacts['cost']:,.2f}. "
            f"As mudanças não rejeitadas acumulam R$ {changes['costDelta']:,.2f}. "
            f"O orçamento importado totaliza R$ {snapshot['budget']['total']:,.2f}."
        )
        sources = [{"module": "Impactos", "label": "Impacto acumulado"}, {"module": "Mudanças", "label": "Variação aprovada"}, {"module": "Orçamento", "label": "Base importada"}]
    elif any(word in q for word in ("revis", "document")):
        answer = (
            f"A base possui {revisions['files']} arquivo(s), {revisions['conflicts']} conflito(s) de revisão "
            f"e {revisions['pendingReview']} documento(s) aguardando controle."
        )
        sources = [{"module": "Revisões", "label": group["disciplineCode"]} for group in revisions["groups"] if group["conflict"]][:5]
    elif any(word in q for word in ("mudança", "mudanca", "alteração", "alteracao")):
        answer = (
            f"Existem {changes['total']} mudança(s), sendo {changes['open']} ainda aberta(s). "
            f"A variação acumulada é de R$ {changes['costDelta']:,.2f} e {changes['scheduleDelta']} dias."
        )
        sources = [{"module": "Mudanças", "label": item.get("code"), "entityId": item.get("id")} for item in snapshot["changes"]["changes"][:5]]
    else:
        answer = (
            f"O empreendimento está com prontidão de {analysis.get('readiness', 0)}% e gate "
            f"“{analysis.get('gate') or 'não executado'}”. Há {sum(i.get('status') != 'encerrada' for i in issues)} "
            f"ocorrência(s) aberta(s), impacto de R$ {impacts['cost']:,.2f} e {impacts['days']} dias."
        )
        sources = [{"module": "Compatibilização", "label": str(analysis.get("gate") or "Sem rodada")}, {"module": "Ocorrências", "label": "Abertas"}, {"module": "Impactos", "label": "Acumulado"}]
    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "generatedAt": now(),
        "disclaimer": "Resposta gerada a partir dos registros da plataforma. Não substitui decisão técnica profissional.",
    }


def install(app: FastAPI) -> None:
    if getattr(app.state, "_vaelith_complete_runtime_v1", False):
        return
    ensure_schema()
    app.state._vaelith_complete_runtime_v1 = True

    @app.get("/api/projects/{pid}/revisions")
    def revisions(pid: str, vaelith_session: str | None = Cookie(None)):
        context(pid, vaelith_session)
        return revision_payload(pid)

    @app.patch("/api/projects/{pid}/revisions/{fid}")
    async def control_revision(pid: str, fid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        server, user, _ = context(pid, vaelith_session)
        data = parse_body(await request.body())
        status = str(data.get("status") or "review")
        if status not in REVISION_STATUSES:
            raise HTTPException(400, "Status de revisão inválido.")
        approved = bool(data.get("approved"))
        with server.conn() as c:
            file_row = c.execute("SELECT * FROM files WHERE id=? AND project_id=?", (fid, pid)).fetchone()
            if not file_row:
                raise HTTPException(404, "Arquivo não encontrado.")
            if status == "active":
                peer_rows = c.execute(
                    "SELECT id FROM files WHERE project_id=? AND discipline_code=? AND id<>?",
                    (pid, file_row["discipline_code"], fid),
                ).fetchall()
                for peer in peer_rows:
                    c.execute(
                        """
                        INSERT INTO document_controls(file_id,project_id,status,approved,approved_by,approved_at,supersedes_file_id,notes,updated)
                        VALUES(?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(file_id) DO UPDATE SET status=EXCLUDED.status,approved=0,approved_by=NULL,approved_at=NULL,updated=EXCLUDED.updated
                        """,
                        (peer["id"], pid, "superseded", 0, None, None, fid, None, now()),
                    )
            c.execute(
                """
                INSERT INTO document_controls(file_id,project_id,status,approved,approved_by,approved_at,supersedes_file_id,notes,updated)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(file_id) DO UPDATE SET status=EXCLUDED.status,approved=EXCLUDED.approved,
                approved_by=EXCLUDED.approved_by,approved_at=EXCLUDED.approved_at,
                supersedes_file_id=EXCLUDED.supersedes_file_id,notes=EXCLUDED.notes,updated=EXCLUDED.updated
                """,
                (
                    fid, pid, status, 1 if approved else 0, user["name"] if approved else None,
                    now() if approved else None, data.get("supersedesFileId") or None,
                    str(data.get("notes") or "").strip() or None, now(),
                ),
            )
            audit(c, pid, user["name"], "revision.controlled", "file", fid, {"status": status, "approved": approved})
        return revision_payload(pid)

    @app.get("/api/projects/{pid}/impacts")
    def impacts(pid: str, vaelith_session: str | None = Cookie(None)):
        context(pid, vaelith_session)
        return impacts_payload(pid)

    @app.get("/api/projects/{pid}/planning")
    def planning(pid: str, vaelith_session: str | None = Cookie(None)):
        context(pid, vaelith_session)
        return planning_payload(pid)

    @app.post("/api/projects/{pid}/planning/activities")
    async def create_activity(pid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        server, user, _ = context(pid, vaelith_session)
        data = parse_body(await request.body())
        name = str(data.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "Informe o nome da atividade.")
        activity_id, created = uuid4().hex, now()
        code = str(data.get("code") or f"PLN-{activity_id[:6].upper()}").strip()
        status = str(data.get("status") or "not_started")
        if status not in PLANNING_STATUSES:
            raise HTTPException(400, "Status de planejamento inválido.")
        progress = min(max(float(data.get("progress") or 0), 0), 100)
        with server.conn() as c:
            c.execute(
                "INSERT INTO planning_activities VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    activity_id, pid, code, name, data.get("startDate") or None, data.get("endDate") or None,
                    max(int(data.get("durationDays") or 0), 0), progress, status,
                    str(data.get("owner") or "").strip() or None, 1 if data.get("critical") else 0,
                    json.dumps(data.get("predecessors") or []), data.get("issueId") or None,
                    data.get("sourceFileId") or None, created, created,
                ),
            )
            audit(c, pid, user["name"], "planning.created", "planning_activity", activity_id, {"code": code})
        return planning_payload(pid)

    @app.patch("/api/projects/{pid}/planning/activities/{activity_id}")
    async def update_activity(pid: str, activity_id: str, request: Request, vaelith_session: str | None = Cookie(None)):
        server, user, _ = context(pid, vaelith_session)
        data = parse_body(await request.body())
        with server.conn() as c:
            row = c.execute("SELECT * FROM planning_activities WHERE id=? AND project_id=?", (activity_id, pid)).fetchone()
            if not row:
                raise HTTPException(404, "Atividade não encontrada.")
            status = str(data.get("status", row["status"]))
            if status not in PLANNING_STATUSES:
                raise HTTPException(400, "Status de planejamento inválido.")
            progress = min(max(float(data.get("progress", row["progress"]) or 0), 0), 100)
            if status == "completed":
                progress = 100
            c.execute(
                """
                UPDATE planning_activities SET name=?,start_date=?,end_date=?,duration_days=?,progress=?,
                status=?,owner=?,critical=?,predecessors=?,updated=? WHERE id=?
                """,
                (
                    str(data.get("name", row["name"])).strip(), data.get("startDate", row["start_date"]),
                    data.get("endDate", row["end_date"]), max(int(data.get("durationDays", row["duration_days"]) or 0), 0),
                    progress, status, str(data.get("owner", row["owner"]) or "").strip() or None,
                    1 if data.get("critical", bool(row["critical"])) else 0,
                    json.dumps(data.get("predecessors", decode_json(row["predecessors"], []))), now(), activity_id,
                ),
            )
            audit(c, pid, user["name"], "planning.updated", "planning_activity", activity_id, {"status": status, "progress": progress})
        return planning_payload(pid)

    @app.delete("/api/projects/{pid}/planning/activities/{activity_id}")
    def delete_activity(pid: str, activity_id: str, vaelith_session: str | None = Cookie(None)):
        server, user, _ = context(pid, vaelith_session)
        with server.conn() as c:
            if not c.execute("SELECT id FROM planning_activities WHERE id=? AND project_id=?", (activity_id, pid)).fetchone():
                raise HTTPException(404, "Atividade não encontrada.")
            c.execute("DELETE FROM planning_activities WHERE id=?", (activity_id,))
            audit(c, pid, user["name"], "planning.deleted", "planning_activity", activity_id)
        return Response(status_code=204)

    @app.post("/api/projects/{pid}/planning/from-issues")
    def planning_from_issues(pid: str, vaelith_session: str | None = Cookie(None)):
        server, user, _ = context(pid, vaelith_session)
        created_count = 0
        with server.conn() as c:
            issues = c.execute(
                "SELECT * FROM operational_issues WHERE project_id=? AND status<>'encerrada' ORDER BY severity DESC,created", (pid,)
            ).fetchall()
            for issue in issues:
                if c.execute("SELECT id FROM planning_activities WHERE issue_id=?", (issue["id"],)).fetchone():
                    continue
                aid = uuid4().hex
                critical = issue["severity"] == "critica"
                c.execute(
                    "INSERT INTO planning_activities VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        aid, pid, f"ISS-{issue['code']}", f"Tratar {issue['code']} — {issue['title']}",
                        None, issue["due_date"], 0, 0, "not_started", issue["assignee"],
                        1 if critical else 0, "[]", issue["id"], None, now(), now(),
                    ),
                )
                created_count += 1
            audit(c, pid, user["name"], "planning.generated_from_issues", "project", pid, {"created": created_count})
        return {"created": created_count, **planning_payload(pid)}

    @app.get("/api/projects/{pid}/changes")
    def changes(pid: str, vaelith_session: str | None = Cookie(None)):
        context(pid, vaelith_session)
        return changes_payload(pid)

    @app.post("/api/projects/{pid}/changes")
    async def create_change(pid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        server, user, _ = context(pid, vaelith_session)
        data = parse_body(await request.body())
        title = str(data.get("title") or "").strip()
        description = str(data.get("description") or "").strip()
        reason = str(data.get("reason") or "").strip()
        if not title or not description or not reason:
            raise HTTPException(400, "Informe título, descrição e justificativa.")
        change_id, created = uuid4().hex, now()
        code = f"MUD-{created[:4]}-{change_id[:6].upper()}"
        with server.conn() as c:
            c.execute(
                "INSERT INTO change_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    change_id, pid, code, title, description, reason, "requested", user["name"], None,
                    max(float(data.get("costDelta") or 0), 0), max(int(data.get("scheduleDelta") or 0), 0),
                    json.dumps(data.get("disciplines") or [], ensure_ascii=False), data.get("issueId") or None,
                    None, created, created, None,
                ),
            )
            audit(c, pid, user["name"], "change.created", "change_request", change_id, {"code": code})
        return changes_payload(pid)

    @app.patch("/api/projects/{pid}/changes/{change_id}")
    async def update_change(pid: str, change_id: str, request: Request, vaelith_session: str | None = Cookie(None)):
        server, user, _ = context(pid, vaelith_session)
        data = parse_body(await request.body())
        with server.conn() as c:
            row = c.execute("SELECT * FROM change_requests WHERE id=? AND project_id=?", (change_id, pid)).fetchone()
            if not row:
                raise HTTPException(404, "Mudança não encontrada.")
            status = str(data.get("status", row["status"]))
            if status not in CHANGE_STATUSES:
                raise HTTPException(400, "Status de mudança inválido.")
            approved = status in {"approved", "implemented", "verified", "closed"}
            c.execute(
                """
                UPDATE change_requests SET status=?,approved_by=?,cost_delta=?,schedule_delta=?,disciplines=?,
                decision=?,updated=?,approved_at=? WHERE id=?
                """,
                (
                    status, user["name"] if approved else row["approved_by"],
                    max(float(data.get("costDelta", row["cost_delta"]) or 0), 0),
                    max(int(data.get("scheduleDelta", row["schedule_delta"]) or 0), 0),
                    json.dumps(data.get("disciplines", decode_json(row["disciplines"], [])), ensure_ascii=False),
                    str(data.get("decision", row["decision"]) or "").strip() or None,
                    now(), now() if approved and not row["approved_at"] else row["approved_at"], change_id,
                ),
            )
            audit(c, pid, user["name"], "change.updated", "change_request", change_id, {"status": status})
        return changes_payload(pid)

    @app.get("/api/projects/{pid}/reports")
    def reports(pid: str, vaelith_session: str | None = Cookie(None)):
        server, _, _ = context(pid, vaelith_session)
        with server.conn() as c:
            rows = [dict(row) for row in c.execute(
                "SELECT id,project_id,report_type,title,created_by,created FROM project_reports WHERE project_id=? ORDER BY created DESC", (pid,)
            ).fetchall()]
        return rows

    @app.post("/api/projects/{pid}/reports")
    async def generate_report(pid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        server, user, project = context(pid, vaelith_session)
        data = parse_body(await request.body())
        report_type = str(data.get("type") or "executive")
        if report_type not in REPORT_TYPES:
            raise HTTPException(400, "Tipo de relatório inválido.")
        title = str(data.get("title") or f"Relatório {report_type} — {project['name']}").strip()
        snapshot = report_snapshot(pid)
        report_id = uuid4().hex
        with server.conn() as c:
            c.execute(
                "INSERT INTO project_reports VALUES(?,?,?,?,?,?,?)",
                (report_id, pid, report_type, title, json.dumps(snapshot, ensure_ascii=False), user["name"], now()),
            )
            audit(c, pid, user["name"], "report.generated", "project_report", report_id, {"type": report_type})
        return {"id": report_id, "title": title, "type": report_type}

    @app.get("/api/projects/{pid}/reports/{report_id}")
    def report_json(pid: str, report_id: str, vaelith_session: str | None = Cookie(None)):
        server, _, _ = context(pid, vaelith_session)
        with server.conn() as c:
            row = c.execute("SELECT * FROM project_reports WHERE id=? AND project_id=?", (report_id, pid)).fetchone()
        if not row:
            raise HTTPException(404, "Relatório não encontrado.")
        return {**dict(row), "snapshot": decode_json(row["snapshot"], {})}

    @app.get("/api/projects/{pid}/reports/{report_id}/html", include_in_schema=False)
    def report_html(pid: str, report_id: str, vaelith_session: str | None = Cookie(None)):
        server, _, _ = context(pid, vaelith_session)
        with server.conn() as c:
            row = c.execute("SELECT * FROM project_reports WHERE id=? AND project_id=?", (report_id, pid)).fetchone()
        if not row:
            raise HTTPException(404, "Relatório não encontrado.")
        return HTMLResponse(render_report_html(decode_json(row["snapshot"], {}), row["title"]))

    @app.get("/api/projects/{pid}/reports/{report_id}/pdf", include_in_schema=False)
    def report_pdf(pid: str, report_id: str, vaelith_session: str | None = Cookie(None)):
        server, _, _ = context(pid, vaelith_session)
        with server.conn() as c:
            row = c.execute("SELECT * FROM project_reports WHERE id=? AND project_id=?", (report_id, pid)).fetchone()
        if not row:
            raise HTTPException(404, "Relatório não encontrado.")
        payload = render_report_pdf(decode_json(row["snapshot"], {}), row["title"])
        return Response(
            payload,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="vaelith-{report_id[:8]}.pdf"'},
        )

    @app.post("/api/projects/{pid}/intelligence/query")
    async def intelligence(pid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        context(pid, vaelith_session)
        data = parse_body(await request.body())
        question = str(data.get("question") or "").strip()
        if len(question) < 3:
            raise HTTPException(400, "Escreva uma pergunta sobre o empreendimento.")
        return intelligence_answer(pid, question)

    @app.get("/api/projects/{pid}/bim/status")
    def bim_status(pid: str, vaelith_session: str | None = Cookie(None)):
        context(pid, vaelith_session)
        try:
            import ifcopenshell
            available = True
            version = getattr(ifcopenshell, "version", None) or getattr(ifcopenshell, "__version__", None)
        except ImportError:
            available, version = False, None
        return {
            "available": available,
            "engine": "IfcOpenShell",
            "version": version,
            "modes": sorted(BIM_MODES),
            "maxFilesPerRun": 4,
            "maxResults": 5000,
        }

    @app.get("/api/projects/{pid}/bim/jobs")
    def bim_jobs(pid: str, vaelith_session: str | None = Cookie(None)):
        server, _, _ = context(pid, vaelith_session)
        with server.conn() as c:
            rows = [dict(row) for row in c.execute(
                "SELECT id,project_id,status,mode,tolerance,input_files,error,created_by,created,started,finished FROM bim_jobs WHERE project_id=? ORDER BY created DESC LIMIT 30", (pid,)
            ).fetchall()]
        for row in rows:
            row["input_files"] = decode_json(row.get("input_files"), [])
        return rows

    @app.get("/api/projects/{pid}/bim/jobs/{job_id}")
    def bim_job(pid: str, job_id: str, vaelith_session: str | None = Cookie(None)):
        server, _, _ = context(pid, vaelith_session)
        with server.conn() as c:
            row = c.execute("SELECT * FROM bim_jobs WHERE id=? AND project_id=?", (job_id, pid)).fetchone()
        if not row:
            raise HTTPException(404, "Processamento BIM não encontrado.")
        data = dict(row)
        data["input_files"] = decode_json(data.get("input_files"), [])
        data["result"] = decode_json(data.get("result"), None)
        return data

    @app.post("/api/projects/{pid}/bim/analyze")
    async def bim_analyze(pid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        server, user, _ = context(pid, vaelith_session)
        data = parse_body(await request.body())
        file_ids = [str(value) for value in (data.get("fileIds") or [])]
        if len(file_ids) < 2 or len(file_ids) > 4:
            raise HTTPException(400, "Selecione de 2 a 4 modelos IFC.")
        mode = str(data.get("mode") or "intersection")
        if mode not in BIM_MODES:
            raise HTTPException(400, "Modo BIM inválido.")
        tolerance = float(data.get("tolerance") or (0.1 if mode == "clearance" else 0.002))
        if tolerance < 0 or tolerance > 5:
            raise HTTPException(400, "A tolerância deve estar entre 0 e 5 metros.")
        placeholders = ",".join("?" for _ in file_ids)
        with server.conn() as c:
            rows = [dict(row) for row in c.execute(
                f"SELECT * FROM files WHERE project_id=? AND id IN ({placeholders})",
                (pid, *file_ids),
            ).fetchall()]
        if len(rows) != len(set(file_ids)) or any(str(row.get("ext") or "").lower() != ".ifc" for row in rows):
            raise HTTPException(400, "Todos os arquivos selecionados devem ser modelos IFC válidos do empreendimento.")
        total_size = sum(int(row.get("size") or 0) for row in rows)
        if total_size > 120 * 1024 * 1024:
            raise HTTPException(413, "A rodada geométrica está limitada a 120 MB combinados nesta versão.")
        job_id, created = uuid4().hex, now()
        with server.conn() as c:
            c.execute(
                "INSERT INTO bim_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id, pid, "running", mode, tolerance,
                    json.dumps([{"id": r["id"], "name": r["name"]} for r in rows], ensure_ascii=False),
                    None, None, user["name"], created, created, None,
                ),
            )
        try:
            result = run_bim_job(
                pid, rows, mode, tolerance, bool(data.get("checkAll", False)),
                bool(data.get("createIssues", False)), user,
            )
            with server.conn() as c:
                c.execute(
                    "UPDATE bim_jobs SET status='completed',result=?,finished=? WHERE id=?",
                    (json.dumps(result, ensure_ascii=False), now(), job_id),
                )
                audit(c, pid, user["name"], "bim.completed", "bim_job", job_id, result.get("summary"))
            return {"jobId": job_id, **result}
        except HTTPException as exc:
            with server.conn() as c:
                c.execute("UPDATE bim_jobs SET status='failed',error=?,finished=? WHERE id=?", (str(exc.detail), now(), job_id))
            raise
        except Exception as exc:
            with server.conn() as c:
                c.execute(
                    "UPDATE bim_jobs SET status='failed',error=?,finished=? WHERE id=?",
                    (f"{type(exc).__name__}: {str(exc)[:500]}", now(), job_id),
                )
            raise HTTPException(500, f"Falha no motor BIM: {type(exc).__name__}: {str(exc)[:240]}") from exc

    @app.get("/api/projects/{pid}/audit")
    def audit_log(pid: str, vaelith_session: str | None = Cookie(None)):
        server, _, _ = context(pid, vaelith_session)
        with server.conn() as c:
            rows = [dict(row) for row in c.execute(
                "SELECT * FROM audit_events WHERE project_id=? ORDER BY created DESC LIMIT 200", (pid,)
            ).fetchall()]
        for row in rows:
            row["detail"] = decode_json(row.get("detail"), {})
        return rows
