"""Deterministic checks (free, reproducible): what a rule can see reliably without a model.
Every defect quotes the document verbatim, so the report never contains a remark without a place."""
from __future__ import annotations

import re

from ..models import Document
from ..parsing import load_rules, sentences
from .models import Defect, Requirement

NUM_UNIT = re.compile(r"\d[\d\s]*(?:[.,]\d+)?\s*(?:₸|тенге|тиын|%|мс|сек|секунд\w*|мин\w*|час\w*|дн\w*|раз\w*|запрос\w*)", re.I)
# a named class or a storage column is a design decision, not a requirement (29148 §5.2.5 b)
DESIGN_TOKEN = re.compile(r"\b[A-Z][A-Za-z0-9]+(?:Controller|Repository)\b|\b[a-z][a-z0-9]*_[a-z0-9]+\b")


def is_design_decision(d: Defect) -> bool:
    """True when the finding cites a concrete implementation choice. The Critic must not drop these."""
    return d.prop == "appropriate" and bool(DESIGN_TOKEN.search(f"{d.quote} {d.problem}"))


def _first_sentence_with(text: str, rx: re.Pattern) -> str:
    for s in re.split(r"(?<=[.!?])\s+|\s+или\s+(?=[{\[])", text):
        if rx.search(s):
            return s.strip()
    return ""


def _req_word(n: int) -> str:
    k = n % 100
    return "требований" if 10 < k < 20 else "требование" if k % 10 == 1 else "требования" if 2 <= k % 10 <= 4 else "требований"


def requirement_checks(reqs: list[Requirement]) -> list[Defect]:
    rules = load_rules()
    out: list[Defect] = []
    for r in reqs:
        # 1) vague words → ambiguous / unverifiable (unless the sentence already has a measurable criterion)
        for v in rules.get("vague_words", []):
            rx = re.compile(v["pattern"], re.I)
            s = _first_sentence_with(r.text, rx)
            if s and not NUM_UNIT.search(s):
                word = rx.search(s).group(0)
                prop = "verifiable" if r.kind in ("nfr", "acceptance") else "unambiguous"
                out.append(Defect(prop=prop, severity="major", quote=s, rids=[r.rid], agent="ambiguity",
                                  problem=f"Слово «{word}» не задаёт измеримого критерия — разработчик и тестировщик поймут его по-разному.",
                                  fix=v["why"] if v.get("why") else "Заменить на число с единицей измерения и условием."))
        # 2) several rules in one item → not singular
        sents = [s for s in sentences(r.text) if len(s) > 12]
        if r.kind in ("functional", "nfr", "data", "integration", "api") and len(sents) >= 3:
            out.append(Defect(prop="singular", severity="minor", quote=sents[0], rids=[r.rid], agent="testability",
                              problem=f"В одном пункте {len(sents)} отдельных правил — их нельзя проверить и проследить по отдельности.",
                              fix=f"Разбить {r.doc_id} на {len(sents)} пронумерованных требования ({r.doc_id}.1…{r.doc_id}.{len(sents)})."))
        low = r.text.lower()
        # 3) an empty value in a passport row («Prod: —», «Swagger — —»)
        passport = r.doc_id.lower().startswith(("общие параметры", "общие сведения"))
        if r.kind == "api" and passport and re.search(r"(:\s*—\s*$|—\s*—\s*$|prod:\s*—)", r.text.strip(), re.I):
            out.append(Defect(prop="complete", severity="major", quote=r.text.strip(), rids=[r.rid], agent="completeness",
                              problem="Значение не заполнено (стоит прочерк) — по документу нельзя настроить или проверить окружение.",
                              fix="Указать значение или явно записать, что параметр не применяется и почему."))
        # 4) HTTP semantics: a method that changes data declared as GET
        if re.search(r"rest type\s*—\s*get\b", low):
            out.append(Defect(prop="correct", severity="critical", quote=r.text.strip(), rids=[r.rid], agent="integrations",
                              problem="Метод сохраняет настройку (URL /alerts/saveLimit, «Сохранение порога»), но объявлен как GET: "
                                      "GET не должен менять данные, его кешируют прокси и повторяют браузеры.",
                              fix="Объявить метод как POST или PUT, параметры передать в теле запроса."))
        # 5) an error inside a successful status
        if '"result":"error"' in low.replace(" ", "") and re.search(r"\b200\b", r.doc_id + " " + r.text):
            out.append(Defect(prop="correct", severity="major", quote=_first_sentence_with(r.text, re.compile("ERROR")) or r.text[:120],
                              rids=[r.rid], agent="integrations",
                              problem="Ошибка сохранения возвращается со статусом 200 «Successful — Created» — клиент не отличит успех от отказа по коду.",
                              fix="Для отклонённой суммы вернуть 400 (или 422) с телом {\"result\":\"ERROR\",\"message\":…}."))
        # 6) a named class or a storage column — a design decision, not a requirement
        cls = re.search(r"\b[A-Z][A-Za-z0-9]+(?:Controller|Repository)\b", r.text)
        if cls:
            out.append(Defect(prop="appropriate", severity="major", quote=r.text.strip(), rids=[r.rid], agent="integrations",
                              problem=f"«{cls.group(0)}» — проектное решение (класс, контроллер), а не требование: документ фиксирует, как реализовать, и закрывает другую реализацию.",
                              fix="Описать поведение без имени класса: кто вызывает, что сохраняется и что возвращается."))
        col = re.search(r"\b[a-z][a-z0-9]*_[a-z0-9]+\b", r.text) if r.kind in ("api", "design", "data") else None
        if col:
            out.append(Defect(prop="appropriate", severity="major", quote=r.text.strip(), rids=[r.rid], agent="integrations",
                              problem=f"«{col.group(0)}» — имя поля хранения, а не требование. Разработка привяжется к схеме, которой в требованиях быть не должно.",
                              fix="Убрать имя поля. Оставить смысл: что хранится, в какой единице и при каком условии."))
        # 7) a status section that describes another status
        m = re.search(r"\b(\d{3})\b", r.doc_id)
        if m and re.search(r"возвращается\s+(\d{3})", r.text) and re.search(r"возвращается\s+(\d{3})", r.text).group(1) != m.group(1):
            other = re.search(r"возвращается\s+(\d{3})", r.text).group(1)
            out.append(Defect(prop="correct", severity="major", quote=_first_sentence_with(r.text, re.compile("возвращается")),
                              rids=[r.rid], agent="integrations",
                              problem=f"Раздел статуса {m.group(1)} описывает ответ {other} — непонятно, возвращается ли {m.group(1)} вообще.",
                              fix=f"Убрать статус {m.group(1)} из перечня или описать, в каком случае он возвращается; {other} описать отдельным пунктом."))
    return out


def set_checks(doc: Document, reqs: list[Requirement], skipped: list[str]) -> list[Defect]:
    full = doc.full_text()
    low = full.lower()
    by_kind = lambda k: [r for r in reqs if r.kind == k]
    out: list[Defect] = []
    # placeholders instead of content
    for s in skipped:
        if "заглушка" in s:
            place, rest = s.split(" — ", 1)
            q = re.search(r"«(.+?)»", rest)
            out.append(Defect(prop="complete", severity="major", quote=q.group(1) if q else "", place=place, agent="completeness",
                              problem=f"Раздел «{place.split(' · ')[-1]}» не заполнен — вместо требований стоит заглушка.",
                              fix="Заполнить раздел или удалить его, указав, где описано тестирование требований."))
    # money in two units
    data = " ".join(r.text for r in by_kind("data"))
    if re.search(r"тиын", data, re.I) and re.search(r"тенге|₸", data, re.I):
        r = by_kind("data")[0]
        out.append(Defect(prop="consistent", severity="major", quote=_first_sentence_with(r.text, re.compile("тиын", re.I)) or r.text,
                          rids=[r.rid], agent="contradictions",
                          problem="Сумма покупки хранится в тиынах, а порог — в тенге: сравнение «расходы ≥ порог» требует пересчёта, "
                                  "который нигде не описан (риск ошибки в 100 раз).",
                          fix="Хранить обе величины в одной единице (тиынах) или явно задать правило пересчёта и округления."))
    # the review checklist is left as a template
    if re.search(r"да\s*/\s*нет", low) and "ревью требований" in low:
        out.append(Defect(prop="modifiable", severity="minor", quote=_first_sentence_with(full, re.compile("Да / Нет")) or "Да / Нет",
                          place="Часть A · Ревью требований", agent="critic",
                          problem="Чек-лист ревью не заполнен: отметки «Да / Нет» не проставлены — нет подтверждения, что документ прошёл ревью.",
                          fix="Проставить отметки и примечания по каждому пункту чек-листа."))
    # approvals
    if "блок согласующих" in low:
        sec = next((s for s in doc.sections if "согласующ" in (s.title or "").lower()), None)
        rows = [s for s in doc.sections if sec and s.ref.startswith(sec.ref + ".")]
        if not any(re.search(r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.", s.text or "") for s in rows):
            out.append(Defect(prop="traceable", severity="major", quote="Подразделение — ФИО ответственного — Подпись",
                              place="Часть A · Блок согласующих", agent="critic",
                              problem="Лист согласования пуст — неизвестно, кто утвердил требования и с кем согласованы изменения смежных систем.",
                              fix="Указать подразделения, ответственных и даты согласования (процессинг, сервис уведомлений, ИБ)."))
    # version / date
    if re.search(r"версия/дата\)?\s*в источнике не заполнен|не заполнен", low) or not re.search(r"версия\s*[:№]?\s*\d", low):
        q = _first_sentence_with(full, re.compile(r"версия/дата", re.I))
        out.append(Defect(prop="modifiable", severity="major", quote=q, place="Часть A · Ревью требований" if q else "документ целиком",
                          agent="critic",
                          problem="У документа нет версии и даты — нельзя понять, по какой редакции разрабатывать и тестировать.",
                          fix="Добавить номер версии, дату и таблицу истории изменений."))
    # identifiers
    with_id = [r for r in reqs if re.match(r"^[А-ЯЁA-Z]{1,5}[-–.]?\d", r.doc_id)]
    if reqs and len(with_id) < len(reqs) * 0.5:
        ids = ", ".join(r.doc_id for r in with_id[:6]) or "нет"
        no_id = list(dict.fromkeys(r.section.split(" · ")[-1] for r in reqs if r not in with_id))
        out.append(Defect(prop="traceable", severity="major", quote="", place="разделы без номеров: " + ", ".join(no_id[:8]),
                          rids=[r.rid for r in reqs if r not in with_id][:3], agent="dispatcher",
                          problem=f"Уникальные идентификаторы есть только у {len(with_id)} из {len(reqs)} требований ({ids}); "
                                  "НФТ, требования к данным, интеграции, критерии приёмки и всё API без номеров — их нельзя связать с тестами.",
                          fix="Пронумеровать все требования (НФТ-1, Д-1, И-1, АК-1, API-1…) и связать критерии приёмки с Ф-номерами."))
    # priorities
    if not re.search(r"приоритет|must|should|could|обязательн\w* для релиза|moscow", low):
        out.append(Defect(prop="ranked", severity="minor", quote="", place=f"все {len(reqs)} {_req_word(len(reqs))} (R-01–R-{len(reqs):02d})",
                          agent="dispatcher",
                          problem="У требований нет приоритета и стабильности — непонятно, что обязательно для первого релиза.",
                          fix="Добавить приоритет (MoSCoW или 1–3) к каждому требованию."))
    # glossary
    if not re.search(r"термин|глоссари|определени", low):
        terms = [t for t in ("тиын", "push", "BPMN", "Sequence", "Bearer", "KZT") if t.lower() in low][:5]
        first = {t: next((r for r in reqs if t.lower() in r.text.lower()), None) for t in terms}
        where = "; ".join(f"«{t}» — {r.rid} ({r.doc_id})" for t, r in first.items() if r)
        if terms:
            out.append(Defect(prop="comprehensible", severity="minor", quote="", place=where or "документ целиком",
                              rids=[r.rid for r in first.values() if r][:3], agent="clarifier",
                              problem=f"Нет раздела терминов: {', '.join(terms)} и «держатель активной карты» не определены.",
                              fix="Добавить глоссарий: что считается активной картой, проведённой покупкой, возвратом, push."))
    return out
