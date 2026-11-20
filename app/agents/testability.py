"""Testability: can each requirement be tested? + acceptance test generation."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..llm import LLMError, llm
from ..models import Document, Finding, PatchOp
from .base import BaseAgent, doc_for_prompt, iter_sentences, make_options

DIGIT = re.compile(r"\d")


class TestCase(BaseModel):
    id: str
    ref: str
    title: str
    given: str
    when: str
    then: str


class TestCases(BaseModel):
    tests: list[TestCase] = Field(default_factory=list)


class TestabilityAgent(BaseAgent):
    id = "testability"
    use_llm = True
    focus = "требования, которые невозможно проверить тестом: нет измеримого результата, нет условия, нет актора."

    def rules(self, doc: Document) -> list[Finding]:
        out, seen = [], set()
        for sec, sent in iter_sentences(doc):
            for rule in self.ctx["rules"]["untestable"]:
                if not re.search(rule["pattern"], sent, flags=re.I):
                    continue
                if rule.get("only_without_digits") and DIGIT.search(sent):
                    continue
                if (sec.ref, rule["id"]) in seen:
                    continue
                seen.add((sec.ref, rule["id"]))
                base = sent.rstrip(" .;")
                opts = [(o["label"], [PatchOp(mode="replace_sentence", section_ref=sec.ref, find=sent,
                                              pattern=rule["pattern"], text=o["text"].replace("{s}", base))])
                        for o in rule["options"]]
                out.append(self.finding(
                    severity=rule.get("severity", "important"), key=rule["id"], topic=rule.get("topic"),
                    section_ref=sec.ref, quote=sent,
                    text=f"Требование п. {sec.ref} нельзя проверить тестом. {rule['why']}",
                    question=f"Как проверить на приёмке п. {sec.ref}?", why=rule["why"],
                    options=make_options(opts),
                ))
        return out

    # ------------------------------------------------------------ test cases
    async def generate_tests(self, doc: Document) -> list[dict]:
        if not llm.mock:
            try:
                res = await llm.complete_json(
                    "Ты — QA-инженер банка. Сгенерируй приёмочные тест-кейсы (Дано/Когда/Тогда) по ТЗ. "
                    "По одному на каждое проверяемое требование, максимум 12. id формата TC-<номер пункта>.",
                    "Сгенерируй тест-кейсы по ТЗ выше.", TestCases, tier="fast", doc=doc_for_prompt(doc),
                    agent="testability", purpose="тест-кейсы")
                if res.tests:
                    return [t.model_dump() for t in res.tests]
            except LLMError:
                pass
        return heuristic_tests(doc)

    def summary(self, found):
        n = len(found)
        return f"{n} требований не проверяются тестом" if n else "Все требования проверяемы"


def heuristic_tests(doc: Document) -> list[dict]:
    tests = []
    for sec in doc.sections:
        if sec.level < 2 or not sec.text:
            continue
        t = sec.text.split("\n")[0]
        low = t.lower()
        title = t if len(t) < 110 else t[:107] + "…"
        num = re.search(r"(\d{1,3}(?:[\s ]\d{3})+|\d+)\s*(₸|тенге)", t)
        if "лимит" in low or "сумм" in low:
            val = num.group(0) if num else "значение лимита"
            given, when, then = ("Клиент идентифицирован, на счёте достаточно средств",
                                 f"Клиент выполняет операцию на сумму, превышающую {val} на 1 ₸",
                                 "Операция отклонена, показано сообщение о превышении лимита, деньги не списаны")
        elif "код" in low or "otp" in low:
            given, when, then = ("Клиент начал операцию и получил OTP",
                                 "Клиент вводит код после истечения срока действия",
                                 "Код отклонён, клиенту предложено запросить новый код")
        elif "комисси" in low:
            given, when, then = ("Тарифы настроены согласно ТЗ", "Клиент выполняет операцию на 10 000 ₸",
                                 "Комиссия рассчитана по тарифу и показана до подтверждения")
        elif "доступн" in low or "%" in low:
            given, when, then = ("Сервис работает в промышленной среде", "Мониторинг собирает метрики за месяц",
                                 "Доступность и время отклика не хуже значений из п. " + sec.ref)
        elif "уведомлен" in low or "push" in low:
            given, when, then = ("Операция выполнена успешно", "Проходит 10 секунд",
                                 "Клиент получил уведомление о результате")
        elif "должн" in low or "может" in low or "выполня" in low or "получа" in low:
            given, when, then = (f"Выполнены предусловия п. {sec.ref}", "Пользователь выполняет описанное действие",
                                 f"Результат соответствует требованию: «{title}»")
        else:
            continue
        tests.append({"id": f"TC-{sec.ref}", "ref": sec.ref, "title": title, "given": given, "when": when, "then": then})
    return tests[:14]
