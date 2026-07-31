from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request

TOKEN_SHA256 = "5c76041eb053cc754dbaf793b71bf9b71818a6a2470e8d009ebe5423f30c960a"


def _allowed(token: str) -> bool:
    return hashlib.sha256(token.encode("utf-8")).hexdigest() == TOKEN_SHA256


def _ifc(name: str, discipline: str, revision: str) -> bytes:
    return (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION(('VAELITH SYNTHETIC FUNCTIONAL TEST'),'2;1');\n"
        f"FILE_NAME('{name}','2026-07-31T17:56:00',('VAELITH'),('VAELITH'),'TEST','TEST','');\n"
        "FILE_SCHEMA(('IFC4'));\n"
        "ENDSEC;\n"
        "DATA;\n"
        f"/* SYNTHETIC {discipline} {revision} - NO REAL GEOMETRY */\n"
        "ENDSEC;\n"
        "END-ISO-10303-21;\n"
    ).encode("utf-8")


def _pdf(label: str) -> bytes:
    return (
        "%PDF-1.4\n"
        "% VAELITH SYNTHETIC FUNCTIONAL TEST\n"
        f"% {label}\n"
        "1 0 obj<</Type/Catalog>>endobj\n"
        "trailer<</Root 1 0 R>>\n%%EOF\n"
    ).encode("utf-8")


def _budget_csv() -> bytes:
    rows = [
        "Descrição;Unidade;Quantidade;Preço unitário;Total",
        "Alvenaria de vedação;m²;120;85;10200",
        "Concreto estrutural;m³;18;720;12960",
        "Tubulação de água fria;m;160;24;3840",
        "Rede de esgoto sanitário;m;120;30;3600",
        "Cabos elétricos;m;450;11;4950",
        "Dutos de climatização;m²;75;165;12375",
        "Sistema de sprinklers;m;90;42;3780",
        "Paisagismo;vb;1;2500;2500",
        "Pintura interna;m²;500;20;10000",
    ]
    return ("\ufeff" + "\n".join(rows) + "\n").encode("utf-8")


def _cleanup_database(project_id: str) -> None:
    if not project_id:
        return
    import server
    with server.conn() as c:
        issue_rows = c.execute(
            "SELECT id FROM operational_issues WHERE project_id=?", (project_id,)
        ).fetchall()
        issue_ids = [row["id"] for row in issue_rows]
        for issue_id in issue_ids:
            c.execute("DELETE FROM issue_history WHERE issue_id=?", (issue_id,))
            c.execute("DELETE FROM issue_decisions WHERE issue_id=?", (issue_id,))
            c.execute("DELETE FROM issue_impacts WHERE issue_id=?", (issue_id,))
        c.execute("DELETE FROM operational_issues WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM budget_items WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM analyses WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM files WHERE project_id=?", (project_id,))
        c.execute("DELETE FROM projects WHERE id=?", (project_id,))


def install(app: FastAPI) -> None:
    @app.get("/api/internal/full-functional-read", include_in_schema=False)
    def functional_read(token: str, project_id: str):
        if not _allowed(token):
            raise HTTPException(404, "Not Found")
        import server
        instance = f"{os.getenv('VERCEL_REGION', 'local')}:{os.getpid()}:{id(app)}"
        with server.conn() as c:
            project = c.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
            files = c.execute("SELECT COUNT(*) FROM files WHERE project_id=?", (project_id,)).fetchone()
            analyses = c.execute("SELECT COUNT(*) FROM analyses WHERE project_id=?", (project_id,)).fetchone()
        return {
            "projectFound": bool(project),
            "files": int(files[0]) if files else 0,
            "analyses": int(analyses[0]) if analyses else 0,
            "instance": instance,
        }

    @app.get("/api/internal/full-functional-test", include_in_schema=False)
    async def full_functional_test(request: Request, token: str):
        if not _allowed(token):
            raise HTTPException(404, "Not Found")

        import professional_auth_v3 as auth
        import server
        import supabase_runtime as storage

        started = time.perf_counter()
        base = str(request.base_url).rstrip("/")
        result: dict = {
            "ok": False,
            "scope": "implemented-production-utilities",
            "filesGenerated": [],
            "checks": {},
            "failures": [],
            "cleanup": {},
        }
        project_id = ""
        uploaded_objects: dict[str, str] = {}
        file_ids: dict[str, str] = {}
        payloads: dict[str, bytes] = {}

        def check(name: str, condition: bool, detail=None):
            result["checks"][name] = {"ok": bool(condition), "detail": detail}
            if not condition:
                result["failures"].append({"check": name, "detail": detail})

        try:
            owner = auth._owner()
            if not owner:
                raise RuntimeError("Conta proprietária não encontrada no PostgreSQL.")
            session = auth._sign_user(owner, True)
            cookies = {"vaelith_session": session}

            budget = _budget_csv()
            payloads = {
                "ARQ_TORRE_A_R01.ifc": _ifc("ARQ_TORRE_A_R01.ifc", "ARQ", "R01"),
                "ARQ_TORRE_A_R02.ifc": _ifc("ARQ_TORRE_A_R02.ifc", "ARQ", "R02"),
                "EST_TORRE_A_R01.ifc": _ifc("EST_TORRE_A_R01.ifc", "EST", "R01"),
                "HID_TORRE_A_R01.ifc": _ifc("HID_TORRE_A_R01.ifc", "HID", "R01"),
                "SAN_TORRE_A_R01.ifc": _ifc("SAN_TORRE_A_R01.ifc", "SAN", "R01"),
                "ELE_TORRE_A_R01.dwg": b"VAELITH SYNTHETIC DWG - ELECTRICAL R01 - NOT A REAL DWG\n",
                "HVAC_TORRE_A_R01.dwg": b"VAELITH SYNTHETIC DWG - HVAC R01 - NOT A REAL DWG\n",
                "PCI_TORRE_A_R01.pdf": _pdf("FIRE PROTECTION R01"),
                "AUT_TORRE_A_R01.pdf": _pdf("AUTOMATION R01"),
                "ORC_TORRE_A_R01.csv": budget,
                "ORC_COPIA_R01.csv": budget,
                "CRONO_TORRE_A_R01.mpp": b"VAELITH SYNTHETIC SCHEDULE R01 - NOT A REAL MPP\n",
                "MEMORIAL_TORRE_A_R01.pdf": _pdf("SCOPE AND SPECIFICATIONS R01"),
                "DOCUMENTO_SEM_CODIGO_R01.pdf": _pdf("UNKNOWN DISCIPLINE R01"),
            }
            result["filesGenerated"] = [
                {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in payloads.items()
            ]

            async with httpx.AsyncClient(timeout=90.0, follow_redirects=False, trust_env=False) as client:
                health = await client.get(f"{base}/api/health", headers={"cache-control": "no-cache"})
                storage_status = await client.get(f"{base}/api/storage/status", headers={"cache-control": "no-cache"})
                auth_status = await client.get(f"{base}/api/auth/professional-status", headers={"cache-control": "no-cache"})
                platform_self_test = await client.get(f"{base}/api/platform/self-test", headers={"cache-control": "no-cache"})
                login_page = await client.get(f"{base}/login")
                app_without_session = await client.get(f"{base}/app")
                app_with_session = await client.get(f"{base}/app", cookies=cookies)
                css = await client.get(f"{base}/platform-v3.css")
                unified_js = await client.get(f"{base}/unified-ui.js")
                upload_js = await client.get(f"{base}/supabase-upload-v2.js")
                me = await client.get(f"{base}/api/me", cookies=cookies)
                catalog = await client.get(f"{base}/api/catalog/disciplines", cookies=cookies)
                projects_unauth = await client.get(f"{base}/api/projects")

                health_data = health.json() if health.status_code == 200 else {}
                storage_data = storage_status.json() if storage_status.status_code == 200 else {}
                auth_data = auth_status.json() if auth_status.status_code == 200 else {}
                self_test_data = platform_self_test.json() if platform_self_test.status_code == 200 else {}
                catalog_data = catalog.json() if catalog.status_code == 200 else []

                check("health", health.status_code == 200 and health_data.get("database") == "postgresql-shared" and health_data.get("storage") == "supabase-private" and health_data.get("maxUploadMb") == 50, health_data)
                check("storage_status", storage_status.status_code == 200 and storage_data.get("bucketReady") is True and storage_data.get("directUpload") is True and storage_data.get("maxFileMb") == 50, storage_data)
                check("professional_auth", auth_status.status_code == 200 and auth_data.get("ownerConfigured") is True and auth_data.get("database") == "postgresql", auth_data)
                check("platform_self_test", platform_self_test.status_code == 200 and self_test_data.get("ok") is True, self_test_data)
                check("login_page", login_page.status_code == 200 and "Entrar na plataforma" in login_page.text, login_page.status_code)
                check("app_protection", app_without_session.status_code in {307, 401} and app_with_session.status_code == 200, {"without": app_without_session.status_code, "with": app_with_session.status_code})
                check("frontend_assets", css.status_code == 200 and len(css.content) > 5000 and unified_js.status_code == 200 and len(unified_js.content) > 1000 and upload_js.status_code == 200 and b"maxFileMb=50" in upload_js.content, {"css": len(css.content), "unifiedJs": len(unified_js.content), "uploadJs": len(upload_js.content)})
                check("current_user", me.status_code == 200 and me.json().get("id") == owner["id"], me.json() if me.status_code == 200 else me.text[:200])
                check("discipline_catalog", catalog.status_code == 200 and len(catalog_data) == 11, {"status": catalog.status_code, "count": len(catalog_data) if isinstance(catalog_data, list) else None})
                check("unauthenticated_blocked", projects_unauth.status_code == 401, projects_unauth.status_code)

                # Audit route uniqueness and ensure the removed temporary handlers are absent.
                pairs = []
                legacy = []
                for route in app.routes:
                    path = getattr(route, "path", None)
                    endpoint = getattr(getattr(route, "endpoint", None), "__name__", "")
                    for method in sorted(getattr(route, "methods", set()) or set()):
                        pairs.append((method, path))
                    if endpoint in {"health", "upload", "delete_file", "download_file"}:
                        legacy.append({"path": path, "endpoint": endpoint})
                duplicates = [
                    {"method": method, "path": path, "count": count}
                    for (method, path), count in Counter(pairs).items()
                    if count > 1
                ]
                check("route_audit", not duplicates and not legacy, {"routeCount": len(pairs), "duplicates": duplicates, "legacy": legacy})

                created = await client.post(
                    f"{base}/api/projects",
                    cookies=cookies,
                    json={
                        "name": "VAELITH — TESTE FUNCIONAL COMPLETO",
                        "client": "Validação automática isolada",
                        "location": "Betim/MG",
                        "phase": "Compatibilização de projetos",
                    },
                )
                created_data = created.json() if created.status_code == 200 else {}
                project_id = str(created_data.get("id") or "")
                check("create_project", created.status_code == 200 and bool(project_id), {"status": created.status_code, "data": created_data})

                project_list = await client.get(f"{base}/api/projects", cookies=cookies)
                project_list_data = project_list.json() if project_list.status_code == 200 else []
                check("list_project", project_list.status_code == 200 and any(item.get("id") == project_id for item in project_list_data), {"status": project_list.status_code, "found": any(item.get("id") == project_id for item in project_list_data) if isinstance(project_list_data, list) else False})

                # File validation rules before real uploads.
                exact_50 = await client.post(
                    f"{base}/api/projects/{project_id}/uploads/sign",
                    cookies=cookies,
                    json={"name": "LIMITE_R01.ifc", "size": 50 * 1024 * 1024, "mime": "application/octet-stream"},
                )
                over_50 = await client.post(
                    f"{base}/api/projects/{project_id}/uploads/sign",
                    cookies=cookies,
                    json={"name": "ACIMA_R01.ifc", "size": 50 * 1024 * 1024 + 1, "mime": "application/octet-stream"},
                )
                invalid_ext = await client.post(
                    f"{base}/api/projects/{project_id}/uploads/sign",
                    cookies=cookies,
                    json={"name": "MALWARE.exe", "size": 100, "mime": "application/octet-stream"},
                )
                zero_size = await client.post(
                    f"{base}/api/projects/{project_id}/uploads/sign",
                    cookies=cookies,
                    json={"name": "VAZIO_R01.pdf", "size": 0, "mime": "application/pdf"},
                )
                check("file_validation", exact_50.status_code == 200 and over_50.status_code == 413 and invalid_ext.status_code == 415 and zero_size.status_code == 400, {"exact50": exact_50.status_code, "over50": over_50.status_code, "invalidExt": invalid_ext.status_code, "zero": zero_size.status_code})

                upload_results = []
                for filename, payload in payloads.items():
                    mime = "text/csv" if filename.endswith(".csv") else "application/octet-stream"
                    signed = await client.post(
                        f"{base}/api/projects/{project_id}/uploads/sign",
                        cookies=cookies,
                        json={"name": filename, "size": len(payload), "mime": mime},
                    )
                    signed_data = signed.json() if signed.status_code == 200 else {}
                    file_id = str(signed_data.get("fileId") or "")
                    object_path = str(signed_data.get("path") or "")
                    signed_url = str(signed_data.get("signedUrl") or "")
                    put = await client.put(
                        signed_url,
                        content=payload,
                        headers={"content-type": mime},
                        follow_redirects=True,
                    ) if signed_url else None
                    uploaded = bool(put and 200 <= put.status_code < 300)
                    if uploaded and object_path:
                        uploaded_objects[filename] = object_path
                    confirm = await client.post(
                        f"{base}/api/projects/{project_id}/uploads/confirm",
                        cookies=cookies,
                        json={
                            "fileId": file_id,
                            "path": object_path,
                            "name": filename,
                            "size": len(payload),
                            "mime": mime,
                        },
                    ) if uploaded else None
                    if confirm is not None and confirm.status_code == 200:
                        file_ids[filename] = file_id
                    upload_results.append({
                        "name": filename,
                        "signed": signed.status_code,
                        "uploaded": uploaded,
                        "confirmed": confirm.status_code if confirm is not None else None,
                        "fileId": file_id,
                    })
                check("upload_all_generated_files", len(upload_results) == len(payloads) and all(item["signed"] == 200 and item["uploaded"] and item["confirmed"] == 200 for item in upload_results), upload_results)

                listed_files = await client.get(f"{base}/api/projects/{project_id}/files", cookies=cookies)
                listed_data = listed_files.json() if listed_files.status_code == 200 else []
                listed_names = {item.get("name") for item in listed_data} if isinstance(listed_data, list) else set()
                check("list_uploaded_files", listed_files.status_code == 200 and len(listed_data) == 14 and listed_names == set(payloads), {"status": listed_files.status_code, "count": len(listed_data) if isinstance(listed_data, list) else None, "missing": sorted(set(payloads) - listed_names)})

                download_results = []
                for filename, payload in payloads.items():
                    fid = file_ids.get(filename, "")
                    response = await client.get(
                        f"{base}/api/projects/{project_id}/files/{fid}/download",
                        cookies=cookies,
                        follow_redirects=True,
                    )
                    download_results.append({
                        "name": filename,
                        "status": response.status_code,
                        "bytes": len(response.content),
                        "matched": response.content == payload,
                    })
                check("download_and_byte_integrity", all(item["status"] == 200 and item["matched"] for item in download_results), download_results)

                budget_initial = await client.get(f"{base}/api/projects/{project_id}/budget/equalization", cookies=cookies)
                budget_initial_data = budget_initial.json() if budget_initial.status_code == 200 else {}
                check("budget_duplicate_import", budget_initial.status_code == 200 and budget_initial_data.get("items") == 18 and abs(float(budget_initial_data.get("total") or 0) - 128410.0) < 0.01 and budget_initial_data.get("unmatched") == 2, budget_initial_data)

                round1 = await client.post(f"{base}/api/projects/{project_id}/compatibility", cookies=cookies)
                r1 = round1.json() if round1.status_code == 200 else {}
                r1_codes = {item.get("code") for item in r1.get("issues", [])}
                check("compatibility_round_1", round1.status_code == 200 and r1.get("files") == 14 and len(r1.get("disciplines") or []) == 11 and len(r1.get("interfacePackages") or []) == 16 and r1.get("gate") == "Bloqueada" and {"DOC-UNK", "REV-ARQ", "DUP-01"}.issubset(r1_codes), {"status": round1.status_code, "gate": r1.get("gate"), "readiness": r1.get("readiness"), "files": r1.get("files"), "disciplines": len(r1.get("disciplines") or []), "interfaces": len(r1.get("interfacePackages") or []), "codes": sorted(r1_codes)})

                unknown_id = file_ids["DOCUMENTO_SEM_CODIGO_R01.pdf"]
                classify = await client.patch(
                    f"{base}/api/projects/{project_id}/files/{unknown_id}",
                    cookies=cookies,
                    json={"discipline_code": "ESC", "revision": "R01"},
                )
                invalid_classification = await client.patch(
                    f"{base}/api/projects/{project_id}/files/{unknown_id}",
                    cookies=cookies,
                    json={"discipline_code": "INVALIDA", "revision": "R01"},
                )
                check("manual_classification", classify.status_code == 200 and invalid_classification.status_code == 400, {"valid": classify.status_code, "invalid": invalid_classification.status_code})

                round2 = await client.post(f"{base}/api/projects/{project_id}/compatibility", cookies=cookies)
                r2 = round2.json() if round2.status_code == 200 else {}
                r2_codes = {item.get("code") for item in r2.get("issues", [])}
                check("compatibility_round_2", round2.status_code == 200 and "DOC-UNK" not in r2_codes and {"REV-ARQ", "DUP-01"}.issubset(r2_codes) and int(r2.get("readiness") or 0) >= int(r1.get("readiness") or 0), {"gate": r2.get("gate"), "readiness": r2.get("readiness"), "codes": sorted(r2_codes)})

                delete_old_arq = await client.delete(
                    f"{base}/api/projects/{project_id}/files/{file_ids['ARQ_TORRE_A_R01.ifc']}",
                    cookies=cookies,
                )
                uploaded_objects.pop("ARQ_TORRE_A_R01.ifc", None)
                delete_duplicate_budget = await client.delete(
                    f"{base}/api/projects/{project_id}/files/{file_ids['ORC_COPIA_R01.csv']}",
                    cookies=cookies,
                )
                uploaded_objects.pop("ORC_COPIA_R01.csv", None)
                check("delete_files", delete_old_arq.status_code == 204 and delete_duplicate_budget.status_code == 204, {"oldArq": delete_old_arq.status_code, "duplicateBudget": delete_duplicate_budget.status_code})

                budget_final = await client.get(f"{base}/api/projects/{project_id}/budget/equalization", cookies=cookies)
                budget_final_data = budget_final.json() if budget_final.status_code == 200 else {}
                category_map = {item.get("code"): item for item in budget_final_data.get("categories", [])}
                coverage_ok = all(category_map.get(code, {}).get("projectReceived") is True for code in ["ARQ", "EST", "HID", "SAN", "ELE", "HVAC", "PCI"])
                check("budget_final_equalization", budget_final.status_code == 200 and budget_final_data.get("items") == 9 and abs(float(budget_final_data.get("total") or 0) - 64205.0) < 0.01 and budget_final_data.get("unmatched") == 1 and coverage_ok and category_map.get("OUT", {}).get("projectReceived") is False, budget_final_data)

                round3 = await client.post(f"{base}/api/projects/{project_id}/compatibility", cookies=cookies)
                r3 = round3.json() if round3.status_code == 200 else {}
                r3_codes = {item.get("code") for item in r3.get("issues", [])}
                geometric = r3.get("geometricEngine") or {}
                check("compatibility_round_3_release", round3.status_code == 200 and r3.get("files") == 12 and len(r3.get("disciplines") or []) == 11 and len(r3.get("interfacePackages") or []) == 16 and r3.get("gate") == "Pronta para conferência integrada" and r3.get("readiness") == 100 and not ({"DOC-UNK", "REV-ARQ", "DUP-01"} & r3_codes) and len(geometric.get("eligibleIfcFiles") or []) == 4, {"gate": r3.get("gate"), "readiness": r3.get("readiness"), "files": r3.get("files"), "disciplines": len(r3.get("disciplines") or []), "interfaces": len(r3.get("interfacePackages") or []), "summary": r3.get("summary"), "geometric": geometric})

                latest = await client.get(f"{base}/api/projects/{project_id}/compatibility/latest", cookies=cookies)
                exported = await client.get(f"{base}/api/projects/{project_id}/export", cookies=cookies)
                latest_data = latest.json() if latest.status_code == 200 else {}
                export_data = exported.json() if exported.status_code == 200 else {}
                check("latest_and_export_report", latest.status_code == 200 and exported.status_code == 200 and latest_data.get("id") == r3.get("id") and export_data.get("id") == r3.get("id") and "attachment" in exported.headers.get("content-disposition", "").lower(), {"latest": latest.status_code, "export": exported.status_code, "sameAnalysis": latest_data.get("id") == r3.get("id") == export_data.get("id"), "contentDisposition": exported.headers.get("content-disposition")})

                issue1 = await client.post(
                    f"{base}/api/projects/{project_id}/operational/issues",
                    cookies=cookies,
                    json={
                        "analysisId": r3.get("id"),
                        "title": "Interferência entre viga e prumada sanitária",
                        "description": "A prumada projetada atravessa a faixa prevista para uma viga estrutural.",
                        "issueType": "incompatibilidade",
                        "severity": "critica",
                        "location": "Pavimento 02 — eixo B/04",
                        "disciplines": ["EST", "SAN"],
                        "assignee": "Coordenação de Projetos",
                        "dueDate": "2026-08-07",
                    },
                )
                issue2 = await client.post(
                    f"{base}/api/projects/{project_id}/operational/issues",
                    cookies=cookies,
                    json={
                        "analysisId": r3.get("id"),
                        "title": "Alteração da altura do forro técnico",
                        "description": "Mudança necessária para acomodar dutos e eletrocalhas no corredor principal.",
                        "issueType": "mudanca",
                        "severity": "alta",
                        "location": "Pavimento 01 — corredor central",
                        "disciplines": ["ARQ", "HVAC", "ELE"],
                        "assignee": "Arquitetura",
                    },
                )
                invalid_issue = await client.post(
                    f"{base}/api/projects/{project_id}/operational/issues",
                    cookies=cookies,
                    json={"title": "Inválida", "description": "Teste", "issueType": "x", "severity": "gigante"},
                )
                issue1_data = issue1.json() if issue1.status_code == 200 else {}
                issue2_data = issue2.json() if issue2.status_code == 200 else {}
                issue1_id = str(issue1_data.get("id") or "")
                issue2_id = str(issue2_data.get("id") or "")
                check("create_operational_issues", issue1.status_code == 200 and issue2.status_code == 200 and invalid_issue.status_code == 400 and bool(issue1_id) and bool(issue2_id), {"issue1": issue1.status_code, "issue2": issue2.status_code, "invalid": invalid_issue.status_code})

                decision = await client.post(
                    f"{base}/api/projects/{project_id}/operational/issues/{issue1_id}/decisions",
                    cookies=cookies,
                    json={
                        "title": "Desviar a prumada pelo shaft adjacente",
                        "rationale": "Preserva a seção estrutural e evita abertura posterior na viga.",
                        "approved": True,
                    },
                )
                impact1 = await client.post(
                    f"{base}/api/projects/{project_id}/operational/issues/{issue1_id}/impacts",
                    cookies=cookies,
                    json={
                        "costAmount": 18750.50,
                        "currency": "BRL",
                        "scheduleDays": 5,
                        "activityReference": "HID-230 — Prumadas",
                        "basis": "Composição sintética: material, mão de obra, revisão de projeto e mobilização.",
                        "confidence": "estimado",
                    },
                )
                impact2 = await client.post(
                    f"{base}/api/projects/{project_id}/operational/issues/{issue2_id}/impacts",
                    cookies=cookies,
                    json={
                        "costAmount": 3200,
                        "currency": "BRL",
                        "scheduleDays": 2,
                        "activityReference": "ARQ-410 — Forros",
                        "basis": "Revisão de perfis, recortes e reprogramação da equipe.",
                        "confidence": "estimado",
                    },
                )
                invalid_impact = await client.post(
                    f"{base}/api/projects/{project_id}/operational/issues/{issue2_id}/impacts",
                    cookies=cookies,
                    json={"costAmount": "abc", "scheduleDays": -1, "basis": ""},
                )
                check("decisions_and_impacts", decision.status_code == 200 and decision.json().get("approved") is True and impact1.status_code == 200 and impact2.status_code == 200 and invalid_impact.status_code == 400, {"decision": decision.status_code, "impact1": impact1.status_code, "impact2": impact2.status_code, "invalidImpact": invalid_impact.status_code})

                status_sequence = [
                    "em_analise",
                    "aguardando_responsavel",
                    "solucao_proposta",
                    "solucao_aprovada",
                    "projeto_revisado",
                    "liberada_execucao",
                    "executada",
                    "verificada",
                    "encerrada",
                ]
                status_results = []
                for status in status_sequence:
                    changed = await client.patch(
                        f"{base}/api/projects/{project_id}/operational/issues/{issue1_id}/status",
                        cookies=cookies,
                        json={"status": status, "comment": f"Transição automática para {status}."},
                    )
                    status_results.append({"status": status, "http": changed.status_code, "returned": changed.json().get("status") if changed.status_code == 200 else None})
                issue2_status = await client.patch(
                    f"{base}/api/projects/{project_id}/operational/issues/{issue2_id}/status",
                    cookies=cookies,
                    json={"status": "em_analise", "comment": "Mudança em avaliação."},
                )
                invalid_status = await client.patch(
                    f"{base}/api/projects/{project_id}/operational/issues/{issue2_id}/status",
                    cookies=cookies,
                    json={"status": "status_inexistente"},
                )
                check("complete_issue_workflow", all(item["http"] == 200 and item["returned"] == item["status"] for item in status_results) and issue2_status.status_code == 200 and invalid_status.status_code == 400, {"issue1": status_results, "issue2": issue2_status.status_code, "invalid": invalid_status.status_code})

                issues_list = await client.get(f"{base}/api/projects/{project_id}/operational/issues", cookies=cookies)
                dashboard = await client.get(f"{base}/api/projects/{project_id}/operational/dashboard", cookies=cookies)
                workflow = await client.get(f"{base}/api/projects/{project_id}/operational/workflow", cookies=cookies)
                issues_data = issues_list.json() if issues_list.status_code == 200 else []
                dashboard_data = dashboard.json() if dashboard.status_code == 200 else {}
                workflow_data = workflow.json() if workflow.status_code == 200 else {}
                check("operational_dashboard", issues_list.status_code == 200 and len(issues_data) == 2 and dashboard.status_code == 200 and dashboard_data.get("totalIssues") == 2 and dashboard_data.get("openIssues") == 1 and dashboard_data.get("criticalIssues") == 1 and abs(float(dashboard_data.get("estimatedCost") or 0) - 21950.5) < 0.01 and dashboard_data.get("estimatedDays") == 7 and workflow.status_code == 200 and len(workflow_data.get("steps") or []) == 11, {"issues": len(issues_data) if isinstance(issues_data, list) else None, "dashboard": dashboard_data, "workflowSteps": len(workflow_data.get("steps") or [])})

                with server.conn() as c:
                    history_count = c.execute("SELECT COUNT(*) FROM issue_history WHERE issue_id=?", (issue1_id,)).fetchone()[0]
                    decision_count = c.execute("SELECT COUNT(*) FROM issue_decisions WHERE issue_id=?", (issue1_id,)).fetchone()[0]
                    impact_count = c.execute("SELECT COUNT(*) FROM issue_impacts WHERE issue_id IN (?,?)", (issue1_id, issue2_id)).fetchone()[0]
                    file_count = c.execute("SELECT COUNT(*) FROM files WHERE project_id=?", (project_id,)).fetchone()[0]
                    analysis_count = c.execute("SELECT COUNT(*) FROM analyses WHERE project_id=?", (project_id,)).fetchone()[0]
                    budget_count = c.execute("SELECT COUNT(*) FROM budget_items WHERE project_id=?", (project_id,)).fetchone()[0]
                check("database_persistence_details", history_count == 10 and decision_count == 1 and impact_count == 2 and file_count == 12 and analysis_count == 3 and budget_count == 9, {"history": history_count, "decisions": decision_count, "impacts": impact_count, "files": file_count, "analyses": analysis_count, "budgetItems": budget_count})

                # Repeated reads through many serverless instances after the complete workflow.
                read_url = f"{base}/api/internal/full-functional-read"
                reads = await asyncio.gather(*[
                    client.get(
                        read_url,
                        params={"token": token, "project_id": project_id},
                        headers={"cache-control": "no-cache", "x-vaelith-test": uuid4().hex},
                    )
                    for _ in range(32)
                ], return_exceptions=True)
                parsed_reads = []
                read_errors = []
                for item in reads:
                    if isinstance(item, Exception):
                        read_errors.append(f"{type(item).__name__}: {item}")
                        continue
                    try:
                        data = item.json()
                    except Exception:
                        read_errors.append(f"HTTP {item.status_code}: resposta inválida")
                        continue
                    parsed_reads.append(data)
                    if item.status_code != 200:
                        read_errors.append(f"HTTP {item.status_code}: {data}")
                instances = sorted({item.get("instance") for item in parsed_reads if item.get("instance")})
                inconsistent = [item for item in parsed_reads if not item.get("projectFound") or item.get("files") != 12 or item.get("analyses") != 3]
                check("cross_instance_complete_state", len(parsed_reads) == 32 and not read_errors and not inconsistent and len(instances) >= 2, {"requests": 32, "responses": len(parsed_reads), "instances": len(instances), "inconsistent": inconsistent[:3], "errors": read_errors[:3]})

                # Verify standard security headers on the final authenticated response.
                security_headers = {
                    "strict-transport-security": dashboard.headers.get("strict-transport-security"),
                    "x-content-type-options": dashboard.headers.get("x-content-type-options"),
                    "x-frame-options": dashboard.headers.get("x-frame-options"),
                    "content-security-policy": dashboard.headers.get("content-security-policy"),
                }
                check("security_headers", bool(security_headers["strict-transport-security"]) and security_headers["x-content-type-options"] == "nosniff" and security_headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in str(security_headers["content-security-policy"]), security_headers)

                result["compatibility"] = {
                    "round1": {"gate": r1.get("gate"), "readiness": r1.get("readiness"), "files": r1.get("files"), "interfaces": len(r1.get("interfacePackages") or []), "documentFindings": sorted(code for code in r1_codes if code in {"DOC-UNK", "REV-ARQ", "DUP-01"})},
                    "round2": {"gate": r2.get("gate"), "readiness": r2.get("readiness"), "files": r2.get("files"), "documentFindings": sorted(code for code in r2_codes if code in {"DOC-UNK", "REV-ARQ", "DUP-01"})},
                    "round3": {"gate": r3.get("gate"), "readiness": r3.get("readiness"), "files": r3.get("files"), "disciplines": len(r3.get("disciplines") or []), "interfaces": len(r3.get("interfacePackages") or []), "summary": r3.get("summary"), "eligibleIfcFiles": geometric.get("eligibleIfcFiles"), "geometricStatus": geometric.get("status")},
                }
                result["budget"] = {"initial": budget_initial_data, "final": budget_final_data}
                result["operational"] = {"issues": issues_data, "dashboard": dashboard_data, "workflow": workflow_data, "historyRecords": history_count, "decisionRecords": decision_count, "impactRecords": impact_count}
                result["platform"] = {"health": health_data, "storage": storage_data, "auth": auth_data, "routes": result["checks"]["route_audit"]["detail"]}

        except Exception as exc:
            result["failures"].append({"check": "unhandled_exception", "detail": f"{type(exc).__name__}: {str(exc)[:500]}"})
        finally:
            # Remove every physical object that may still exist. Public delete was
            # already exercised for two files; this is deterministic cleanup.
            storage_cleanup = []
            try:
                for filename, object_path in list(uploaded_objects.items()):
                    encoded = quote(object_path, safe="/")
                    response = storage._request(
                        "DELETE",
                        f"/object/{quote(storage.BUCKET, safe='')}/{encoded}",
                        timeout=45.0,
                    )
                    storage_cleanup.append({"name": filename, "status": response.status_code})
                result["cleanup"]["storage"] = {
                    "attempted": len(storage_cleanup),
                    "ok": all(item["status"] in {200, 204, 404} for item in storage_cleanup),
                    "results": storage_cleanup,
                }
            except Exception as exc:
                result["cleanup"]["storage"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            try:
                _cleanup_database(project_id)
                result["cleanup"]["database"] = {"ok": True, "projectRemoved": bool(project_id)}
            except Exception as exc:
                result["cleanup"]["database"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

            essential_checks_ok = bool(result["checks"]) and all(item.get("ok") for item in result["checks"].values())
            cleanup_ok = all(item.get("ok") for item in result["cleanup"].values()) if result["cleanup"] else False
            result["ok"] = essential_checks_ok and cleanup_ok and not result["failures"]
            result["summary"] = {
                "checks": len(result["checks"]),
                "passed": sum(1 for item in result["checks"].values() if item.get("ok")),
                "failed": sum(1 for item in result["checks"].values() if not item.get("ok")),
                "generatedFiles": len(result["filesGenerated"]),
                "durationSeconds": round(time.perf_counter() - started, 3),
            }

        return result
