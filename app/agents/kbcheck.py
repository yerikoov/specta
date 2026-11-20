"""Shared logic for KB-driven agents (Fintech/Regulatory, Security): RAG over /kb."""
from __future__ import annotations

import re

from ..kb import checks_for, retrieve
from ..models import Document, Finding, PatchOp
from .base import BaseAgent, make_options


class KBCheckAgent(BaseAgent):
    use_llm = True

    def rules(self, doc: Document) -> list[Finding]:
        text = doc.full_text().lower() + "\n" + "\n".join(doc.appendix).lower()
        out = []
        for kbdoc, chk in checks_for(self.id):
            if chk.get("applies_if") and not any(re.search(p, text) for p in chk["applies_if"]):
                continue
            if any(re.search(p, text) for p in chk.get("present", [])):
                continue
            target = kbdoc.get("target", "compliance")
            sec = doc.by_template(target)
            opts = [(o["label"], [PatchOp(mode="append", template_key=target, text=o["text"])]) for o in chk["options"]]
            out.append(self.finding(
                severity=chk.get("severity", "important"), key=chk["id"], section_ref=sec.ref if sec else None,
                topic=f"kb:{chk['id']}",
                text=f"Не описано: {chk['title']}. {chk.get('why', '')}",
                question=chk["question"], why=chk.get("why"), options=make_options(opts),
            ))
        return out

    def extra_prompt(self, doc):
        chunks = retrieve(doc.full_text(), k=3, agent=self.id)
        return "Справка из базы знаний:\n" + "\n---\n".join(c["body"] for c in chunks) + "\n\n" if chunks else ""


class RegulatoryAgent(KBCheckAgent):
    id = "regulatory"
    focus = "пропущенные требования регулятора: KYC/AML, персональные данные, платёжное законодательство РК, PCI DSS."

    def summary(self, found):
        return f"Сверил с базой знаний: {len(found)} пробелов в комплаенсе" if found else "Комплаенс-пункты на месте"


class SecurityAgent(KBCheckAgent):
    id = "security"
    focus = "пропущенные требования информационной безопасности мобильного банкинга."

    def summary(self, found):
        return f"{len(found)} требований ИБ не хватает" if found else "Требования ИБ описаны"
