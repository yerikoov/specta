"""Ambiguity: vague words without numbers (regex rules from config/rules.yaml)."""
from __future__ import annotations

import re

from ..models import Document, Finding, PatchOp
from .base import BaseAgent, iter_sentences, make_options

DIGIT = re.compile(r"\d")


class AmbiguityAgent(BaseAgent):
    id = "ambiguity"
    use_llm = True
    focus = "размытые, субъективные или неоднозначные формулировки, которых нет в словаре правил."

    def rules(self, doc: Document) -> list[Finding]:
        out, seen = [], set()
        for sec, sent in iter_sentences(doc):
            for rule in self.ctx["rules"]["vague_words"]:
                m = re.search(rule["pattern"], sent, flags=re.I)
                if not m or (sec.ref, rule["id"]) in seen:
                    continue
                seen.add((sec.ref, rule["id"]))
                word = m.group(0).strip()
                # a number right after the word means it is already measurable (Critic drops it)
                has_number = bool(DIGIT.search(sent[m.end(): m.end() + 45]))
                opts = []
                for o in rule["options"]:
                    new = o["replace"].replace("{w}", word)
                    opts.append((o["label"], [PatchOp(mode="replace", section_ref=sec.ref, find=word,
                                                      pattern=rule["pattern"], text=new)]))
                out.append(self.finding(
                    severity=rule.get("severity", "important"), key=rule["id"], section_ref=sec.ref,
                    topic="load" if rule["id"] == "many" else None,
                    quote=sent, text=f"«{word}» — нет измеримого критерия. {rule['why']}",
                    question=f"Что именно значит «{word}» в п. {sec.ref}?", why=rule["why"],
                    options=make_options(opts),
                    confidence=0.3 if has_number else 0.95,
                    drop_reason="в предложении уже есть числовой критерий" if has_number else None,
                ))
        return out

    def summary(self, found):
        n = len(found)
        return f"Отметил {n} размытых формулировок" if n else "Формулировки чёткие"
