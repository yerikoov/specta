"""Completeness: missing / empty template sections (template.yaml = the checklist)."""
from __future__ import annotations

import re

from ..models import Document, Finding, PatchOp
from ..parsing import section_body
from .base import BaseAgent, make_options


class CompletenessAgent(BaseAgent):
    id = "completeness"
    use_llm = True
    focus = "смысловые пропуски: разделы шаблона, которые формально есть, но не раскрыты по подсказкам шаблона."

    def rules(self, doc: Document) -> list[Finding]:
        out = []
        for t in self.ctx["template"]["sections"]:
            sec = doc.by_template(t["key"])
            create_full = [PatchOp(mode="create", template_key=t["key"], text=t.get("default", ""))]
            create_stub = [PatchOp(mode="create", template_key=t["key"], text=f"TODO: заполнить — {t.get('hint', '')}")]
            if sec is None:
                sev = t.get("severity", "important") if t.get("required") else "minor"
                first = (("Добавить раздел с подсказкой — заполню конкретикой", create_full) if t.get("stub")
                         else ("Добавить типовой раздел (агенты заполнят)", create_full))
                opts = [first] + ([] if t.get("stub") else [("Добавить заготовку — заполню сам", create_stub)])
                out.append(self.finding(
                    severity=sev, key=t["key"], topic=f"section:{t['key']}",
                    text=f"В ТЗ нет раздела «{t['name']}». {t.get('hint', '')}",
                    question=f"Раздела «{t['name']}» нет. Что делаем?",
                    why=f"Шаблон ожидает: {t.get('hint', '')}" if t.get("required") else "Раздел необязательный, но полезный.",
                    options=make_options(opts + [("Не нужен в этом проекте", [PatchOp(mode="none")])]),
                ))
            elif self._is_stub(doc, sec, t):
                # a placeholder is not a requirement: it stays open (and keeps the score honest) until filled in
                out.append(self.finding(
                    severity="important", key=t["key"] + ":stub",       # an unfinished section, required or not
                    section_ref=sec.ref, topic=f"stub:{t['key']}",
                    text=f"Раздел «{sec.title}» (п. {sec.ref}) — пока только заготовка. Впишите конкретику: {t.get('hint', '')}",
                    why="Заготовка описывает, что должно быть в разделе, но разработчику и тестировщику в ней нечего проверять.",
                ))
            elif len(section_body(doc, sec.ref)) - len(sec.title) < 15:
                out.append(self.finding(
                    severity="important" if t.get("required") else "minor", key=t["key"] + ":empty",
                    section_ref=sec.ref, topic=f"section:{t['key']}",
                    text=f"Раздел «{sec.title}» (п. {sec.ref}) пустой.",
                    question=f"Раздел п. {sec.ref} пуст. Заполнить типовым содержанием?",
                    why=t.get("hint", ""),
                    options=make_options([
                        ("Заполнить типовым текстом", [PatchOp(mode="append", section_ref=sec.ref, text=t.get("default", ""))]),
                        ("Оставить — заполню сам", [PatchOp(mode="none")]),
                    ]),
                ))
        return out

    @staticmethod
    def _is_stub(doc: Document, sec, t: dict) -> bool:
        body = " ".join(section_body(doc, sec.ref).split())
        if "TODO:" in body:
            return True
        default = " ".join((t.get("default") or "").split())
        if not (t.get("stub") and default and default in body):
            return False
        rest = body.replace(default, "").replace(sec.title, "").strip(" .\n")
        return len(re.sub(r"\b\d+(\.\d+)*\b", "", rest).strip()) < 15     # nothing written besides the hint

    def extra_prompt(self, doc):
        hints = "\n".join(f"- {t['name']}: {t.get('hint', '')}" for t in self.ctx["template"]["sections"])
        return f"Разделы шаблона:\n{hints}\n\n"
