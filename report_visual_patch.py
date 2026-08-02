from __future__ import annotations


def install() -> None:
    import professional_report_runtime as reports

    def branded_header_footer(canvas, doc, meta: dict):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        width, height = A4
        page = canvas.getPageNumber()
        if page == 1:
            reports._draw_vaelith_symbol(canvas, 15*mm, height-26*mm, 12*mm, colors.HexColor("#C8FF3D"))
        else:
            canvas.saveState()
            reports._draw_vaelith_symbol(canvas, 15*mm, height-15*mm, 8*mm, colors.HexColor("#111511"))
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

    reports._header_footer = branded_header_footer
