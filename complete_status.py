from __future__ import annotations

from fastapi import FastAPI

REQUIRED_TABLES = (
    "document_controls",
    "planning_activities",
    "change_requests",
    "project_reports",
    "audit_events",
    "bim_jobs",
)

REQUIRED_ROUTES = (
    "/api/projects/{pid}/revisions",
    "/api/projects/{pid}/impacts",
    "/api/projects/{pid}/planning",
    "/api/projects/{pid}/changes",
    "/api/projects/{pid}/reports",
    "/api/projects/{pid}/intelligence/query",
    "/api/projects/{pid}/bim/analyze",
    "/api/projects/{pid}/audit",
)


def install(app: FastAPI) -> None:
    if getattr(app.state, "_vaelith_complete_status", False):
        return
    app.state._vaelith_complete_status = True

    @app.get("/api/platform/complete-status", include_in_schema=False)
    def complete_status():
        import server
        from complete_runtime_v1 import ensure_schema

        errors: list[str] = []
        try:
            ensure_schema()
            with server.conn() as connection:
                rows = connection.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public'"
                ).fetchall()
            existing = {row["table_name"] for row in rows}
            table_status = {name: name in existing for name in REQUIRED_TABLES}
        except Exception as exc:
            table_status = {name: False for name in REQUIRED_TABLES}
            errors.append(f"database: {type(exc).__name__}: {str(exc)[:180]}")

        route_paths = {getattr(route, "path", None) for route in app.routes}
        route_status = {path: path in route_paths for path in REQUIRED_ROUTES}

        try:
            import ifcopenshell
            import ifcopenshell.geom
            bim = {
                "available": True,
                "version": getattr(ifcopenshell, "version", None)
                or getattr(ifcopenshell, "__version__", None),
                "geometryTree": hasattr(ifcopenshell.geom, "tree"),
                "intersection": hasattr(ifcopenshell.geom.tree, "clash_intersection_many"),
                "collision": hasattr(ifcopenshell.geom.tree, "clash_collision_many"),
                "clearance": hasattr(ifcopenshell.geom.tree, "clash_clearance_many"),
            }
        except Exception as exc:
            bim = {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:180]}"}
            errors.append(f"bim: {bim['error']}")

        try:
            import reportlab
            from reportlab.pdfgen import canvas
            pdf = {
                "available": True,
                "version": getattr(reportlab, "Version", None)
                or getattr(reportlab, "__version__", None),
                "canvas": bool(canvas),
            }
        except Exception as exc:
            pdf = {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:180]}"}
            errors.append(f"pdf: {pdf['error']}")

        modules = {
            "revisionControl": table_status.get("document_controls", False),
            "impactConsolidation": route_status.get("/api/projects/{pid}/impacts", False),
            "planning": table_status.get("planning_activities", False),
            "changeControl": table_status.get("change_requests", False),
            "controlledReports": table_status.get("project_reports", False) and pdf.get("available", False),
            "auditTrail": table_status.get("audit_events", False),
            "intelligence": route_status.get("/api/projects/{pid}/intelligence/query", False),
            "bimGeometry": table_status.get("bim_jobs", False) and bim.get("available", False),
        }
        return {
            "ok": all(table_status.values())
            and all(route_status.values())
            and all(modules.values()),
            "version": "complete-v1",
            "modules": modules,
            "tables": table_status,
            "routes": route_status,
            "bim": bim,
            "pdf": pdf,
            "errors": errors,
        }
