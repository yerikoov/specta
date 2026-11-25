"""The static review the hackathon task asks for: one command, a report with the required sections, every defect
tied to a place. Runs offline (rule checks) — the model part is covered by test_local_and_pii / test_agent_loop."""
import asyncio
import json
from pathlib import Path

import pytest

from app import cli
from app.parsing import parse_bytes
from app.review.checks import requirement_checks, set_checks
from app.review.pipeline import _quote_ok, _norm, run_review
from app.review.report import render
from app.review.slicer import slice_requirements

ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "samples" / "test_tz_bnpl.md"
PDF = ROOT / "tests" / "fixtures" / "sample_bnpl.pdf"

API_DOC = """# Уведомление о расходах
## Функциональные требования
* **Ф-1.** Клиент задаёт порог от 1 000 до 1 000 000 ₸. По умолчанию выключено.
* **Ф-2.** Месяц определяется по дате покупки. В расходы входят покупки. Возврат уменьшает расходы. Переводы исключаются.
### Нефункциональные требования
Сервис должен работать быстро.
### Требования к данным
Хранить сумму покупки в тиынах и порог в тенге.
### Требования к тестированию
заполняются тестировщиками
### Критерии приемки
| Исходные условия | Действие | Ожидаемый результат |
| :--- | :--- | :--- |
| Расходы 48 500 ₸ | Покупка 1 500 ₸ | Один push |
## Часть B. REST API
### Общие параметры
| Поле | Значение |
| :--- | :--- |
| **REST type** | GET |
| **Request URL** | Dev: `/alerts/saveLimit` . Prod: — |
### Логика работы метода
1. Проверить сессию.
2. Заменить настройку.
"""


def test_status_codes_stuck_in_the_200_example_stay_under_statuses():
    text = """# Уведомление
## Часть B. REST API
## Статусы
200. Ответ в случае успешного выполнения метода
400. Ответ в случае, если параметры запроса заполнены неверно
## 200. Successful — Created
{"result":"OK","amount":"50000"}
401. Ответ в случае, если запрос выполнен без необходимой авторизации
403. Ответ в случае, если на указанный ресурс доступ запрещен
"""
    reqs, _ = slice_requirements(parse_bytes("api.md", text.encode()))
    by = {r.doc_id: r.section for r in reqs}
    assert by["Статусы, код 401"].endswith("Статусы")
    assert "200. Successful" not in by["Статусы, код 401"]
    assert by["Статусы, код 403"].endswith("Статусы")


def test_design_decisions_are_kept():
    text = """# Уведомление
## Схема
Приложение → AlertsController → хранилище настроек → AlertsController → приложение
## Ответ
amount — string — При успехе — Порог в тенге — limit_kzt
"""
    doc = parse_bytes("api.md", text.encode())
    reqs, _ = slice_requirements(doc)
    found = requirement_checks(reqs)
    assert any(d.prop == "appropriate" and "AlertsController" in d.quote for d in found)
    assert any(d.prop == "appropriate" and "limit_kzt" in d.quote for d in found)
    from app.review.checks import is_design_decision
    assert all(is_design_decision(d) for d in found if d.prop == "appropriate")


def test_slicing_keeps_document_ids_and_places():
    doc = parse_bytes("api.md", API_DOC.encode())
    reqs, skipped = slice_requirements(doc)
    ids = [r.doc_id for r in reqs]
    assert "Ф-1" in ids and "Ф-2" in ids
    assert "Критерии приемки, строка 1" in ids and "Логика работы метода, шаг 2" in ids
    assert all(r.rid == f"R-{i:02d}" for i, r in enumerate(reqs, 1))
    assert any("заглушка" in s for s in skipped)


def test_numbered_documents_use_their_clause_numbers():
    reqs, _ = slice_requirements(parse_bytes(MD.name, MD.read_bytes()))
    assert reqs[0].doc_id.startswith("п. ") and any(r.doc_id == "п. 3.5" for r in reqs)


def test_pdf_is_cut_like_the_markdown():
    a, _ = slice_requirements(parse_bytes(PDF.name, PDF.read_bytes()))
    b, _ = slice_requirements(parse_bytes(MD.name, MD.read_bytes()))
    assert [r.doc_id for r in a] == [r.doc_id for r in b]


def test_rule_checks_find_the_classic_defects():
    doc = parse_bytes("api.md", API_DOC.encode())
    reqs, skipped = slice_requirements(doc)
    props = {(d.prop, d.severity) for d in requirement_checks(reqs) + set_checks(doc, reqs, skipped)}
    assert ("correct", "critical") in props            # GET for a method that saves
    assert ("consistent", "major") in props            # тиыны vs тенге
    assert any(p == "verifiable" or p == "unambiguous" for p, _ in props)   # «быстро»
    assert ("singular", "minor") in props               # Ф-2 holds four rules
    assert ("complete", "major") in props               # a placeholder section / an empty value


def test_every_quote_is_verbatim():
    doc = parse_bytes("api.md", API_DOC.encode())
    rev = asyncio.run(run_review(API_DOC.encode(), "api.md", use_llm=False))
    text = _norm(doc.full_text())
    assert rev.req_defects and all(_quote_ok(d.quote, text) for d in rev.req_defects + rev.set_defects)
    assert not _quote_ok("этой фразы в документе нет совсем никогда", text)


def test_report_has_every_section_the_task_requires():
    rev = asyncio.run(run_review(MD.read_bytes(), MD.name, use_llm=False))
    md = render(rev)
    for head in ("## 1. Паспорт прогона", "## 2. Как агент нарезал требования", "## 3. Проверка каждого требования",
                 "## 4. Проверка всего набора требований", "## 5. Сводка", "## 6. Итог"):
        assert head in md
    for field in ("| Документ |", "| Дата прогона |", "| Модель |", "| Версия агента |"):
        assert field in md
    assert "Можно ли начинать разработку" in md and "Можно ли начинать тестирование" in md
    assert "| ID в отчёте | ID / место в документе |" in md


def test_cli_one_command_writes_the_report(tmp_path, monkeypatch):
    out = tmp_path / "report.md"
    js = tmp_path / "r.json"
    assert cli.main(["check", str(PDF), str(out), "--offline", "--no-anim", "--json", str(js)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Отчёт о проверке требований") and "sample_bnpl.pdf" in text
    assert json.loads(js.read_text())["requirements"]


def test_cli_explains_how_to_get_a_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    from app.llm import llm
    monkeypatch.setattr(llm, "client", None)
    assert cli.main(["check", str(MD), "-o", str(tmp_path / "r.md"), "--no-anim"]) == 3
    err = capsys.readouterr().out
    assert "console.anthropic.com" in err and "aistudio.google.com" in err


def test_cli_rejects_missing_or_unknown_files(tmp_path):
    assert cli.main(["check", str(tmp_path / "nope.pdf"), "--offline", "--no-anim"]) == 2
    bad = tmp_path / "x.exe"
    bad.write_bytes(b"MZ")
    assert cli.main(["check", str(bad), "--offline", "--no-anim"]) == 2


@pytest.mark.parametrize("schema_has_refs", [True])
def test_gemini_schema_is_flattened(schema_has_refs):
    from app.openai_compat import _flat
    from app.review.agents import RDefs
    flat = json.dumps(_flat(RDefs.model_json_schema()))
    assert "$ref" not in flat and "$defs" not in flat and "additionalProperties" not in flat
