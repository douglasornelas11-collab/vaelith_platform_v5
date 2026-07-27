from __future__ import annotations

import json
import mimetypes
from uuid import uuid4


def seed_realistic_demo() -> None:
    """Create a repeatable, realistic but fictional engineering demo dataset."""
    from compatibility_engine import DISCIPLINES, build_analysis, infer_revision
    from server import conn, now

    demo_email = "demo@vaelithlabs.com.br"
    with conn() as c:
        user = c.execute("SELECT * FROM users WHERE email=?", (demo_email,)).fetchone()
        if not user:
            return
        uid = user["id"]
        project = c.execute(
            "SELECT * FROM projects WHERE user_id=? AND name=?",
            (uid, "Centro Empresarial Horizonte — Reforma e Modernização"),
        ).fetchone()
        if project:
            pid = project["id"]
            existing = c.execute("SELECT COUNT(*) FROM budget_items WHERE project_id=?", (pid,)).fetchone()[0]
            existing_analysis = c.execute("SELECT COUNT(*) FROM analyses WHERE project_id=?", (pid,)).fetchone()[0]
            if existing >= 10 and existing_analysis:
                return
            c.execute("DELETE FROM files WHERE project_id=?", (pid,))
            c.execute("DELETE FROM budget_items WHERE project_id=?", (pid,))
            c.execute("DELETE FROM analyses WHERE project_id=?", (pid,))
        else:
            pid = uuid4().hex
            c.execute(
                "INSERT INTO projects VALUES(?,?,?,?,?,?,?)",
                (
                    pid,
                    uid,
                    "Centro Empresarial Horizonte — Reforma e Modernização",
                    "Construtora Horizonte S.A.",
                    "Betim/MG",
                    "Execução — 38% concluída",
                    now(),
                ),
            )

        files = [
            ("ARQ_EXECUTIVO_TORRE_A_R04.ifc", "ARQ", 48_600_000),
            ("ARQ_EXECUTIVO_TORRE_A_R05.ifc", "ARQ", 52_300_000),
            ("EST_FORMAS_E_ARMACAO_R03.ifc", "EST", 37_800_000),
            ("HID_AGUA_FRIA_QUENTE_R02.ifc", "HID", 18_400_000),
            ("SAN_ESGOTO_E_VENTILACAO_R02.ifc", "SAN", 16_900_000),
            ("ELE_FORCA_ILUMINACAO_R04.dwg", "ELE", 21_700_000),
            ("HVAC_DUTOS_E_EQUIPAMENTOS_R03.ifc", "HVAC", 44_200_000),
            ("PCI_SPRINKLERS_HIDRANTES_R02.dwg", "PCI", 15_600_000),
            ("ORCAMENTO_EXECUTIVO_R05.xlsx", "ORC", 1_840_000),
            ("CRONOGRAMA_INTEGRADO_R04.mpp", "PLA", 3_200_000),
            ("MEMORIAL_DESCRITIVO_R03.pdf", "ESC", 6_800_000),
            ("LEVANTAMENTO_CAMPO_12-07-2026.pdf", "ESC", 9_400_000),
        ]
        for filename, code, size in files:
            ext = "." + filename.rsplit(".", 1)[-1].lower()
            c.execute(
                "INSERT INTO files(id,project_id,name,ext,size,discipline,revision,uploaded,discipline_code,checksum,storage_path,mime) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uuid4().hex,
                    pid,
                    filename,
                    ext,
                    size,
                    DISCIPLINES[code]["name"],
                    infer_revision(filename),
                    now(),
                    code,
                    "demo-" + uuid4().hex,
                    "",
                    mimetypes.guess_type(filename)[0] or "application/octet-stream",
                ),
            )

        budget = [
            ("Mobilização, canteiro e administração local", "mês", 12, 128500.00, "OUT"),
            ("Demolições controladas e remoções", "m²", 3850, 96.40, "ARQ"),
            ("Reforço estrutural com fibra de carbono", "m²", 420, 1180.00, "EST"),
            ("Estrutura metálica de cobertura técnica", "kg", 28600, 19.85, "EST"),
            ("Alvenarias, drywall e fechamentos", "m²", 7120, 184.30, "ARQ"),
            ("Revestimentos, pisos e forros", "m²", 9680, 238.70, "ARQ"),
            ("Rede hidráulica de água fria e quente", "vb", 1, 684300.00, "HID"),
            ("Rede sanitária, ventilação e drenagem", "vb", 1, 512800.00, "SAN"),
            ("Instalações elétricas e iluminação", "vb", 1, 1286000.00, "ELE"),
            ("Sistema de climatização VRF e renovação de ar", "vb", 1, 1624500.00, "HVAC"),
            ("Sistema de incêndio, alarme e sinalização", "vb", 1, 738900.00, "PCI"),
            ("Automação predial e supervisão BMS", "vb", 1, 465000.00, "OUT"),
        ]
        for description, unit, qty, unit_price, category in budget:
            c.execute(
                "INSERT INTO budget_items VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    uuid4().hex,
                    pid,
                    None,
                    description,
                    unit,
                    qty,
                    unit_price,
                    qty * unit_price,
                    category,
                    now(),
                ),
            )

        file_rows = [dict(row) for row in c.execute("SELECT * FROM files WHERE project_id=?", (pid,)).fetchall()]
        analysis = build_analysis(pid, file_rows)
        confirmed = [
            {
                "id": "demo-int-001",
                "code": "INT-001",
                "severity": "Crítica",
                "category": "Interface confirmada",
                "title": "Duto principal de climatização atravessa viga V-34",
                "description": "O duto de insuflamento 900×500 mm intercepta a viga estrutural no eixo F/7, pavimento 3. A abertura não consta no projeto estrutural.",
                "evidence": ["HVAC_DUTOS_E_EQUIPAMENTOS_R03.ifc", "EST_FORMAS_E_ARMACAO_R03.ifc"],
                "recommendedAction": "Desviar o duto ou emitir detalhamento de reforço estrutural antes da fabricação. Impacto estimado: R$ 86.000 e 9 dias se executado sem correção prévia.",
                "status": "Aguardando projetista estrutural",
            },
            {
                "id": "demo-int-002",
                "code": "INT-002",
                "severity": "Alta",
                "category": "Interface confirmada",
                "title": "Prumada sanitária sem reserva na laje do pavimento 2",
                "description": "A prumada PS-07 está deslocada 32 cm em relação ao furo estrutural previsto, atingindo a faixa de armadura negativa.",
                "evidence": ["SAN_ESGOTO_E_VENTILACAO_R02.ifc", "EST_FORMAS_E_ARMACAO_R03.ifc"],
                "recommendedAction": "Revisar o caminhamento sanitário e validar nova reserva com o calculista antes de qualquer perfuração.",
                "status": "Em correção",
            },
            {
                "id": "demo-int-003",
                "code": "INT-003",
                "severity": "Alta",
                "category": "Revisão",
                "title": "Arquitetura R04 ainda utilizada pela equipe de campo",
                "description": "O canteiro possui pranchas impressas R04, enquanto a base de coordenação já contém a revisão R05, que altera sanitários e shafts.",
                "evidence": ["ARQ_EXECUTIVO_TORRE_A_R04.ifc", "ARQ_EXECUTIVO_TORRE_A_R05.ifc", "LEVANTAMENTO_CAMPO_12-07-2026.pdf"],
                "recommendedAction": "Recolher cópias superadas, registrar distribuição da R05 e bloquear serviços dos ambientes afetados até conferência.",
                "status": "Aberta",
            },
            {
                "id": "demo-orc-004",
                "code": "ORC-004",
                "severity": "Alta",
                "category": "Projeto × Orçamento",
                "title": "Automação BMS prevista no escopo, mas sem projeto recebido",
                "description": "O orçamento contém R$ 465.000 para automação predial, porém não há projeto AUT/BMS na base documental.",
                "evidence": ["ORCAMENTO_EXECUTIVO_R05.xlsx", "MEMORIAL_DESCRITIVO_R03.pdf"],
                "recommendedAction": "Solicitar projeto de automação, lista de pontos e integração com HVAC, elétrica e incêndio antes da contratação.",
                "status": "Aberta",
            },
            {
                "id": "demo-cam-005",
                "code": "CAM-005",
                "severity": "Média",
                "category": "Ocorrência de campo",
                "title": "Quadro QGBT-02 sem área livre para manutenção",
                "description": "A parede executada reduziu a faixa frontal de manutenção para 72 cm, abaixo do previsto no layout coordenado.",
                "evidence": ["ELE_FORCA_ILUMINACAO_R04.dwg", "LEVANTAMENTO_CAMPO_12-07-2026.pdf"],
                "recommendedAction": "Readequar o fechamento antes da instalação definitiva do quadro e atualizar a arquitetura as built.",
                "status": "Em correção",
            },
            {
                "id": "demo-pra-006",
                "code": "PRA-006",
                "severity": "Média",
                "category": "Prazo",
                "title": "Liberação do forro depende de três pendências críticas",
                "description": "A montagem do forro do pavimento 3 está programada para 03/08/2026, mas depende da solução do duto, da prumada e da revisão de sprinklers.",
                "evidence": ["CRONOGRAMA_INTEGRADO_R04.mpp"],
                "recommendedAction": "Criar marco de liberação técnica e reprogramar a frente apenas após fechamento das interfaces.",
                "status": "Monitorando",
            },
        ]
        analysis["issues"] = confirmed + analysis.get("issues", [])
        analysis["summary"] = {
            "critical": sum(i["severity"] == "Crítica" for i in analysis["issues"]),
            "high": sum(i["severity"] == "Alta" for i in analysis["issues"]),
            "medium": sum(i["severity"] == "Média" for i in analysis["issues"]),
            "low": sum(i["severity"] == "Baixa" for i in analysis["issues"]),
        }
        analysis["gate"] = "Bloqueada para liberação do pavimento 3"
        analysis["readiness"] = 68
        analysis["projectSnapshot"] = {
            "physicalProgress": 38,
            "plannedProgress": 42,
            "estimatedBudget": 9_018_302.00,
            "committedCost": 3_426_955.00,
            "potentialAvoidedLoss": 238_000.00,
            "nextGate": "Liberação técnica do forro — pavimento 3",
            "targetDate": "2026-08-03",
        }
        analysis["id"] = uuid4().hex
        analysis["createdAt"] = now()
        c.execute(
            "INSERT INTO analyses VALUES(?,?,?,?)",
            (analysis["id"], pid, json.dumps(analysis, ensure_ascii=False), analysis["createdAt"]),
        )
