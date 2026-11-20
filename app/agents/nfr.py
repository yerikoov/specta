"""NFR: availability, load, recovery — must be numbers."""
from __future__ import annotations

import re

from ..models import Document, Finding, PatchOp
from .base import BaseAgent, make_options

CHECKS = [
    {"id": "availability", "topic": "availability", "severity": "important",
     "present": r"\d+[.,]?\d*\s*%.{0,40}доступн|доступн.{0,40}\d+[.,]?\d*\s*%",
     "text": "Не задана доступность сервиса в процентах.",
     "question": "Какая доступность сервиса нужна?", "why": "Без цифры доступности нельзя выбрать архитектуру и SLA.",
     "options": [("99,9% в месяц (≈ 43 мин простоя)", "Доступность сервиса — не ниже 99,9% в месяц."),
                 ("99,95% в месяц (≈ 22 мин простоя)", "Доступность сервиса — не ниже 99,95% в месяц."),
                 ("99,5% на пилоте, 99,9% после запуска", "Доступность на пилоте — не ниже 99,5%, после промышленного запуска — не ниже 99,9% в месяц.")]},
    {"id": "load", "topic": "load", "severity": "important",
     "present": r"rps|в секунду|одновременн\w* \d|\d[\d\s]* (одновременн|операц|запрос|пользовател)",
     "text": "Не задана расчётная нагрузка (RPS, пользователи).",
     "question": "На какую нагрузку рассчитываем систему?", "why": "Нагрузочное тестирование невозможно без целевых чисел.",
     "options": [("300 операций в секунду в пике", "Пиковая нагрузка — 300 операций в секунду, средняя — 50."),
                 ("50 000 одновременных пользователей", "Система выдерживает 50 000 одновременных пользователей без деградации времени отклика.")]},
    {"id": "recovery", "topic": "recovery", "severity": "minor",
     "present": r"\brto\b|\brpo\b|резервн\w* коп|восстановлен",
     "text": "Не заданы RTO/RPO и резервное копирование.",
     "question": "Какие RTO и RPO допустимы?", "why": "Нужно знать, сколько данных и времени можно потерять при аварии.",
     "options": [("RTO 1 ч, RPO 5 мин", "RTO — 1 час, RPO — 5 минут; резервное копирование — ежедневно, хранение копий 30 дней."),
                 ("RTO 4 ч, RPO 1 ч", "RTO — 4 часа, RPO — 1 час; резервное копирование — ежедневно.")]},
]


class NFRAgent(BaseAgent):
    id = "nfr"

    def rules(self, doc: Document) -> list[Finding]:
        text = doc.full_text().lower()
        sec = doc.by_template("nfr")
        out = []
        for c in CHECKS:
            if re.search(c["present"], text):
                continue
            tgt = {"section_ref": sec.ref} if sec else {"template_key": "nfr"}
            out.append(self.finding(
                severity=c["severity"], key=c["id"], topic=c["topic"], section_ref=sec.ref if sec else None,
                text=c["text"], question=c["question"], why=c["why"],
                options=make_options([(lbl, [PatchOp(mode="append", **tgt, text=t)]) for lbl, t in c["options"]]),
            ))
        return out
