from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from professional_report_runtime import TEMPLATES, render_professional_pdf


def _snapshot(template: str) -> dict:
    return {
        "project": {"name": "Empreendimento Demonstração VAELITH", "client": "Cliente Demonstração", "location": "Betim/MG", "phase": "Compatibilização"},
        "analysis": {"readiness": 92, "gate": "Em análise", "interfacePackages": [{"id": "1"}, {"id": "2"}, {"id": "3"}]},
        "files": [
            {"name": "ARQ_R02.ifc", "discipline": "Arquitetura", "revision": "R02", "ext": ".ifc", "size": 1200000},
            {"name": "EST_R01.ifc", "discipline": "Estrutura", "revision": "R01", "ext": ".ifc", "size": 900000},
            {"name": "MEMORIAL_R02.pdf", "discipline": "Escopo e memoriais", "revision": "R02", "ext": ".pdf", "size": 320000},
        ],
        "issues": [
            {"code": "OCO-001", "severity": "critica", "status": "em_analise", "title": "Interferência entre viga e tubulação hidráulica", "assignee": "Coordenação de Projetos"},
            {"code": "OCO-002", "severity": "alta", "status": "solucao_proposta", "title": "Ajuste de altura do forro técnico", "assignee": "Arquitetura"},
        ],
        "decisions": [
            {"code": "OCO-001", "decision": "Desviar a tubulação preservando a seção estrutural da viga.", "decided_by": "Coordenação de Projetos", "created": "2026-08-02T10:00:00+00:00"}
        ],
        "impacts": {
            "summary": {"records": 2, "cost": 21950.50, "days": 7, "issuesAffected": 2, "confirmedCost": 12850.75},
            "records": [
                {"code": "OCO-001", "basis": "Memória de impacto", "cost_amount": 12850.75, "schedule_days": 4},
                {"code": "OCO-002", "basis": "Estimativa preliminar", "cost_amount": 9099.75, "schedule_days": 3},
            ],
        },
        "planning": {
            "summary": {"total": 3, "completed": 0, "inProgress": 2, "blocked": 1, "critical": 1, "delayed": 1, "averageProgress": 35.0},
            "activities": [
                {"code": "PLN-001", "name": "Revisar interferência estrutural x hidráulica", "owner": "Coordenação", "status": "in_progress", "progress": 35},
                {"code": "PLN-002", "name": "Emitir revisão arquitetônica", "owner": "Arquitetura", "status": "blocked", "progress": 10},
            ],
        },
        "changes": {
            "summary": {"total": 2, "open": 1, "costDelta": 3200.50, "scheduleDelta": 2},
            "changes": [
                {"code": "MUD-001", "status": "approved", "title": "Alteração de rota hidráulica", "reason": "Eliminar interferência com elemento estrutural", "cost_delta": 3200.50, "schedule_delta": 2},
                {"code": "MUD-002", "status": "closed", "title": "Ajuste de forro técnico", "reason": "Compatibilização com climatização", "cost_delta": 0, "schedule_delta": 0},
            ],
        },
        "revisions": {
            "conflicts": 0,
            "groups": [
                {"disciplineCode": "ARQ", "distinctRevisions": ["R01", "R02"], "conflict": False, "versions": [{"controlStatus": "superseded"}, {"controlStatus": "active"}]},
                {"disciplineCode": "EST", "distinctRevisions": ["R01"], "conflict": False, "versions": [{"controlStatus": "active"}]},
            ],
        },
        "budget": {"items": 9, "total": 64205.00, "rows": []},
        "bimJobs": [{"created": "2026-08-02T09:00:00+00:00", "mode": "intersection", "status": "completed", "result": {"summary": {"clashes": 1}}}],
        "pdfStats": {"analyzed": 2, "pages": 14, "scanned": 0},
        "report": {
            "template": template,
            "templateName": TEMPLATES[template]["name"],
            "documentCode": f"VAE-{TEMPLATES[template]['code']}-TESTE",
            "revision": "R00",
            "preparedBy": "Equipe Técnica VAELITH",
            "title": f"{TEMPLATES[template]['name']} - Empreendimento Demonstração",
            "notes": "Documento sintético utilizado exclusivamente para validar o motor de geração de relatórios.",
            "generatedAt": "2026-08-02T10:30:00+00:00",
            "includeAppendices": True,
        },
    }


def install(app: FastAPI) -> None:
    if getattr(app.state, "_vaelith_report_selftest", False):
        return
    app.state._vaelith_report_selftest = True

    @app.get("/api/platform/report-template-status", include_in_schema=False)
    def report_template_status():
        results = {}
        errors = []
        try:
            from pypdf import PdfReader
        except Exception as exc:
            return {"ok": False, "errors": [f"pypdf: {type(exc).__name__}: {exc}"]}
        import io
        for template in TEMPLATES:
            try:
                payload = render_professional_pdf(_snapshot(template))
                reader = PdfReader(io.BytesIO(payload))
                valid = payload.startswith(b"%PDF-") and len(reader.pages) >= 2
                results[template] = {"ok": valid, "bytes": len(payload), "pages": len(reader.pages), "signature": payload[:8].decode("latin1", "ignore")}
                if not valid:
                    errors.append(f"{template}: PDF inválido")
            except Exception as exc:
                results[template] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}
                errors.append(f"{template}: {type(exc).__name__}: {str(exc)[:180]}")
        return {"ok": not errors, "templates": results, "errors": errors}

    @app.get("/api/platform/report-template-sample/{template}", include_in_schema=False)
    def report_template_sample(template: str):
        if template not in TEMPLATES:
            raise HTTPException(404, "Modelo não encontrado.")
        payload = render_professional_pdf(_snapshot(template))
        return Response(payload, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="vaelith-{template}-sample.pdf"', "Cache-Control": "no-store"})
