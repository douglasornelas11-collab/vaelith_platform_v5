from __future__ import annotations

import io
import json
from html import escape
from uuid import uuid4


PATCH_VERSION = "complete-v1-audit-pdf-20260731"


def install() -> None:
    """Apply production-safe corrections to Complete Runtime V1."""
    import complete_runtime_v1 as runtime

    def corrected_audit(c, pid, actor, action, entity_type, entity_id, detail=None):
        c.execute(
            "INSERT INTO audit_events(id,project_id,actor,action,entity_type,entity_id,detail,created) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                pid,
                actor,
                action,
                entity_type,
                entity_id,
                json.dumps(detail or {}, ensure_ascii=False),
                runtime.now(),
            ),
        )

    def corrected_render_report_pdf(snapshot: dict, title: str) -> bytes:
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except ImportError as exc:
            from fastapi import HTTPException
            raise HTTPException(503, "Gerador PDF indisponível no ambiente.") from exc

        stream = io.BytesIO()
        doc = SimpleDocTemplate(
            stream,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
            title=title,
            author="VAELITH LABS",
        )
        styles = getSampleStyleSheet()
        label_style = ParagraphStyle(
            "VaelithLabel",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#607066"),
            spaceAfter=5,
        )
        cell_style = ParagraphStyle(
            "VaelithCell",
            parent=styles["BodyText"],
            fontSize=7.5,
            leading=9,
        )
        story = [
            Paragraph("VAELITH PLATFORM · RELATÓRIO CONTROLADO", label_style),
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
        summary_table = Table(summary, colWidths=[55 * mm, 115 * mm])
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef5e5")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ccd4ca")),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story += [summary_table, Spacer(1, 12), Paragraph("Ocorrências", styles["Heading2"])]
        issue_data = [["Código", "Título", "Criticidade", "Status"]]
        for item in snapshot.get("issues", [])[:100]:
            issue_data.append(
                [
                    Paragraph(escape(str(item.get("code") or "")), cell_style),
                    Paragraph(escape(str(item.get("title") or "")[:140]), cell_style),
                    Paragraph(escape(str(item.get("severity") or "")), cell_style),
                    Paragraph(escape(str(item.get("status") or "")), cell_style),
                ]
            )
        issue_table = Table(issue_data, repeatRows=1, colWidths=[28 * mm, 85 * mm, 28 * mm, 30 * mm])
        issue_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172018")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ccd4ca")),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(issue_table)
        doc.build(story)
        return stream.getvalue()

    runtime.audit = corrected_audit
    runtime.render_report_pdf = corrected_render_report_pdf
