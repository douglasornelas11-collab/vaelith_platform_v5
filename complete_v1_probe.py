from __future__ import annotations

import hashlib
import math
import tempfile
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException

TOKEN_SHA256 = "dbcf82a753974f393b168be4559d9926e45984dc51169b48848f74751aaac3df"


def _allowed(token: str) -> bool:
    return hashlib.sha256(token.encode("utf-8")).hexdigest() == TOKEN_SHA256


def _ifc_model(name: str, ifc_class: str, position: tuple[float, float, float], angle: float, length: float, height: float, thickness: float) -> bytes:
    import numpy as np
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.context
    import ifcopenshell.api.geometry
    import ifcopenshell.api.project
    import ifcopenshell.api.root
    import ifcopenshell.api.spatial
    import ifcopenshell.api.unit

    model = ifcopenshell.api.project.create_file()
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name=f"VAELITH {name}")
    ifcopenshell.api.unit.assign_unit(model)
    model3d = ifcopenshell.api.context.add_context(model, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        model,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model3d,
    )
    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name="Building")
    storey = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingStorey", name="Level 01")
    ifcopenshell.api.aggregate.assign_object(model, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(model, products=[storey], relating_object=building)

    element = ifcopenshell.api.root.create_entity(model, ifc_class=ifc_class, name=name)
    representation = ifcopenshell.api.geometry.add_wall_representation(
        model,
        context=body,
        length=length,
        height=height,
        thickness=thickness,
    )
    ifcopenshell.api.geometry.assign_representation(model, product=element, representation=representation)
    matrix = np.identity(4)
    matrix[0, 0] = math.cos(angle)
    matrix[0, 1] = -math.sin(angle)
    matrix[1, 0] = math.sin(angle)
    matrix[1, 1] = math.cos(angle)
    matrix[0, 3], matrix[1, 3], matrix[2, 3] = position
    ifcopenshell.api.geometry.edit_object_placement(model, product=element, matrix=matrix)
    ifcopenshell.api.spatial.assign_container(model, products=[element], relating_structure=storey)

    with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as handle:
        path = Path(handle.name)
    try:
        model.write(str(path))
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _cleanup_project(project_id: str) -> None:
    if not project_id:
        return
    import server
    with server.conn() as c:
        issues = c.execute("SELECT id FROM operational_issues WHERE project_id=?", (project_id,)).fetchall()
        for issue in issues:
            issue_id = issue["id"]
            c.execute("DELETE FROM issue_history WHERE issue_id=?", (issue_id,))
            c.execute("DELETE FROM issue_decisions WHERE issue_id=?", (issue_id,))
            c.execute("DELETE FROM issue_impacts WHERE issue_id=?", (issue_id,))
        c.execute("DELETE FROM operational_issues WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM document_controls WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM planning_activities WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM change_requests WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM project_reports WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM audit_events WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM bim_jobs WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM budget_items WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM analyses WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM files WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM projects WHERE id=?", (project_id,))


def install(app: FastAPI) -> None:
    @app.get("/api/internal/complete-v1-test", include_in_schema=False)
    async def complete_v1_test(token: str):
        if not _allowed(token):
            raise HTTPException(404, "Not Found")

        import professional_auth_v3 as auth
        import server

        owner = auth._owner()
        if not owner:
            raise HTTPException(409, "Conta proprietária não configurada.")
        signed = auth._sign_user(owner, True)
        cookie = {"vaelith_session": signed}
        transport = httpx.ASGITransport(app=app)
        checks: dict[str, dict] = {}
        project_id = ""
        file_ids: list[str] = []

        def record(name: str, ok: bool, detail=None):
            checks[name] = {"ok": bool(ok), "detail": detail}

        async def request(client, method: str, url: str, **kwargs):
            return await client.request(method, url, **kwargs)

        try:
            async with httpx.AsyncClient(transport=transport, base_url="https://vaelith.local", cookies=cookie, timeout=180.0) as client:
                status = await request(client, "GET", "/api/platform/complete-status")
                status_data = status.json()
                record("complete_status", status.status_code == 200 and status_data.get("ok") is True, status_data)

                created = await request(
                    client,
                    "POST",
                    "/api/projects",
                    json={
                        "name": "VAELITH COMPLETE V1 — TESTE ISOLADO",
                        "client": "Validação interna",
                        "location": "Ambiente sintético",
                        "phase": "Coordenação",
                    },
                )
                project_data = created.json()
                project_id = str(project_data.get("id") or "")
                record("create_project", created.status_code == 200 and bool(project_id), project_data)

                files = [
                    ("EST_MODELO_R01.ifc", _ifc_model("Viga estrutural", "IfcBeam", (0.0, 0.0, 1.5), 0.0, 4.0, 0.5, 0.5)),
                    ("HID_MODELO_R01.ifc", _ifc_model("Tubulação hidráulica", "IfcPipeSegment", (2.0, -1.5, 1.65), math.pi / 2.0, 3.0, 0.2, 0.2)),
                    ("ARQ_MEMORIAL_R01.pdf", b"%PDF-1.4\n% VAELITH REVISION R01\n%%EOF\n"),
                    ("ARQ_MEMORIAL_R02.pdf", b"%PDF-1.4\n% VAELITH REVISION R02\n%%EOF\n"),
                ]
                upload_details = []
                for filename, payload in files:
                    sign = await request(
                        client,
                        "POST",
                        f"/api/projects/{project_id}/uploads/sign",
                        json={"name": filename, "size": len(payload), "mime": "application/octet-stream"},
                    )
                    if sign.status_code != 200:
                        upload_details.append({"name": filename, "sign": sign.status_code, "body": sign.text[:200]})
                        continue
                    sign_data = sign.json()
                    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as storage_client:
                        put = await storage_client.put(
                            sign_data["signedUrl"],
                            content=payload,
                            headers={"Content-Type": "application/octet-stream"},
                        )
                    confirm = await request(
                        client,
                        "POST",
                        f"/api/projects/{project_id}/uploads/confirm",
                        json={
                            "fileId": sign_data["fileId"],
                            "path": sign_data["path"],
                            "name": filename,
                            "size": len(payload),
                            "mime": "application/octet-stream",
                        },
                    )
                    if confirm.status_code == 200:
                        file_ids.append(sign_data["fileId"])
                    upload_details.append(
                        {
                            "name": filename,
                            "sign": sign.status_code,
                            "put": put.status_code,
                            "confirm": confirm.status_code,
                            "fileId": sign_data["fileId"],
                        }
                    )
                record(
                    "upload_real_files",
                    len(file_ids) == 4 and all(item.get("put") in {200, 201} and item.get("confirm") == 200 for item in upload_details),
                    upload_details,
                )

                revisions = await request(client, "GET", f"/api/projects/{project_id}/revisions")
                rev_data = revisions.json()
                arq = next((g for g in rev_data.get("groups", []) if g.get("disciplineCode") == "ARQ"), None)
                record("revision_conflict", revisions.status_code == 200 and bool(arq and arq.get("conflict")), rev_data)
                arq_r02 = next((f for f in (arq or {}).get("versions", []) if f.get("revision") == "R02"), None)
                rev_patch = await request(
                    client,
                    "PATCH",
                    f"/api/projects/{project_id}/revisions/{arq_r02['id']}",
                    json={"status": "active", "approved": True, "notes": "Base aprovada pelo teste."},
                ) if arq_r02 else None
                rev_after = rev_patch.json() if rev_patch else {}
                arq_after = next((g for g in rev_after.get("groups", []) if g.get("disciplineCode") == "ARQ"), None)
                record("revision_control", bool(rev_patch and rev_patch.status_code == 200 and arq_after and not arq_after.get("conflict")), arq_after)

                issue = await request(
                    client,
                    "POST",
                    f"/api/projects/{project_id}/operational/issues",
                    json={
                        "title": "Interferência sintética entre viga e tubulação",
                        "description": "Ocorrência criada para validar impacto, planejamento e inteligência.",
                        "issueType": "incompatibilidade",
                        "severity": "critica",
                        "location": "Pavimento 01 — eixo A/01",
                        "disciplines": ["EST", "HID"],
                        "assignee": "Coordenação BIM",
                    },
                )
                issue_data = issue.json()
                issue_id = str(issue_data.get("id") or "")
                record("create_issue", issue.status_code == 200 and bool(issue_id), issue_data)

                impact = await request(
                    client,
                    "POST",
                    f"/api/projects/{project_id}/operational/issues/{issue_id}/impacts",
                    json={
                        "costAmount": 12850.75,
                        "scheduleDays": 4,
                        "basis": "Estimativa sintética para teste integrado.",
                        "confidence": "confirmado",
                    },
                )
                impacts = await request(client, "GET", f"/api/projects/{project_id}/impacts")
                impacts_data = impacts.json()
                record(
                    "impact_consolidation",
                    impact.status_code == 200
                    and impacts.status_code == 200
                    and impacts_data.get("summary", {}).get("cost") == 12850.75
                    and impacts_data.get("summary", {}).get("days") == 4,
                    impacts_data,
                )

                generated_plan = await request(client, "POST", f"/api/projects/{project_id}/planning/from-issues")
                planning_data = generated_plan.json()
                activity = (planning_data.get("activities") or [None])[0]
                planning_update = await request(
                    client,
                    "PATCH",
                    f"/api/projects/{project_id}/planning/activities/{activity['id']}",
                    json={"status": "in_progress", "progress": 35},
                ) if activity else None
                planning_after = planning_update.json() if planning_update else {}
                record(
                    "planning",
                    generated_plan.status_code == 200
                    and planning_data.get("created") == 1
                    and bool(planning_update and planning_update.status_code == 200)
                    and planning_after.get("summary", {}).get("inProgress") == 1,
                    planning_after,
                )

                change = await request(
                    client,
                    "POST",
                    f"/api/projects/{project_id}/changes",
                    json={
                        "title": "Deslocar tubulação hidráulica",
                        "description": "Alterar o traçado para eliminar a colisão com a viga.",
                        "reason": "Incompatibilidade geométrica confirmada.",
                        "disciplines": ["EST", "HID"],
                        "costDelta": 3200.5,
                        "scheduleDelta": 2,
                        "issueId": issue_id,
                    },
                )
                change_data = change.json()
                change_id = (change_data.get("changes") or [{}])[0].get("id")
                change_update = await request(
                    client,
                    "PATCH",
                    f"/api/projects/{project_id}/changes/{change_id}",
                    json={"status": "approved", "decision": "Deslocamento aprovado pela coordenação."},
                ) if change_id else None
                change_after = change_update.json() if change_update else {}
                record(
                    "change_control",
                    change.status_code == 200
                    and bool(change_update and change_update.status_code == 200)
                    and change_after.get("summary", {}).get("approved") == 1,
                    change_after,
                )

                report = await request(
                    client,
                    "POST",
                    f"/api/projects/{project_id}/reports",
                    json={"type": "coordination", "title": "Relatório de validação Complete V1"},
                )
                report_data = report.json()
                report_id = str(report_data.get("id") or "")
                html = await request(client, "GET", f"/api/projects/{project_id}/reports/{report_id}/html")
                pdf = await request(client, "GET", f"/api/projects/{project_id}/reports/{report_id}/pdf")
                record(
                    "controlled_reports",
                    report.status_code == 200
                    and html.status_code == 200
                    and "RELATÓRIO CONTROLADO" in html.text
                    and pdf.status_code == 200
                    and pdf.content.startswith(b"%PDF"),
                    {"report": report_data, "htmlBytes": len(html.content), "pdfBytes": len(pdf.content)},
                )

                intelligence = await request(
                    client,
                    "POST",
                    f"/api/projects/{project_id}/intelligence/query",
                    json={"question": "Qual é o impacto financeiro e de prazo?"},
                )
                intelligence_data = intelligence.json()
                record(
                    "intelligence",
                    intelligence.status_code == 200
                    and "12.850,75" in intelligence_data.get("answer", "")
                    and bool(intelligence_data.get("sources")),
                    intelligence_data,
                )

                bim_status = await request(client, "GET", f"/api/projects/{project_id}/bim/status")
                bim = await request(
                    client,
                    "POST",
                    f"/api/projects/{project_id}/bim/analyze",
                    json={
                        "fileIds": file_ids[:2],
                        "mode": "intersection",
                        "tolerance": 0.002,
                        "checkAll": True,
                        "createIssues": True,
                    },
                )
                try:
                    bim_data = bim.json()
                except Exception:
                    bim_data = {"raw": bim.text[:500]}
                record(
                    "bim_geometry",
                    bim_status.status_code == 200
                    and bim_status.json().get("available") is True
                    and bim.status_code == 200
                    and bim_data.get("summary", {}).get("shapes", 0) >= 2
                    and bim_data.get("summary", {}).get("clashes", 0) >= 1,
                    {"status": bim_status.json(), "analysis": bim_data},
                )

                audit = await request(client, "GET", f"/api/projects/{project_id}/audit")
                audit_data = audit.json()
                actions = {item.get("action") for item in audit_data}
                record(
                    "audit_trail",
                    audit.status_code == 200
                    and {"revision.controlled", "planning.generated_from_issues", "change.created", "report.generated", "bim.completed"}.issubset(actions),
                    {"records": len(audit_data), "actions": sorted(actions)},
                )

                # Delete physical objects through the same production API before removing DB rows.
                deletion = []
                for file_id in file_ids:
                    response = await request(client, "DELETE", f"/api/projects/{project_id}/files/{file_id}")
                    deletion.append({"fileId": file_id, "status": response.status_code})
                record("storage_cleanup", all(item["status"] == 204 for item in deletion), deletion)

        finally:
            _cleanup_project(project_id)

        failures = [{"check": name, "detail": value.get("detail")} for name, value in checks.items() if not value.get("ok")]
        return {
            "ok": not failures,
            "version": "complete-v1",
            "summary": {
                "checks": len(checks),
                "passed": sum(value.get("ok") is True for value in checks.values()),
                "failed": len(failures),
            },
            "checks": checks,
            "failures": failures,
            "cleanup": {"projectRemoved": True, "projectId": project_id},
        }
