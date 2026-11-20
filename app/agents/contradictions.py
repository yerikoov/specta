"""Contradictions: facts table built by code (numbers, limits, dates) + optional LLM confirmation."""
from __future__ import annotations

import re
from typing import Optional

from ..models import Document, Finding, PatchOp
from .base import BaseAgent, iter_sentences, make_options

VALUE_RE = {
    "money": re.compile(r"(\d{1,3}(?:[\s ]\d{3})+|\d+)(?:[.,]\d+)?\s*(₸|тенге|тг\.?|kzt|руб\w*)", re.I),
    "percent": re.compile(r"(\d+(?:[.,]\d+)?)\s*%"),
    "duration": re.compile(r"(\d+(?:[.,]\d+)?)\s*(секунд\w*|сек\b\.?|с\b|минут\w*|мин\b\.?|час\w*|ч\b|дн\w*|дней|суток|лет|год\w*|месяц\w*)", re.I),
    "date": re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b"),
    "count": re.compile(r"(\d+)"),
}
UNIT_SEC = {"сек": 1, "с": 1, "мин": 60, "час": 3600, "ч": 3600, "дн": 86400, "дне": 86400, "сут": 86400,
            "мес": 2592000, "год": 31536000, "лет": 31536000}


def normalize(kind: str, m: re.Match) -> object:
    if kind == "money":
        return int(re.sub(r"\D", "", m.group(1)))
    if kind == "percent":
        return float(m.group(1).replace(",", "."))
    if kind == "duration":
        unit = m.group(2).lower()
        mult = next((v for k, v in UNIT_SEC.items() if unit.startswith(k)), 1)
        return float(m.group(1).replace(",", ".")) * mult
    if kind == "date":
        return (m.group(3), m.group(2), m.group(1))
    return int(m.group(1))


def extract_value(kind: str, sentence: str, start: int) -> Optional[re.Match]:
    rx = VALUE_RE[kind]
    return rx.search(sentence, start) or rx.search(sentence)


def facts_table(doc: Document, keys: list[dict]) -> list[dict]:
    facts = []
    for sec, sent in iter_sentences(doc):
        for k in keys:
            sm = re.search(k["subject"], sent, flags=re.I)
            if not sm:
                continue
            vm = extract_value(k["kind"], sent, sm.start())
            if not vm:
                continue
            facts.append({"key": k["id"], "name": k["name"], "ref": sec.ref, "raw": vm.group(0).strip(),
                          "value": normalize(k["kind"], vm), "sentence": sent})
    return facts


def fmt_money(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₸"


class ContradictionsAgent(BaseAgent):
    id = "contradictions"
    use_llm = True
    focus = "логические противоречия между разделами: роли, права, последовательность шагов, условия (не только числа)."

    def rules(self, doc: Document) -> list[Finding]:
        keys = self.ctx["rules"]["fact_keys"]
        facts = facts_table(doc, keys)
        self.facts = facts
        out = []
        for k in keys:
            group = [f for f in facts if f["key"] == k["id"]]
            distinct = []
            for f in group:
                if all(f["value"] != d["value"] for d in distinct):
                    distinct.append(f)
            if len(distinct) < 2:
                continue
            a, b = distinct[0], distinct[1]
            refs = sorted({f["ref"] for f in group})
            opts = []
            for keep, other in ((a, b), (b, a)):
                ops = [PatchOp(mode="replace", section_ref=f["ref"], find=f["raw"], text=keep["raw"])
                       for f in group if f["value"] != keep["value"]]
                opts.append((f"{keep['raw']} (как в п. {keep['ref']})", ops))
            extra = k.get("extra_option")
            if extra and k["kind"] == "money":
                lo, hi = sorted([a["value"], b["value"]])
                text = extra["text"].format(min=fmt_money(lo), max=fmt_money(hi))
                ops = [PatchOp(mode="replace", section_ref=f["ref"], find=f["raw"], text=text) for f in group]
                opts.append((extra["label"].format(min=fmt_money(lo), max=fmt_money(hi)), ops))
            out.append(self.finding(
                severity=k.get("severity", "important"), key=k["id"], section_ref=a["ref"], refs=refs,
                quote=b["sentence"] if a["ref"] == b["ref"] else a["sentence"],
                text=f"{k['name']}: значения расходятся — {a['raw']} (п. {a['ref']}) и {b['raw']} (п. {b['ref']}).",
                question=f"{k['name']}: какое значение верное?",
                why=f"Разработчик выберет одно из значений наугад — расхождение между п. {a['ref']} и п. {b['ref']}.",
                options=make_options(opts),
            ))
        return out

    def extra_prompt(self, doc):
        rows = "\n".join(f"- {f['name']}: {f['raw']} (п. {f['ref']})" for f in getattr(self, "facts", []))
        return f"Таблица фактов, построенная кодом:\n{rows or '—'}\n\n"

    def summary(self, found):
        n = len(getattr(self, "facts", []))
        return f"Собрал таблицу из {n} фактов, нашёл {len(found)} противоречий" if found else f"Проверил {n} фактов — противоречий нет"
