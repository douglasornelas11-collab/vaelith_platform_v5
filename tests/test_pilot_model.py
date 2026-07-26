from compatibility_engine import build_analysis, infer_discipline, infer_revision
from server import _budget_category, parse_budget


def f(name, code, revision="R01", checksum=""):
    return {
        "id": name,
        "name": name,
        "ext": "." + name.rsplit(".", 1)[-1].lower(),
        "size": 1024,
        "discipline_code": code,
        "discipline": code,
        "revision": revision,
        "checksum": checksum,
    }


def complete_base():
    return [
        f("ARQ_R03.ifc", "ARQ", "R03"),
        f("EST_R02.ifc", "EST", "R02"),
        f("HID_R04.ifc", "HID", "R04"),
        f("ELE_R02.dwg", "ELE", "R02"),
        f("HVAC_R01.rvt", "HVAC", "R01"),
        f("ORC_R05.xlsx", "ORC", "R05"),
        f("CRONO_R02.mpp", "PLA", "R02"),
        f("MEMORIAL_R03.pdf", "ESC", "R03"),
    ]


def test_complete_base_generates_interfaces_without_document_blocker():
    result = build_analysis("pilot-ok", complete_base())
    assert result["gate"] == "Pronta para conferência integrada"
    assert result["files"] == 8
    assert {d["code"] for d in result["disciplines"]} >= {"ARQ", "EST", "HID", "ELE", "HVAC", "ORC", "PLA", "ESC"}
    assert len(result["interfacePackages"]) >= 8
    assert not [i for i in result["issues"] if i["code"] in {"DOC-CORE", "DOC-UNK"}]


def test_concurrent_revision_blocks_round():
    files = complete_base() + [f("HID_R05.ifc", "HID", "R05")]
    result = build_analysis("pilot-revision", files)
    assert result["gate"] == "Bloqueada"
    assert any(i["code"] == "REV-HID" for i in result["issues"])


def test_missing_core_discipline_blocks_round():
    files = [x for x in complete_base() if x["discipline_code"] != "ELE"]
    result = build_analysis("pilot-missing", files)
    assert result["gate"] == "Bloqueada"
    assert any(i["code"] == "DOC-CORE" and "Elétrica" in i["evidence"] for i in result["issues"])


def test_unknown_file_requires_manual_classification():
    files = complete_base() + [f("PROJETO_FINAL_NOVO.pdf", "UNK", "Não informada")]
    result = build_analysis("pilot-unknown", files)
    assert any(i["code"] == "DOC-UNK" for i in result["issues"])


def test_duplicate_content_is_detected():
    files = complete_base()
    files[0]["checksum"] = "same-content"
    files[1]["checksum"] = "same-content"
    result = build_analysis("pilot-duplicate", files)
    assert any(i["code"].startswith("DUP-") for i in result["issues"])


def test_filename_inference():
    assert infer_discipline("Projeto_Arquitetura_R07.ifc")[0] == "ARQ"
    assert infer_discipline("HVAC_REV03.rvt")[0] == "HVAC"
    assert infer_revision("ELE_REV_009.dwg") == "R09"


def test_budget_csv_is_parsed_and_classified():
    raw = (
        "Descrição;Unidade;Quantidade;Preço unitário;Valor total\n"
        "Eletrocalha galvanizada;m;100;50,00;5000,00\n"
        "Duto de climatização;m2;20;200,00;4000,00\n"
        "Pintura acrílica;m2;50;30,00;1500,00\n"
    ).encode("utf-8")
    items = parse_budget(raw, ".csv")
    assert len(items) == 3
    assert {item["category"] for item in items} == {"ELE", "HVAC", "ARQ"}
    assert sum(item["total"] for item in items) == 10500


def test_budget_unknown_description_is_not_forced_into_discipline():
    assert _budget_category("Serviço especial conforme projeto") == "OUT"
