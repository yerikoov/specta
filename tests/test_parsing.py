import io
from pathlib import Path

import docx

from app.parsing import parse_bytes, sentences

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample_tz_p2p.md"


def test_markdown_sections_and_refs():
    doc = parse_bytes("tz.md", SAMPLE.read_bytes())
    assert doc.title.startswith("Техническое задание")
    top = [s for s in doc.sections if s.level == 1]
    assert [s.ref for s in top] == ["1", "2", "3", "4", "5", "6", "7", "8"]
    assert doc.get("3.2") and "OTP" in doc.get("3.2").text
    assert doc.get("4.1").text == "Приложение должно работать быстро."


def test_template_mapping():
    doc = parse_bytes("tz.md", SAMPLE.read_bytes())
    keys = {s.template_key for s in doc.sections if s.template_key}
    assert {"general", "goals", "functional", "nfr", "schedule"} <= keys
    assert doc.by_template("security") is None


def test_plain_text_numbering():
    txt = "ТЗ на кредитный калькулятор\n1. Общие положения\n1.1 Калькулятор считает аннуитет.\n2. Требования\n2.1 Расчёт должен быть быстрым.\n"
    doc = parse_bytes("x.txt", txt.encode("utf-8"))
    assert doc.title == "ТЗ на кредитный калькулятор"
    assert [s.ref for s in doc.sections] == ["1", "1.1", "2", "2.1"]


def test_docx_headings():
    d = docx.Document()
    d.add_heading("ТЗ: платёжный шлюз", 0)
    d.add_heading("1. Общие сведения", 1)
    d.add_paragraph("1.1 Шлюз принимает платежи по картам.")
    d.add_heading("Интеграции", 1)
    d.add_paragraph("Обмен по REST.")
    buf = io.BytesIO()
    d.save(buf)
    doc = parse_bytes("gw.docx", buf.getvalue())
    assert doc.get("1.1") is not None
    assert any(s.title == "Интеграции" and s.template_key == "integrations" for s in doc.sections)


def test_sentence_split_keeps_numbers():
    s = sentences("Комиссия — 0,5% от суммы. Запуск — 01.02.2027. Код действует 60 секунд.")
    assert len(s) == 3 and "0,5%" in s[0]
