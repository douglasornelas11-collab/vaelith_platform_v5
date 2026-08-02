from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from fastapi import Cookie, FastAPI, HTTPException, Request

MAX_TEXT_CHARS = 300_000
MAX_COMPARE_LINES = 120


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _server():
    import server
    return server


def _ensure_schema() -> None:
    srv = _server()
    with srv.conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS pdf_analyses(
              file_id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              pages INTEGER NOT NULL DEFAULT 0,
              text_content TEXT NOT NULL DEFAULT '',
              metadata TEXT NOT NULL DEFAULT '{}',
              char_count INTEGER NOT NULL DEFAULT 0,
              text_pages INTEGER NOT NULL DEFAULT 0,
              scanned_likely INTEGER NOT NULL DEFAULT 0,
              analyzed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pdf_analyses_project ON pdf_analyses(project_id, analyzed_at DESC);
            """
        )


def _context(pid: str, token: str | None):
    srv = _server()
    user = srv.require_user(token)
    project = srv.require_project(pid, user["id"])
    _ensure_schema()
    return srv, user, project


def _file_row(pid: str, fid: str):
    srv = _server()
    with srv.conn() as c:
        row = c.execute("SELECT * FROM files WHERE id=? AND project_id=?", (fid, pid)).fetchone()
    if not row:
        raise HTTPException(404, "Arquivo não encontrado.")
    item = dict(row)
    if str(item.get("ext") or "").lower() != ".pdf":
        raise HTTPException(415, "Este recurso processa apenas arquivos PDF.")
    return item


def _pdf_bytes(file_row: dict) -> bytes:
    storage_path = str(file_row.get("storage_path") or "")
    if not storage_path.startswith("supabase://"):
        raise HTTPException(409, "O PDF precisa estar persistido no Supabase para ser analisado.")
    parts = storage_path.split("/", 3)
    if len(parts) < 4:
        raise HTTPException(409, "Referência de armazenamento inválida.")
    object_path = parts[3]
    import supabase_runtime
    return supabase_runtime._object_bytes(object_path)


def _clean_text(value: str) -> str:
    value = value.replace("\x00", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def analyze_pdf(pid: str, fid: str) -> dict:
    file_row = _file_row(pid, fid)
    raw = _pdf_bytes(file_row)
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw), strict=False)
    except Exception as exc:
        raise HTTPException(422, f"Não foi possível abrir o PDF: {type(exc).__name__}: {str(exc)[:160]}") from exc

    chunks: list[str] = []
    chars = 0
    text_pages = 0
    for index, page in enumerate(reader.pages):
        if chars >= MAX_TEXT_CHARS:
            break
        try:
            text = _clean_text(page.extract_text() or "")
        except Exception:
            text = ""
        if text:
            text_pages += 1
            chunk = f"\n--- PÁGINA {index + 1} ---\n{text}"
            chunks.append(chunk)
            chars += len(chunk)
    text_content = "".join(chunks)[:MAX_TEXT_CHARS]
    metadata = {}
    try:
        source = reader.metadata or {}
        for key, value in source.items():
            if value is not None:
                metadata[str(key).lstrip("/")] = str(value)[:1000]
    except Exception:
        metadata = {}
    pages = len(reader.pages)
    scanned_likely = pages > 0 and text_pages == 0
    analyzed_at = now()

    srv = _server()
    with srv.conn() as c:
        c.execute(
            """
            INSERT INTO pdf_analyses(file_id,project_id,pages,text_content,metadata,char_count,text_pages,scanned_likely,analyzed_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(file_id) DO UPDATE SET
              pages=excluded.pages,text_content=excluded.text_content,metadata=excluded.metadata,
              char_count=excluded.char_count,text_pages=excluded.text_pages,
              scanned_likely=excluded.scanned_likely,analyzed_at=excluded.analyzed_at
            """,
            (fid, pid, pages, text_content, json.dumps(metadata, ensure_ascii=False), len(text_content), text_pages, int(scanned_likely), analyzed_at),
        )
        try:
            c.execute(
                "INSERT INTO audit_events(id,project_id,actor,action,entity_type,entity_id,detail,created) VALUES(md5(random()::text || clock_timestamp()::text),?,?,?,?,?,?,?)",
                (pid, "VAELITH PDF Engine", "pdf.analyzed", "file", fid, json.dumps({"pages": pages, "characters": len(text_content), "scannedLikely": scanned_likely}, ensure_ascii=False), analyzed_at),
            )
        except Exception:
            pass
    return {
        "fileId": fid,
        "name": file_row.get("name"),
        "pages": pages,
        "textPages": text_pages,
        "characters": len(text_content),
        "scannedLikely": scanned_likely,
        "metadata": metadata,
        "revision": file_row.get("revision"),
        "discipline": file_row.get("discipline"),
        "preview": text_content[:3500],
        "analyzedAt": analyzed_at,
    }


def _analysis_row(pid: str, fid: str, *, auto: bool = False) -> dict | None:
    _ensure_schema()
    srv = _server()
    with srv.conn() as c:
        row = c.execute("SELECT * FROM pdf_analyses WHERE file_id=? AND project_id=?", (fid, pid)).fetchone()
    if not row and auto:
        analyze_pdf(pid, fid)
        with srv.conn() as c:
            row = c.execute("SELECT * FROM pdf_analyses WHERE file_id=? AND project_id=?", (fid, pid)).fetchone()
    return dict(row) if row else None


def _public_analysis(file_row: dict, analysis: dict | None) -> dict:
    return {
        "id": file_row["id"],
        "name": file_row.get("name"),
        "revision": file_row.get("revision"),
        "discipline": file_row.get("discipline"),
        "disciplineCode": file_row.get("discipline_code"),
        "analyzed": bool(analysis),
        "pages": int((analysis or {}).get("pages") or 0),
        "characters": int((analysis or {}).get("char_count") or 0),
        "textPages": int((analysis or {}).get("text_pages") or 0),
        "scannedLikely": bool((analysis or {}).get("scanned_likely")),
        "analyzedAt": (analysis or {}).get("analyzed_at"),
    }


def _search(pid: str, query: str, limit: int = 8) -> list[dict]:
    query = query.strip()
    if len(query) < 2:
        return []
    srv = _server()
    with srv.conn() as c:
        rows = c.execute(
            """SELECT a.*,f.name,f.revision,f.discipline FROM pdf_analyses a
               JOIN files f ON f.id=a.file_id WHERE a.project_id=? ORDER BY a.analyzed_at DESC""",
            (pid,),
        ).fetchall()
    terms = [t for t in re.findall(r"[A-Za-zÀ-ÿ0-9_.-]{2,}", query.lower()) if len(t) > 2]
    results = []
    for raw in rows:
        row = dict(raw)
        text = row.get("text_content") or ""
        low = text.lower()
        positions = [low.find(term) for term in terms if low.find(term) >= 0]
        if not positions:
            continue
        pos = min(positions)
        start = max(0, pos - 250)
        end = min(len(text), pos + 700)
        excerpt = text[start:end].replace("\n", " ").strip()
        score = sum(low.count(term) for term in terms)
        results.append({"fileId": row["file_id"], "name": row["name"], "revision": row.get("revision"), "discipline": row.get("discipline"), "score": score, "excerpt": excerpt})
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def install(app: FastAPI) -> None:
    if getattr(app.state, "_vaelith_pdf_runtime", False):
        return
    app.state._vaelith_pdf_runtime = True
    _ensure_schema()

    @app.get("/api/projects/{pid}/pdf")
    def pdf_status(pid: str, vaelith_session: str | None = Cookie(None)):
        srv, _, _ = _context(pid, vaelith_session)
        with srv.conn() as c:
            files = [dict(r) for r in c.execute("SELECT * FROM files WHERE project_id=? AND lower(ext)='.pdf' ORDER BY uploaded DESC", (pid,)).fetchall()]
            analyses = {r["file_id"]: dict(r) for r in c.execute("SELECT * FROM pdf_analyses WHERE project_id=?", (pid,)).fetchall()}
        items = [_public_analysis(item, analyses.get(item["id"])) for item in files]
        return {"projectId": pid, "pdfs": items, "total": len(items), "analyzed": sum(i["analyzed"] for i in items), "scannedLikely": sum(i["scannedLikely"] for i in items)}

    @app.post("/api/projects/{pid}/pdf/{fid}/analyze")
    def pdf_analyze(pid: str, fid: str, vaelith_session: str | None = Cookie(None)):
        _context(pid, vaelith_session)
        return analyze_pdf(pid, fid)

    @app.get("/api/projects/{pid}/pdf/{fid}")
    def pdf_detail(pid: str, fid: str, vaelith_session: str | None = Cookie(None)):
        _context(pid, vaelith_session)
        file_row = _file_row(pid, fid)
        analysis = _analysis_row(pid, fid, auto=True)
        metadata = json.loads((analysis or {}).get("metadata") or "{}")
        return {**_public_analysis(file_row, analysis), "metadata": metadata, "text": (analysis or {}).get("text_content") or ""}

    @app.post("/api/projects/{pid}/pdf/search")
    async def pdf_search(pid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        _context(pid, vaelith_session)
        try:
            body = json.loads((await request.body()) or b"{}")
        except Exception as exc:
            raise HTTPException(400, "JSON inválido.") from exc
        query = str(body.get("query") or "").strip()
        return {"query": query, "results": _search(pid, query)}

    @app.post("/api/projects/{pid}/pdf/compare")
    async def pdf_compare(pid: str, request: Request, vaelith_session: str | None = Cookie(None)):
        _context(pid, vaelith_session)
        try:
            body = json.loads((await request.body()) or b"{}")
        except Exception as exc:
            raise HTTPException(400, "JSON inválido.") from exc
        file_a = str(body.get("fileA") or "")
        file_b = str(body.get("fileB") or "")
        if not file_a or not file_b or file_a == file_b:
            raise HTTPException(400, "Informe dois PDFs diferentes para comparar.")
        row_a = _analysis_row(pid, file_a, auto=True)
        row_b = _analysis_row(pid, file_b, auto=True)
        text_a = (row_a or {}).get("text_content") or ""
        text_b = (row_b or {}).get("text_content") or ""
        if not text_a and not text_b:
            raise HTTPException(422, "Os dois PDFs não possuem texto extraível. Para PDFs escaneados será necessário OCR em uma etapa própria.")
        lines_a = [x.strip() for x in text_a.splitlines() if len(x.strip()) > 2 and not x.startswith("--- PÁGINA")]
        lines_b = [x.strip() for x in text_b.splitlines() if len(x.strip()) > 2 and not x.startswith("--- PÁGINA")]
        set_a, set_b = set(lines_a), set(lines_b)
        all_added = [x for x in lines_b if x not in set_a]
        all_removed = [x for x in lines_a if x not in set_b]
        similarity = round(SequenceMatcher(None, text_a[:100_000], text_b[:100_000]).ratio() * 100, 1)
        return {"fileA": file_a, "fileB": file_b, "similarity": similarity, "added": all_added[:MAX_COMPARE_LINES], "removed": all_removed[:MAX_COMPARE_LINES], "addedCount": len(all_added), "removedCount": len(all_removed)}

    # Extend VAELITH Intelligence with excerpts from PDFs already analyzed.
    try:
        import complete_runtime_v1 as runtime
        original = runtime.intelligence_answer
        def intelligence_with_pdf(pid: str, question: str):
            base = original(pid, question)
            matches = _search(pid, question, 4)
            if not matches:
                return base
            sources = list(base.get("sources") or [])
            for match in matches:
                sources.append({"module": "PDF", "label": f"{match['name']} · {match.get('revision') or 'sem revisão'}"})
            base["sources"] = sources
            base["documentEvidence"] = matches
            base["answer"] = (base.get("answer") or "") + " Há também evidências documentais em PDF relacionadas à pergunta; consulte os trechos indicados nas fontes."
            return base
        runtime.intelligence_answer = intelligence_with_pdf
    except Exception:
        pass
