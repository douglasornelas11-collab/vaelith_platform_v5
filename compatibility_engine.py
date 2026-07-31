from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


def _guarantee_platform_runtimes() -> None:
    """Install visual, operational and diagnostic routes before server startup."""
    try:
        from fastapi import FastAPI

        if getattr(FastAPI, "_vaelith_platform_runtime_patch", False):
            return

        original_init = FastAPI.__init__

        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            paths = {getattr(route, "path", None) for route in getattr(self, "routes", [])}
            if "/platform-v3.css" not in paths:
                try:
                    from static_runtime import install as install_static
                    install_static(self)
                except Exception as exc:
                    print(f"VAELITH_STATIC_DIRECT_INSTALL_ERROR: {exc}")
            paths = {getattr(route, "path", None) for route in getattr(self, "routes", [])}
            if "/api/projects/{pid}/operational/dashboard" not in paths:
                try:
                    from unified_runtime_v2 import install as install_unified
                    install_unified(self)
                except Exception as exc:
                    print(f"VAELITH_UNIFIED_DIRECT_INSTALL_ERROR: {exc}")
            paths = {getattr(route, "path", None) for route in getattr(self, "routes", [])}
            if "/api/platform/self-test" not in paths:
                @self.get("/api/platform/self-test", include_in_schema=False)
                def platform_self_test():
                    checks: dict[str, Any] = {}
                    errors: list[str] = []
                    route_paths = {getattr(route, "path", None) for route in getattr(self, "routes", [])}
                    required_routes = [
                        "/platform-v3.css",
                        "/unified-ui.js",
                        "/api/projects/{pid}/operational/dashboard",
                        "/api/projects/{pid}/operational/issues",
                        "/api/projects/{pid}/compatibility",
                        "/api/projects/{pid}/budget/equalization",
                    ]
                    checks["routes"] = all(path in route_paths for path in required_routes)
                    checks["routeDetails"] = {path: path in route_paths for path in required_routes}
                    try:
                        import server
                        with server.conn() as connection:
                            connection.execute("CREATE TEMP TABLE IF NOT EXISTS vaelith_self_test(id TEXT)")
                            connection.execute("DELETE FROM vaelith_self_test")
                            connection.execute("INSERT INTO vaelith_self_test(id) VALUES(?)", ("ok",))
                            row = connection.execute("SELECT COUNT(*) FROM vaelith_self_test").fetchone()
                            checks["database"] = bool(row and int(row[0]) == 1)
                    except Exception as exc:
                        checks["database"] = False
                        errors.append(f"database: {type(exc).__name__}: {str(exc)[:160]}")
                    try:
                        from unified_runtime_v2 import ensure_schema
                        ensure_schema()
                        checks["operationalSchema"] = True
                    except Exception as exc:
                        checks["operationalSchema"] = False
                        errors.append(f"operationalSchema: {type(exc).__name__}: {str(exc)[:160]}")
                    try:
                        sample = [
                            {"name": "ARQ_R01.ifc", "ext": ".ifc", "discipline_code": "ARQ", "revision": "R01"},
                            {"name": "EST_R01.ifc", "ext": ".ifc", "discipline_code": "EST", "revision": "R01"},
                            {"name": "HID_R01.ifc", "ext": ".ifc", "discipline_code": "HID", "revision": "R01"},
                            {"name": "ELE_R01.dwg", "ext": ".dwg", "discipline_code": "ELE", "revision": "R01"},
                        ]
                        result = build_analysis("self-test", sample)
                        checks["compatibilityEngine"] = bool(result.get("files") == 4 and result.get("interfacePackages"))
                        checks["compatibilitySummary"] = {
                            "files": result.get("files"),
                            "disciplines": len(result.get("disciplines") or []),
                            "interfaces": len(result.get("interfacePackages") or []),
                            "readiness": result.get("readiness"),
                        }
                    except Exception as exc:
                        checks["compatibilityEngine"] = False
                        errors.append(f"compatibilityEngine: {type(exc).__name__}: {str(exc)[:160]}")
                    try:
                        from supabase_runtime import configured
                        checks["persistentStorage"] = bool(configured())
                    except Exception as exc:
                        checks["persistentStorage"] = False
                        errors.append(f"persistentStorage: {type(exc).__name__}: {str(exc)[:160]}")
                    database_provider = "postgresql" if any(
                        os.getenv(name, "").startswith(("postgres://", "postgresql://"))
                        for name in ("VAELITH_DB_URL", "STORAGE_URL", "DATABASE_URL", "POSTGRES_URL", "NEON_DATABASE_URL")
                    ) else "sqlite-temporary"
                    essential = ["routes", "database", "operationalSchema", "compatibilityEngine"]
                    return {
                        "ok": all(bool(checks.get(name)) for name in essential),
                        "checks": checks,
                        "databaseProvider": database_provider,
                        "environment": "vercel" if os.getenv("VERCEL") else "local",
                        "errors": errors,
                    }

        FastAPI.__init__ = patched_init
        FastAPI._vaelith_platform_runtime_patch = True
    except Exception as exc:
        print(f"VAELITH_PLATFORM_DIRECT_PATCH_ERROR: {exc}")


_guarantee_platform_runtimes()


DISCIPLINES: dict[str, dict[str, Any]] = {
    "ARQ": {"name": "Arquitetura", "tokens": {"ARQ", "ARQUITETURA", "ARCH"}, "core": True},
    "EST": {"name": "Estrutura", "tokens": {"EST", "ESTRUTURA", "STR", "STRUCT"}, "core": True},
    "HID": {"name": "Hidráulica", "tokens": {"HID", "HIDRAULICA", "AGUA", "PLUMBING"}, "core": True},
    "SAN": {"name": "Sanitária", "tokens": {"SAN", "SANITARIA", "ESGOTO", "SEWER"}, "core": False},
    "ELE": {"name": "Elétrica", "tokens": {"ELE", "ELETRICA", "ELT", "ELECTRICAL"}, "core": True},
    "HVAC": {"name": "Climatização", "tokens": {"HVAC", "AVAC", "CLIMA", "CLIMATIZACAO", "MEC"}, "core": False},
    "PCI": {"name": "Incêndio", "tokens": {"PCI", "INCENDIO", "FIRE", "SPK"}, "core": False},
    "AUT": {"name": "Automação", "tokens": {"AUT", "AUTOMACAO", "BMS", "CONTROLE"}, "core": False},
    "ORC": {"name": "Orçamento", "tokens": {"ORC", "ORCAMENTO", "BUDGET", "CUSTO"}, "core": False},
    "PLA": {"name": "Planejamento", "tokens": {"PLA", "PLANEJAMENTO", "CRONO", "CRONOGRAMA", "SCHEDULE"}, "core": False},
    "ESC": {"name": "Escopo e memoriais", "tokens": {"ESC", "ESCOPO", "MEMORIAL", "SPEC", "ESPECIFICACAO"}, "core": False},
}

PAIR_RULES = [
    ("ARQ", "EST", "Alta", "Arquitetura × Estrutura", ["eixos e modulação", "vãos e aberturas", "níveis e pé-direito", "shafts e reservas"]),
    ("ARQ", "HID", "Alta", "Arquitetura × Hidráulica", ["áreas molhadas", "shafts", "pontos e equipamentos", "caimentos e cotas"]),
    ("ARQ", "SAN", "Alta", "Arquitetura × Sanitária", ["prumadas", "caixas e inspeções", "ventilação", "interferências em ambientes"]),
    ("ARQ", "ELE", "Média", "Arquitetura × Elétrica", ["pontos e mobiliário", "forros", "quadros", "acessibilidade e alturas"]),
    ("ARQ", "HVAC", "Alta", "Arquitetura × Climatização", ["forro e dutos", "grelhas", "casas de máquinas", "acessos de manutenção"]),
    ("ARQ", "PCI", "Alta", "Arquitetura × Incêndio", ["rotas de fuga", "hidrantes e extintores", "sprinklers", "compartimentação"]),
    ("EST", "HID", "Crítica", "Estrutura × Hidráulica", ["travessias em vigas", "furos em lajes", "reservas", "cargas de equipamentos"]),
    ("EST", "SAN", "Crítica", "Estrutura × Sanitária", ["prumadas em vigas", "furos e sleeves", "caimentos", "reservas estruturais"]),
    ("EST", "ELE", "Alta", "Estrutura × Elétrica", ["eletrocalhas", "shafts", "furos e chumbadores", "salas técnicas"]),
    ("EST", "HVAC", "Crítica", "Estrutura × Climatização", ["dutos em vigas", "bases de equipamentos", "aberturas", "vibração e cargas"]),
    ("EST", "PCI", "Alta", "Estrutura × Incêndio", ["tubulações", "reservas", "suportes", "proteção passiva"]),
    ("HID", "ELE", "Alta", "Hidráulica × Elétrica", ["distâncias de segurança", "salas técnicas", "rotas concorrentes", "equipamentos alimentados"]),
    ("HID", "HVAC", "Média", "Hidráulica × Climatização", ["drenos", "condensação", "rotas em forro", "casas de máquinas"]),
    ("ELE", "HVAC", "Alta", "Elétrica × Climatização", ["alimentação", "automação", "quadros", "acessos de manutenção"]),
    ("ELE", "PCI", "Alta", "Elétrica × Incêndio", ["detecção e alarme", "alimentação de emergência", "rotas", "selagens corta-fogo"]),
    ("HVAC", "PCI", "Alta", "Climatização × Incêndio", ["dampers", "pressurização", "controle de fumaça", "selagens"]),
]

REV_RE = re.compile(r"(?:^|[_\-\s])(R(?:EV)?\s*0*\d{1,3}|V\s*0*\d{1,3}|P\s*0*\d{1,3})(?=$|[_\-\s.])", re.I)


def _ascii(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).upper()


def _tokens(filename: str) -> set[str]:
    return {t for t in re.split(r"[^A-Z0-9]+", _ascii(Path(filename).stem)) if t}


def infer_discipline(filename: str) -> tuple[str, str]:
    tokens = _tokens(filename)
    for code, cfg in DISCIPLINES.items():
        if tokens & cfg["tokens"]:
            return code, cfg["name"]
    if Path(filename).suffix.lower() == ".mpp":
        return "PLA", DISCIPLINES["PLA"]["name"]
    return "UNK", "Não identificada"


def infer_revision(filename: str) -> str:
    match = REV_RE.search(_ascii(filename))
    if not match:
        return "Não informada"
    raw = re.sub(r"\s+", "", match.group(1).upper()).replace("REV", "R")
    prefix = raw[0]
    digits = re.sub(r"\D", "", raw)
    return f"{prefix}{int(digits):02d}" if digits else "Não informada"


def file_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _issue_id(project_id: str, code: str, evidence: list[str]) -> str:
    seed = project_id + code + "|".join(sorted(evidence))
    return hashlib.sha1(seed.encode()).hexdigest()[:12]


def build_analysis(project_id: str, files: list[dict[str, Any]]) -> dict[str, Any]:
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in files:
        code = item.get("discipline_code") or infer_discipline(item.get("name", ""))[0]
        item["discipline_code"] = code
        by_code[code].append(item)
    identified = [f for f in files if f["discipline_code"] != "UNK"]
    present = sorted(code for code in by_code if code != "UNK")
    core = [code for code, cfg in DISCIPLINES.items() if cfg["core"]]
    missing_core = [code for code in core if code not in present]
    issues: list[dict[str, Any]] = []

    def add(code: str, severity: str, category: str, title: str, description: str, evidence: list[str], action: str):
        issues.append({"id": _issue_id(project_id, code, evidence), "code": code, "severity": severity, "category": category, "title": title, "description": description, "evidence": evidence, "recommendedAction": action, "status": "Aberta"})

    unknown = [f["name"] for f in by_code.get("UNK", [])]
    if unknown:
        add("DOC-UNK", "Média", "Base documental", "Arquivos sem disciplina identificada", "A disciplina não pôde ser inferida pelo nome do arquivo.", unknown, "Classificar manualmente os arquivos antes de liberar a rodada.")
    if missing_core:
        names = [DISCIPLINES[c]["name"] for c in missing_core]
        add("DOC-CORE", "Alta", "Base documental", "Disciplinas essenciais ausentes", "A compatibilização integrada não pode ser concluída sem a base mínima.", names, "Solicitar e incluir as disciplinas essenciais pendentes.")

    for code, group in by_code.items():
        if code == "UNK":
            continue
        revisions = sorted({f.get("revision") or infer_revision(f["name"]) for f in group if (f.get("revision") or infer_revision(f["name"])) != "Não informada"})
        missing_rev = [f["name"] for f in group if (f.get("revision") or infer_revision(f["name"])) == "Não informada"]
        if len(revisions) > 1:
            add(f"REV-{code}", "Alta", "Revisões", f"Mais de uma revisão ativa em {DISCIPLINES[code]['name']}", f"Foram encontradas as revisões {', '.join(revisions)} para a mesma disciplina.", [f["name"] for f in group], "Definir uma única revisão-base e arquivar as versões superadas.")
        if missing_rev:
            add(f"REV-MISS-{code}", "Média", "Revisões", f"Revisão não informada em {DISCIPLINES[code]['name']}", "Há arquivos sem identificação de revisão.", missing_rev, "Renomear ou classificar a revisão antes da rodada definitiva.")

    checksums: dict[str, list[str]] = defaultdict(list)
    for f in files:
        if f.get("checksum"):
            checksums[f["checksum"]].append(f["name"])
    for i, names in enumerate([n for n in checksums.values() if len(n) > 1], 1):
        add(f"DUP-{i:02d}", "Baixa", "Base documental", "Conteúdo duplicado na base", "Arquivos diferentes possuem o mesmo conteúdo.", names, "Manter apenas o arquivo válido para evitar análise repetida.")

    interface_packages: list[dict[str, Any]] = []
    matrix: dict[str, dict[str, str]] = {c: {} for c in present}
    for a, b, severity, title, checks in PAIR_RULES:
        if a not in present or b not in present:
            continue
        evidence = [f["name"] for f in by_code[a][:3]] + [f["name"] for f in by_code[b][:3]]
        pkg_code = f"IFC-{a}-{b}"
        interface_packages.append({"code": pkg_code, "disciplines": [a, b], "title": title, "severity": severity, "checks": checks, "evidence": evidence, "status": "Pronta para conferência"})
        matrix.setdefault(a, {})[b] = severity
        matrix.setdefault(b, {})[a] = severity
        add(pkg_code, severity, "Interface técnica", f"Conferir {title}", "As duas disciplinas estão presentes e devem ser analisadas em conjunto nos pontos de interface definidos.", evidence, "Executar os itens do pacote de interface e registrar cada conflito confirmado.")

    support_checks = []
    for code, label, consequence in [("ESC", "Escopo e memoriais", "responsabilidades e critérios de aceite"), ("ORC", "Orçamento", "impacto financeiro e itens não previstos"), ("PLA", "Planejamento", "sequência executiva e impacto de prazo")]:
        if code in present:
            support_checks.append({"code": code, "name": label, "status": "Disponível", "purpose": consequence})
        else:
            support_checks.append({"code": code, "name": label, "status": "Ausente", "purpose": consequence})
            add(f"SUP-{code}", "Média", "Análise integrada", f"{label} não localizado", f"A rodada fica sem leitura de {consequence}.", [], f"Adicionar {label.lower()} à base do empreendimento.")

    blockers = [i for i in issues if i["severity"] in {"Crítica", "Alta"} and i["category"] in {"Base documental", "Revisões"}]
    completeness = round(100 * (len(present) / max(len(DISCIPLINES), 1)))
    identification = round(100 * (len(identified) / max(len(files), 1))) if files else 0
    revision_quality = 100 - min(100, 25 * sum(1 for i in issues if i["category"] == "Revisões"))
    readiness = round(completeness * .35 + identification * .25 + revision_quality * .25 + (100 if not missing_core else 25) * .15)
    gate = "Bloqueada" if blockers else ("Pronta para conferência integrada" if files else "Aguardando arquivos")
    severity_order = {"Crítica": 0, "Alta": 1, "Média": 2, "Baixa": 3}
    issues.sort(key=lambda x: (severity_order.get(x["severity"], 9), x["code"]))
    return {
        "analysisMode": "COORDENACAO_DOCUMENTAL_E_INTERFACES_V1", "projectId": project_id, "gate": gate, "readiness": readiness,
        "files": len(files), "identifiedFiles": len(identified),
        "disciplines": [{"code": c, "name": DISCIPLINES[c]["name"], "files": len(by_code[c])} for c in present],
        "missingCore": [{"code": c, "name": DISCIPLINES[c]["name"]} for c in missing_core], "supportChecks": support_checks,
        "matrix": matrix, "interfacePackages": interface_packages, "issues": issues,
        "summary": {"critical": sum(i["severity"] == "Crítica" for i in issues), "high": sum(i["severity"] == "Alta" for i in issues), "medium": sum(i["severity"] == "Média" for i in issues), "low": sum(i["severity"] == "Baixa" for i in issues)},
        "stages": [
            {"id": "inventory", "name": "Inventário", "status": "Concluída" if files else "Pendente"},
            {"id": "revision", "name": "Revisões", "status": "Bloqueada" if any(i["category"] == "Revisões" and i["severity"] == "Alta" for i in issues) else "Concluída"},
            {"id": "coverage", "name": "Cobertura", "status": "Bloqueada" if missing_core else "Concluída"},
            {"id": "interfaces", "name": "Interfaces", "status": "Pronta" if interface_packages else "Pendente"},
            {"id": "release", "name": "Liberação", "status": "Bloqueada" if blockers else "A validar"},
        ],
        "geometricEngine": {"eligibleIfcFiles": [f["name"] for f in files if str(f.get("ext", "")).lower() == ".ifc"], "status": "Preparada para etapa geométrica" if sum(str(f.get("ext", "")).lower() == ".ifc" for f in files) >= 2 else "Aguardando pelo menos dois modelos IFC", "next": "Federar modelos IFC, normalizar coordenadas e executar detecção geométrica por classes e tolerâncias."},
    }