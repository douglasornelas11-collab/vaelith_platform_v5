from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from html import escape
from uuid import uuid4

from fastapi import Cookie, FastAPI, HTTPException, Request
from fastapi.responses import Response

TEMPLATES = {
    "executive": {
        "name": "Relatório Executivo",
        "description": "Visão gerencial de prontidão, riscos, custo, prazo, mudanças e decisões prioritárias.",
        "code": "EXEC",
    },
    "coordination": {
        "name": "Relatório de Compatibilização",
        "description": "Base documental, revisões, interfaces, ocorrências e resultados de coordenação BIM/IFC.",
        "code": "COMP",
    },
    "operational": {
        "name": "Relatório Operacional",
        "description": "Ocorrências, responsáveis, planejamento, impactos, decisões e acompanhamento de execução.",
        "code": "OPER",
    },
    "change_control": {
        "name": "Relatório de Controle de Mudanças",
        "description": "Solicitações, justificativas, aprovações, variações de custo/prazo e situação das alterações.",
        "code": "MUD",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _server():
    import server
    return server


def _runtime():
    import complete_runtime_v1
    return complete_runtime_v1


def _context(pid: str, token: str | None):
    srv = _server()
    user = srv.require_user(token)
    project = srv.require_project(pid, user["id"])
    return srv, user, project


def _json(raw: bytes) -> dict:
    try:
        value = json.loads(raw or b"{}")
    except Exception as exc:
        raise HTTPException(400, "JSON inválido.") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "O corpo deve ser um objeto JSON.")
    return value


def _brl(value) -> str:
    text = f"{float(value or 0):,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_date(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(value)[:16]


def _safe_filename(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", value or "relatorio")
    return text.strip("_")[:80] or "relatorio"


def _int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _float(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _collect_bim(pid: str) -> list[dict]:
    srv = _server()
    try:
        with srv.conn() as c:
            rows = c.execute(
                "SELECT id,status,mode,tolerance,input_files,result,error,created_by,created,finished "
                "FROM bim_jobs WHERE project_id=? ORDER BY created DESC LIMIT 10",
                (pid,),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            for key in ("input_files", "result"):
                try:
                    item[key] = json.loads(item.get(key) or "null")
                except Exception:
                    pass
            out.append(item)
        return out
    except Exception:
        return []


def _collect_pdf_stats(pid: str) -> dict:
    srv = _server()
    try:
        with srv.conn() as c:
            row = c.execute(
                "SELECT COUNT(*) total, COALESCE(SUM(pages),0) pages, "
                "COALESCE(SUM(CASE WHEN scanned_likely=1 THEN 1 ELSE 0 END),0) scanned "
                "FROM pdf_analyses WHERE project_id=?",
                (pid,),
            ).fetchone()
        return {"analyzed": _int(row["total"]), "pages": _int(row["pages"]), "scanned": _int(row["scanned"])}
    except Exception:
        return {"analyzed": 0, "pages": 0, "scanned": 0}


def _build_snapshot(pid: str, template: str, meta: dict) -> dict:
    runtime = _runtime()
    snapshot = runtime.report_snapshot(pid)
    snapshot["report"] = {
        "template": template,
        "templateName": TEMPLATES[template]["name"],
        "documentCode": meta["documentCode"],
        "revision": meta["revision"],
        "preparedBy": meta["preparedBy"],
        "title": meta["title"],
        "notes": meta.get("notes") or "",
        "generatedAt": _now(),
        "includeAppendices": bool(meta.get("includeAppendices", True)),
    }
    snapshot["bimJobs"] = _collect_bim(pid)
    snapshot["pdfStats"] = _collect_pdf_stats(pid)
    return snapshot


def _styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    styles = getSampleStyleSheet()
    return {
        "cover_brand": ParagraphStyle("CoverBrand", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=10, leading=12, textColor=colors.HexColor("#C8FF3D"), spaceAfter=6),
        "cover_title": ParagraphStyle("CoverTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=28, leading=31, textColor=colors.HexColor("#111511"), spaceAfter=12),
        "cover_project": ParagraphStyle("CoverProject", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#263028"), spaceAfter=6),
        "h1": ParagraphStyle("VH1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=19, textColor=colors.HexColor("#111511"), spaceBefore=10, spaceAfter=8),
        "h2": ParagraphStyle("VH2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor("#263028"), spaceBefore=8, spaceAfter=6),
        "body": ParagraphStyle("VBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=colors.HexColor("#303A32"), spaceAfter=5),
        "small": ParagraphStyle("VSmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=6.8, leading=9, textColor=colors.HexColor("#667168")),
        "table": ParagraphStyle("VTable", parent=styles["BodyText"], fontName="Helvetica", fontSize=7, leading=9, textColor=colors.HexColor("#263028")),
        "table_bold": ParagraphStyle("VTableBold", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.HexColor("#111511")),
        "conclusion": ParagraphStyle("VConclusion", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=9, leading=13, textColor=colors.HexColor("#111511"), borderColor=colors.HexColor("#C8FF3D"), borderWidth=1, borderPadding=9, backColor=colors.HexColor("#F5F9ED"), spaceBefore=8, spaceAfter=8),
    }


def _p(value, style):
    from reportlab.platypus import Paragraph
    return Paragraph(escape(str(value or "-")), style)


def _table(data, widths, *, header=True, repeat=1):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle
    table = Table(data, colWidths=widths, repeatRows=repeat if header else 0, hAlign="LEFT")
    rules = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DCE3DC")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        rules += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111511")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ]
    for idx in range(1 if header else 0, len(data)):
        if idx % 2 == 0:
            rules.append(("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#F7F9F6")))
    table.setStyle(TableStyle(rules))
    return table


def _draw_vaelith_symbol(canvas, x, y, size, color):
    canvas.saveState()
    canvas.setStrokeColor(color)
    canvas.setLineWidth(max(1.6, size * 0.105))
    canvas.setLineJoin(1)
    canvas.line(x + size*.13, y + size*.87, x + size*.50, y + size*.16)
    canvas.line(x + size*.50, y + size*.16, x + size*.87, y + size*.87)
    canvas.line(x + size*.33, y + size*.87, x + size*.68, y + size*.87)
    canvas.line(x + size*.68, y + size*.87, x + size*.51, y + size*.54)
    canvas.restoreState()


def _header_footer(canvas, doc, meta: dict):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    width, height = A4
    page = canvas.getPageNumber()
    if page > 1:
        canvas.saveState()
        _draw_vaelith_symbol(canvas, 15*mm, height-15*mm, 8*mm, colors.HexColor("#111511"))
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(colors.HexColor("#111511"))
        canvas.drawString(25*mm, height-10.8*mm, "VAELITH PLATFORM")
        canvas.setFont("Helvetica", 6.2)
        canvas.setFillColor(colors.HexColor("#6A746C"))
        canvas.drawRightString(width-15*mm, height-10.8*mm, f"{meta['documentCode']} | Rev. {meta['revision']}")
        canvas.setStrokeColor(colors.HexColor("#DDE3DC"))
        canvas.line(15*mm, height-14.5*mm, width-15*mm, height-14.5*mm)
        canvas.restoreState()
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#DDE3DC"))
    canvas.line(15*mm, 12*mm, width-15*mm, 12*mm)
    canvas.setFillColor(colors.HexColor("#6A746C"))
    canvas.setFont("Helvetica", 6)
    canvas.drawString(15*mm, 8.2*mm, "Documento controlado - VAELITH Platform")
    canvas.drawCentredString(width/2, 8.2*mm, meta["preparedBy"][:60])
    canvas.drawRightString(width-15*mm, 8.2*mm, f"Página {page}")
    canvas.restoreState()


def _cover(snapshot: dict, styles: dict, meta: dict):
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, PageBreak, Spacer, Table, TableStyle
    project = snapshot["project"]
    items = [Spacer(1, 17*mm), _p("VAELITH LABS | ENGENHARIA + TECNOLOGIA", styles["cover_brand"]), _p(meta["title"], styles["cover_title"]), _p(project.get("name") or "Empreendimento", styles["cover_project"])]
    subtitle = " | ".join(x for x in [project.get("client"), project.get("location"), project.get("phase")] if x)
    if subtitle:
        items.append(_p(subtitle, styles["body"]))
    items.append(Spacer(1, 18*mm))
    data = [
        [_p("Código do documento", styles["table_bold"]), _p(meta["documentCode"], styles["table"])],
        [_p("Revisão", styles["table_bold"]), _p(meta["revision"], styles["table"])],
        [_p("Modelo", styles["table_bold"]), _p(TEMPLATES[meta["template"]]["name"], styles["table"])],
        [_p("Responsável pela emissão", styles["table_bold"]), _p(meta["preparedBy"], styles["table"])],
        [_p("Data de emissão", styles["table_bold"]), _p(_fmt_date(meta["generatedAt"]), styles["table"])],
        [_p("Status", styles["table_bold"]), _p("EMITIDO PELA PLATAFORMA", styles["table"])],
    ]
    table = Table(data, colWidths=[52*mm, 108*mm])
    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#D6DDD5")),
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#EEF3EB")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("PADDING", (0,0), (-1,-1), 7),
    ]))
    items += [KeepTogether(table), Spacer(1, 10*mm), _p("Engenharia como origem. Tecnologia como diferencial.", styles["small"]), PageBreak()]
    return items


def _summary(snapshot: dict, styles: dict):
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Table, TableStyle, Spacer
    analysis = snapshot.get("analysis") or {}
    impacts = snapshot["impacts"]["summary"]
    planning = snapshot["planning"]["summary"]
    changes = snapshot["changes"]["summary"]
    issues = snapshot.get("issues") or []
    opened = sum(str(i.get("status") or "") != "encerrada" for i in issues)
    critical = sum(str(i.get("severity") or "").lower() == "critica" for i in issues)
    cards = [
        ["PRONTIDÃO", f"{_int(analysis.get('readiness'))}%"],
        ["OCORRÊNCIAS ABERTAS", str(opened)],
        ["CRÍTICAS", str(critical)],
        ["IMPACTO FINANCEIRO", f"R$ {_brl(impacts.get('cost'))}"],
        ["IMPACTO EM PRAZO", f"{_int(impacts.get('days'))} dias"],
        ["AVANÇO PLANEJADO", f"{_float(planning.get('averageProgress')):.1f}%".replace(".", ",")],
        ["MUDANÇAS ABERTAS", str(_int(changes.get('open')))],
        ["ARQUIVOS", str(len(snapshot.get("files") or []))],
    ]
    data=[]
    for i in range(0,len(cards),4):
        data.append([_p(x[0], styles["small"]) for x in cards[i:i+4]])
        data.append([_p(x[1], styles["table_bold"]) for x in cards[i:i+4]])
    t=Table(data,colWidths=[42.5*mm]*4)
    t.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),.3,colors.HexColor("#DCE3DC")),
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#F7F9F6")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
    ]))
    return [t, Spacer(1, 5*mm)]


def _executive(snapshot, styles):
    from reportlab.lib.units import mm
    from reportlab.platypus import Spacer
    analysis=snapshot.get("analysis") or {}
    impacts=snapshot["impacts"]["summary"]
    planning=snapshot["planning"]["summary"]
    changes=snapshot["changes"]["summary"]
    issues=snapshot.get("issues") or []
    critical=[i for i in issues if str(i.get("severity") or "").lower() in {"critica","alta"} and str(i.get("status") or "")!="encerrada"]
    conclusion=(
        f"A base apresenta prontidão de {_int(analysis.get('readiness'))}% e gate '{analysis.get('gate') or 'não executado'}'. "
        f"Os impactos registrados totalizam R$ {_brl(impacts.get('cost'))} e {_int(impacts.get('days'))} dias. "
        f"O planejamento possui {_int(planning.get('delayed'))} atividade(s) atrasada(s) e {_int(planning.get('blocked'))} bloqueada(s). "
        f"Existem {_int(changes.get('open'))} mudança(s) aberta(s)."
    )
    data=[[ _p("Código",styles["table_bold"]),_p("Prioridade",styles["table_bold"]),_p("Ocorrência",styles["table_bold"]),_p("Responsável",styles["table_bold"]) ]]
    for item in critical[:20]:
        data.append([_p(item.get("code"),styles["table"]),_p(item.get("severity"),styles["table"]),_p(item.get("title"),styles["table"]),_p(item.get("assignee") or "-",styles["table"])])
    if len(data)==1:
        data.append([_p("-",styles["table"]),_p("-",styles["table"]),_p("Nenhuma ocorrência crítica ou alta em aberto.",styles["table"]),_p("-",styles["table"])])
    return [_p("1. Sumário executivo",styles["h1"]),*_summary(snapshot,styles),_p(conclusion,styles["conclusion"]),_p("2. Prioridades",styles["h1"]),_table(data,[22*mm,27*mm,91*mm,30*mm])]


def _coordination(snapshot, styles):
    from reportlab.lib.units import mm
    from reportlab.platypus import Spacer
    revisions=snapshot["revisions"]
    analysis=snapshot.get("analysis") or {}
    files=snapshot.get("files") or []
    groups=revisions.get("groups") or []
    rev_data=[[_p("Disciplina",styles["table_bold"]),_p("Versões",styles["table_bold"]),_p("Ativa",styles["table_bold"]),_p("Conflito",styles["table_bold"])]]
    for group in groups:
        active=sum(str(v.get("controlStatus"))=="active" for v in group.get("versions") or [])
        rev_data.append([_p(group.get("disciplineCode"),styles["table"]),_p(", ".join(group.get("distinctRevisions") or []),styles["table"]),_p(active,styles["table"]),_p("SIM" if group.get("conflict") else "NÃO",styles["table"])])
    if len(rev_data)==1: rev_data.append([_p("-",styles["table"])]*4)
    file_data=[[_p("Arquivo",styles["table_bold"]),_p("Disciplina",styles["table_bold"]),_p("Revisão",styles["table_bold"]),_p("Formato",styles["table_bold"])]]
    for f in files[:100]:
        file_data.append([_p(f.get("name"),styles["table"]),_p(f.get("discipline"),styles["table"]),_p(f.get("revision"),styles["table"]),_p(str(f.get("ext") or "").upper().replace(".",""),styles["table"])])
    bim_data=[[_p("Data",styles["table_bold"]),_p("Modo",styles["table_bold"]),_p("Status",styles["table_bold"]),_p("Colisões",styles["table_bold"])]]
    for job in snapshot.get("bimJobs") or []:
        result=job.get("result") if isinstance(job.get("result"),dict) else {}
        clashes=((result or {}).get("summary") or {}).get("clashes")
        bim_data.append([_p(_fmt_date(job.get("created")),styles["table"]),_p(job.get("mode"),styles["table"]),_p(job.get("status"),styles["table"]),_p(clashes if clashes is not None else "-",styles["table"])])
    if len(bim_data)==1: bim_data.append([_p("-",styles["table"]),_p("-",styles["table"]),_p("Nenhuma rodada BIM registrada.",styles["table"]),_p("-",styles["table"])])
    return [_p("1. Estado da compatibilização",styles["h1"]),*_summary(snapshot,styles),_p(f"Gate: {analysis.get('gate') or 'não executado'}. Pacotes de interface: {len(analysis.get('interfacePackages') or [])}. Conflitos de revisão: {_int(revisions.get('conflicts'))}.",styles["body"]),_p("2. Controle de revisões",styles["h1"]),_table(rev_data,[30*mm,70*mm,30*mm,30*mm]),Spacer(1,4*mm),_p("3. Inventário documental",styles["h1"]),_table(file_data,[85*mm,42*mm,23*mm,20*mm]),Spacer(1,4*mm),_p("4. Processamentos BIM",styles["h1"]),_table(bim_data,[40*mm,35*mm,45*mm,35*mm])]


def _operational(snapshot, styles):
    from reportlab.lib.units import mm
    from reportlab.platypus import Spacer
    issues=snapshot.get("issues") or []
    planning=snapshot["planning"].get("activities") or []
    impacts=snapshot["impacts"].get("records") or []
    issue_data=[[_p("Código",styles["table_bold"]),_p("Criticidade",styles["table_bold"]),_p("Status",styles["table_bold"]),_p("Título",styles["table_bold"]),_p("Responsável",styles["table_bold"])]]
    for i in issues[:100]: issue_data.append([_p(i.get("code"),styles["table"]),_p(i.get("severity"),styles["table"]),_p(i.get("status"),styles["table"]),_p(i.get("title"),styles["table"]),_p(i.get("assignee") or "-",styles["table"])])
    if len(issue_data)==1: issue_data.append([_p("-",styles["table"])]*5)
    plan_data=[[_p("Código",styles["table_bold"]),_p("Atividade",styles["table_bold"]),_p("Responsável",styles["table_bold"]),_p("Status",styles["table_bold"]),_p("Avanço",styles["table_bold"])]]
    for a in planning[:100]: plan_data.append([_p(a.get("code"),styles["table"]),_p(a.get("name"),styles["table"]),_p(a.get("owner") or "-",styles["table"]),_p(a.get("status"),styles["table"]),_p(f"{_float(a.get('progress')):.0f}%",styles["table"])])
    if len(plan_data)==1: plan_data.append([_p("-",styles["table"])]*5)
    impact_data=[[_p("Ocorrência",styles["table_bold"]),_p("Base",styles["table_bold"]),_p("Custo",styles["table_bold"]),_p("Prazo",styles["table_bold"])]]
    for r in impacts[:100]: impact_data.append([_p(r.get("code") or r.get("issue_id"),styles["table"]),_p(r.get("basis"),styles["table"]),_p(f"R$ {_brl(r.get('cost_amount'))}",styles["table"]),_p(f"{_int(r.get('schedule_days'))} dias",styles["table"])])
    if len(impact_data)==1: impact_data.append([_p("-",styles["table"])]*4)
    return [_p("1. Painel operacional",styles["h1"]),*_summary(snapshot,styles),_p("2. Ocorrências",styles["h1"]),_table(issue_data,[20*mm,24*mm,27*mm,72*mm,27*mm]),Spacer(1,4*mm),_p("3. Planejamento",styles["h1"]),_table(plan_data,[21*mm,69*mm,31*mm,30*mm,19*mm]),Spacer(1,4*mm),_p("4. Impactos",styles["h1"]),_table(impact_data,[30*mm,80*mm,32*mm,28*mm])]


def _change_control(snapshot, styles):
    from reportlab.lib.units import mm
    changes=snapshot["changes"].get("changes") or []
    data=[[_p("Código",styles["table_bold"]),_p("Status",styles["table_bold"]),_p("Mudança",styles["table_bold"]),_p("Justificativa",styles["table_bold"]),_p("Custo",styles["table_bold"]),_p("Prazo",styles["table_bold"])]]
    for c in changes[:100]: data.append([_p(c.get("code"),styles["table"]),_p(c.get("status"),styles["table"]),_p(c.get("title"),styles["table"]),_p(c.get("reason"),styles["table"]),_p(f"R$ {_brl(c.get('cost_delta'))}",styles["table"]),_p(f"{_int(c.get('schedule_delta'))} d",styles["table"])])
    if len(data)==1: data.append([_p("-",styles["table"])]*6)
    summary=snapshot["changes"]["summary"]
    conclusion=f"Foram registrados {_int(summary.get('total'))} item(ns) de mudança, dos quais {_int(summary.get('open'))} permanecem abertos. A variação acumulada é de R$ {_brl(summary.get('costDelta'))} e {_int(summary.get('scheduleDelta'))} dias."
    return [_p("1. Resumo do controle de mudanças",styles["h1"]),*_summary(snapshot,styles),_p(conclusion,styles["conclusion"]),_p("2. Registro de mudanças",styles["h1"]),_table(data,[18*mm,22*mm,40*mm,50*mm,24*mm,16*mm])]


def render_professional_pdf(snapshot: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer

    meta=snapshot["report"]
    styles=_styles()
    stream=io.BytesIO()
    doc=SimpleDocTemplate(stream,pagesize=A4,leftMargin=15*mm,rightMargin=15*mm,topMargin=19*mm,bottomMargin=17*mm,title=meta["title"],author="VAELITH LABS",subject=TEMPLATES[meta["template"]]["name"])
    story=[]
    story.extend(_cover(snapshot,styles,meta))
    template=meta["template"]
    if template=="executive": story.extend(_executive(snapshot,styles))
    elif template=="coordination": story.extend(_coordination(snapshot,styles))
    elif template=="operational": story.extend(_operational(snapshot,styles))
    else: story.extend(_change_control(snapshot,styles))

    if meta.get("notes"):
        story += [Spacer(1,5*mm),_p("Observações da emissão",styles["h1"]),_p(meta["notes"],styles["body"])]
    story += [Spacer(1,6*mm),_p("Conclusão e responsabilidade técnica",styles["h1"]),_p("Este relatório consolida os registros disponíveis na VAELITH Platform na data de emissão. As conclusões e indicadores devem ser validados pela equipe técnica responsável pelo empreendimento antes de qualquer decisão de projeto, contratação ou execução.",styles["conclusion"])]

    if meta.get("includeAppendices"):
        decisions=snapshot.get("decisions") or []
        if decisions:
            story.append(PageBreak());story.append(_p("Anexo A - Decisões registradas",styles["h1"]))
            data=[[_p("Ocorrência",styles["table_bold"]),_p("Decisão",styles["table_bold"]),_p("Responsável",styles["table_bold"]),_p("Data",styles["table_bold"])]]
            for d in decisions[:100]: data.append([_p(d.get("code"),styles["table"]),_p(d.get("decision") or d.get("description") or d.get("text"),styles["table"]),_p(d.get("decided_by") or d.get("created_by") or "-",styles["table"]),_p(_fmt_date(d.get("created")),styles["table"])])
            story.append(_table(data,[25*mm,85*mm,35*mm,25*mm]))
    doc.build(story,onFirstPage=lambda c,d:_header_footer(c,d,meta),onLaterPages=lambda c,d:_header_footer(c,d,meta))
    return stream.getvalue()


def install(app: FastAPI) -> None:
    if getattr(app.state,"_vaelith_professional_reports",False): return
    app.state._vaelith_professional_reports=True

    @app.get("/api/reports/templates")
    def report_templates():
        return {"templates":[{"id":key,**value} for key,value in TEMPLATES.items()]}

    @app.post("/api/projects/{pid}/professional-reports")
    async def generate_professional_report(pid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        srv,user,project=_context(pid,vaelith_session)
        data=_json(await request.body())
        template=str(data.get("template") or "executive")
        if template not in TEMPLATES: raise HTTPException(400,"Modelo de relatório inválido.")
        generated=datetime.now().strftime("%Y%m%d")
        document_code=str(data.get("documentCode") or f"VAE-{TEMPLATES[template]['code']}-{generated}").strip()[:60]
        revision=str(data.get("revision") or "R00").strip().upper()[:20]
        prepared_by=str(data.get("preparedBy") or user.get("name") or "Equipe técnica").strip()[:120]
        title=str(data.get("title") or f"{TEMPLATES[template]['name']} - {project['name']}").strip()[:180]
        meta={"template":template,"documentCode":document_code,"revision":revision,"preparedBy":prepared_by,"title":title,"notes":str(data.get("notes") or "")[:4000],"includeAppendices":bool(data.get("includeAppendices",True))}
        snapshot=_build_snapshot(pid,template,meta)
        report_id=uuid4().hex
        with srv.conn() as c:
            c.execute("INSERT INTO project_reports VALUES(?,?,?,?,?,?,?)",(report_id,pid,template,title,json.dumps(snapshot,ensure_ascii=False),user["name"],_now()))
            try:
                import complete_runtime_v1 as runtime
                runtime.audit(c,pid,user["name"],"professional_report.generated","project_report",report_id,{"template":template,"documentCode":document_code,"revision":revision})
            except Exception:
                pass
        return {"id":report_id,"template":template,"title":title,"documentCode":document_code,"revision":revision,"pdfUrl":f"/api/projects/{pid}/professional-reports/{report_id}/pdf"}

    @app.get("/api/projects/{pid}/professional-reports/{report_id}/pdf", include_in_schema=False)
    def professional_report_pdf(pid: str, report_id: str, vaelith_session: str | None = Cookie(None)):
        srv,_,_=_context(pid,vaelith_session)
        with srv.conn() as c:
            row=c.execute("SELECT * FROM project_reports WHERE id=? AND project_id=?",(report_id,pid)).fetchone()
        if not row: raise HTTPException(404,"Relatório não encontrado.")
        snapshot=json.loads(row["snapshot"] or "{}")
        if not snapshot.get("report"):
            raise HTTPException(409,"Este relatório foi criado no modelo antigo. Gere uma nova emissão profissional.")
        payload=render_professional_pdf(snapshot)
        meta=snapshot["report"]
        filename=f"VAELITH_{_safe_filename(meta['documentCode'])}_{_safe_filename(meta['revision'])}.pdf"
        return Response(payload,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="{filename}"',"Cache-Control":"private, no-store"})

    @app.get("/api/projects/{pid}/professional-reports/{report_id}/preview")
    def professional_report_preview(pid: str, report_id: str, vaelith_session: str | None = Cookie(None)):
        srv,_,_=_context(pid,vaelith_session)
        with srv.conn() as c:
            row=c.execute("SELECT * FROM project_reports WHERE id=? AND project_id=?",(report_id,pid)).fetchone()
        if not row: raise HTTPException(404,"Relatório não encontrado.")
        snapshot=json.loads(row["snapshot"] or "{}")
        meta=snapshot.get("report") or {}
        return {"id":report_id,"title":row["title"],"type":row["report_type"],"created":row["created"],"createdBy":row["created_by"],"documentCode":meta.get("documentCode"),"revision":meta.get("revision"),"template":meta.get("template"),"templateName":meta.get("templateName"),"pdfUrl":f"/api/projects/{pid}/professional-reports/{report_id}/pdf"}
