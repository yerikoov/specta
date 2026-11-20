"""Personal data never reaches a cloud model.

Before a request goes to Claude, ИИН/БИН, phone numbers, card numbers, IBAN and e-mails in the TZ, the prompts
and the tool results are replaced by stable tokens («[ИИН-1]»). The model reasons about «[ИИН-1]»; its answer
is un-masked before the agents use it, so quotes still match the document word for word.
Local models (LLM_PROVIDER=local) and the rule engine see the original text — it stays inside the network.
Disable with PII_MASK=0.
"""
from __future__ import annotations

import os
import re

PATTERNS = [
    ("IBAN", re.compile(r"\bKZ\d{2}[A-Z0-9]{16}\b")),
    ("КАРТА", re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?:[ -]?\d{1,3})?(?!\d)")),
    ("ИИН", re.compile(r"(?<!\d)\d{12}(?!\d)")),
    ("ТЕЛ", re.compile(r"(?<![\d+])(?:\+7|8)[\s(-]*7\d{2}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
]


def enabled() -> bool:
    return os.getenv("PII_MASK", "1").lower() not in ("0", "false", "no", "off")


class Masker:
    """One masker per agent call: the same value always gets the same token, both ways."""

    def __init__(self) -> None:
        self.to_token: dict[str, str] = {}
        self.to_value: dict[str, str] = {}

    def mask(self, text):
        if not isinstance(text, str) or not text:
            return text
        for kind, rx in PATTERNS:
            text = rx.sub(lambda m: self._token(kind, m.group(0)), text)
        return text

    def _token(self, kind: str, value: str) -> str:
        if value not in self.to_token:
            n = sum(1 for t in self.to_value if t.startswith(f"[{kind}-")) + 1
            tok = f"[{kind}-{n}]"
            self.to_token[value], self.to_value[tok] = tok, value
        return self.to_token[value]

    def unmask(self, text: str) -> str:
        if not self.to_value or not isinstance(text, str):
            return text
        return re.sub(r"\[(?:IBAN|КАРТА|ИИН|ТЕЛ|EMAIL)-\d+\]", lambda m: self.to_value.get(m.group(0), m.group(0)), text)

    def unmask_obj(self, obj):
        if isinstance(obj, str):
            return self.unmask(obj)
        if isinstance(obj, dict):
            return {k: self.unmask_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.unmask_obj(v) for v in obj]
        return obj

    @property
    def count(self) -> int:
        return len(self.to_token)
