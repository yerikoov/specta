"""Integrations: external systems mentioned without protocol / timeouts / errors."""
from __future__ import annotations

import re

from ..models import Document, Finding, PatchOp
from .base import BaseAgent, iter_sentences, make_options

MENTION = re.compile(r"интегр|взаимодейств|процессинг|шлюз|\bабс\b|\bapi\b", re.I)
SPECIFIC = re.compile(r"rest|soap|json|xml|iso\s?8583|протокол|таймаут|формат|swagger|openapi|grpc|mq\b", re.I)


class IntegrationsAgent(BaseAgent):
    id = "integrations"

    def rules(self, doc: Document) -> list[Finding]:
        out = []
        for sec, sent in iter_sentences(doc):
            if not MENTION.search(sent) or SPECIFIC.search(sent):
                continue
            systems = ", ".join(sorted({m.group(0).lower() for m in MENTION.finditer(sent)}))
            opts = make_options([
                ("REST/JSON по TLS 1.2+, таймаут 5 с, 3 повтора",
                 [PatchOp(mode="append", template_key="integrations",
                          text=f"Интеграции по п. {sec.ref}: REST/JSON поверх TLS 1.2+, таймаут ответа — 5 с, до 3 повторов с экспоненциальной задержкой; при недоступности внешней системы операция не проводится и деньги не списываются, клиенту показывается сообщение «Сервис временно недоступен».")]),
                ("Свой протокол и таймаут для каждой системы",
                 [PatchOp(mode="append", template_key="integrations",
                          text=f"Интеграции по п. {sec.ref}: для каждой внешней системы фиксируются протокол (REST/JSON, ISO 8583 или SOAP), таймаут (3–10 с), число повторов и резервный сценарий при её недоступности.")]),
                ("Описать в отдельной спецификации API (приложение А)",
                 [PatchOp(mode="append", template_key="integrations",
                          text=f"Протоколы, форматы сообщений, таймауты и коды ошибок интеграций по п. {sec.ref} описываются в спецификации API (приложение А), которая утверждается до начала разработки.")]),
            ])
            out.append(self.finding(
                severity="important", key="no_protocol", section_ref=sec.ref, quote=sent,
                text=f"Интеграция упомянута ({systems}), но не указаны протокол, формат, таймауты и поведение при сбое.",
                question=f"Как система взаимодействует с внешними системами из п. {sec.ref}?",
                why="Без протокола и таймаутов команда не оценит трудоёмкость, а сбой внешней системы сломает основной сценарий.",
                options=opts,
            ))
        return out
