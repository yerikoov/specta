"""AGENTS config: the whole team is described here as data.

tier:     fast | strong  (which LLM model the agent uses when a key is set)
tools:    rag | facts_table | regex | web_search | none
always:   always-on pipeline agents (not chosen by the Dispatcher)
triggers: regex keywords the Dispatcher looks for to decide if the agent is needed
emotions: overrides of DEFAULT_EMOTIONS (state -> emotion)
"""
from __future__ import annotations

DEFAULT_EMOTIONS = {
    "idle": "neutral",
    "working": "curious",
    "found": "surprised",
    "blocked": "angry",
    "done": "happy",
    "skipped": "sleepy",
    "failed": "sad",
    "good": "wink",
}

AGENTS: dict[str, dict] = {
    "parser": {
        "name": "Парсер", "role": "Чтение документа", "line": "Разбирает файл на пронумерованные разделы.",
        "shape": "drop", "color": "#6aa8ff", "tier": "fast", "tools": ["none"], "always": True,
    },
    "dispatcher": {
        "name": "Диспетчер", "role": "Собирает команду", "line": "Решает, какие эксперты нужны именно этому ТЗ.",
        "shape": "ball", "color": "#8b5cf6", "tier": "fast", "tools": ["none"], "always": True,
    },
    "completeness": {
        "name": "Полнота", "role": "Разделы шаблона", "line": "Сверяет ТЗ с шаблоном и ищет пропущенные разделы.",
        "shape": "hexagon", "color": "#7cf5c8", "tier": "fast", "tools": ["rag"], "criterion": "completeness",
        "triggers": [r"."], "reason": "сверка с шаблоном «{template}»",
    },
    "ambiguity": {
        "name": "Ясность", "role": "Размытые формулировки", "line": "Ловит «быстро», «удобно» и «по возможности».",
        "shape": "heart", "color": "#f5b592", "tier": "fast", "tools": ["regex"], "criterion": "clarity",
        "triggers": [r"должн", r"необходимо", r"требует"], "reason": "в тексте {n} требований — проверю формулировки",
    },
    "contradictions": {
        "name": "Согласованность", "role": "Противоречия", "line": "Строит таблицу фактов и ищет конфликты чисел и дат.",
        "shape": "clover", "color": "#fb6adc", "tier": "strong", "tools": ["facts_table"], "criterion": "consistency",
        "triggers": [r"\d"], "reason": "в таблице фактов {n} значений (лимиты, сроки, комиссии)",
    },
    "testability": {
        "name": "Тестируемость", "role": "Проверяемость и тесты", "line": "Проверяет, можно ли каждое требование протестировать.",
        "shape": "bumps", "color": "#31c943", "tier": "strong", "tools": ["none"], "criterion": "testability",
        "triggers": [r"должн", r"цел"], "reason": "нужно убедиться, что требования проверяемы, и предложить тесты",
    },
    "regulatory": {
        "name": "Комплаенс", "role": "KYC/AML, ПДн, PCI DSS", "line": "Сверяет ТЗ с локальной базой регуляторных требований.",
        "shape": "hexagon", "color": "#a48bff", "tier": "strong", "tools": ["rag", "web_search"], "criterion": "compliance",
        "triggers": [r"перевод", r"платеж|платёж", r"карт", r"кредит", r"депозит", r"\bсч[её]т"],
        "reason": "ТЗ описывает движение денег ({hits})",
        "skip_reason": "нет финансовых операций",
    },
    "security": {
        "name": "Безопасность", "role": "Информационная безопасность", "line": "Шифрование, аутентификация, журналы, антифрод.",
        "shape": "drop", "color": "#a8f0ff", "tier": "strong", "tools": ["rag"], "criterion": "compliance",
        "triggers": [r"персональн", r"парол", r"\botp\b", r"код подтвержд", r"авториз", r"аутентиф", r"биометр", r"карт"],
        "reason": "в ТЗ есть пользовательские данные и подтверждение операций ({hits})",
        "skip_reason": "нет упоминаний пользовательских данных и авторизации",
    },
    "integrations": {
        "name": "Интеграции", "role": "Внешние системы", "line": "Проверяет протоколы, таймауты и ошибки интеграций.",
        "shape": "cloud", "color": "#f5a524", "tier": "fast", "tools": ["none"], "criterion": "completeness",
        "triggers": [r"интегр", r"\bapi\b", r"процессинг", r"шлюз", r"\bабс\b", r"внешн\w* систем"],
        "reason": "упомянуты внешние системы ({hits})",
        "skip_reason": "внешние системы не упоминаются",
    },
    "nfr": {
        "name": "НФТ", "role": "Нефункциональные требования", "line": "Доступность, нагрузка, восстановление — в цифрах.",
        "shape": "ball", "color": "#2fd6b5", "tier": "fast", "tools": ["none"], "criterion": "clarity",
        "triggers": [r"нагрузк", r"производител", r"доступ(ен|на|ност)", r"надёжн|надежн", r"отказ", r"\bsla\b", r"время отклика", r"быстр"],
        "reason": "в ТЗ есть нефункциональные требования ({hits})",
        "skip_reason": "нет нефункциональных требований",
    },
    "critic": {
        "name": "Критик", "role": "Отсеивает ложные срабатывания", "line": "Перепроверяет каждое замечание и убирает лишнее.",
        "shape": "heart", "color": "#ff7a8a", "tier": "strong", "tools": ["none"], "always": True,
        "emotions": {"found": "wink"},
    },
    "clarifier": {
        "name": "Уточнитель", "role": "Вопросы к вам", "line": "Собирает вопросы, ранжирует и задаёт по 3–5 за раз.",
        "shape": "cloud", "color": "#b9a6ff", "tier": "fast", "tools": ["none"], "always": True,
        "emotions": {"working": "curious", "blocked": "angry"},
    },
    "reporter": {
        "name": "Репортёр", "role": "Итоговый отчёт", "line": "Считает оценку, пишет тест-кейсы и улучшенное ТЗ.",
        "shape": "clover", "color": "#31c943", "tier": "fast", "tools": ["none"], "always": True,
    },
}

# order in which specialist agents are shown / dispatched
SPECIALISTS = ["completeness", "ambiguity", "contradictions", "testability", "regulatory", "security", "integrations", "nfr"]

# template sections that are fully covered by a specialist agent (Critic removes the generic "missing section")
COVERED_BY = {"security": "security", "compliance": "regulatory", "integrations": "integrations"}


def emotion(agent: str, state: str) -> str:
    return AGENTS.get(agent, {}).get("emotions", {}).get(state, DEFAULT_EMOTIONS.get(state, "neutral"))


def public_agents() -> list[dict]:
    keys = ("name", "role", "line", "shape", "color", "tier", "tools")
    return [{"id": k, **{x: v[x] for x in keys}} for k, v in AGENTS.items()]
