"""Is the uploaded file a technical specification at all? (cheap heuristic, no API calls)

A TZ is mostly requirement sentences («система должна…», «клиент может…», limits, numbers, deadlines).
A checklist, a review, meeting notes or an article about requirements is mostly talk *about* them.
"""
from __future__ import annotations

import re

from .models import Document
from .parsing import sentences

REQ = re.compile(r"должн|обязан|обеспечива|позволя|поддержива|выполня|допуска|не может|не должн|может\b|"
                 r"списыва|подтвержда|интегрир|доступ|хранится|хранятся|запуск|срок|лимит|комисси|"
                 r"\d+\s*(₸|тенге|%|секунд|минут|час|дн|месяц|лет|мс|rps)", re.I)
ACTOR = re.compile(r"\b(систем|сервис|клиент|пользовател|приложени|банк|оператор|администратор|магазин)\w*", re.I)
META = re.compile(r"агент\w*|загрузите|проверьте|сверьте|шпаргалк|найдут|нашли|замечани|ловушк|"
                  r"критик|кеш|промпт|тест-кейс|чек-лист|оценк[аи] тз|в этом документе описан", re.I)


def tz_likeness(doc: Document) -> dict:
    sents = [x for s in doc.sections for x in sentences(((s.title + ". ") if s.title else "") + (s.text or ""))]
    sents = [x for x in sents if len(x) > 12]
    n = len(sents) or 1
    req = sum(1 for x in sents if REQ.search(x) and ACTOR.search(x)) / n
    meta = sum(1 for x in sents if META.search(x)) / n
    numbered = sum(1 for s in doc.sections if s.level >= 2)
    ok = len(sents) >= 5 and meta < 0.2 and (req >= 0.15 or (numbered >= 8 and req >= 0.08))
    reason = ""
    if not ok:
        if len(sents) < 5:
            reason = "в документе почти нет текста"
        elif meta >= 0.2:
            reason = "текст описывает проверку или замечания, а не требования к системе"
        else:
            reason = "мало требований вида «система должна…», лимитов и сроков"
    return {"ok": ok, "requirements_share": round(req, 2), "meta_share": round(meta, 2),
            "numbered_items": numbered, "reason": reason}
