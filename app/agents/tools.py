"""Tools the agents can call through Claude tool use.

The TZ itself is in every agent's (cached) system prompt; tools give access to what is NOT in the text:
the regulatory knowledge base, the computed facts table, the template checklist, and precise lookups.
Local tools are plain Python over local data — deterministic and free. The two web tools (web_search,
read_page) use free sources without API keys (see app.research) and only when the local KB is not enough.
"""
from __future__ import annotations

import inspect
import json
import re
from typing import Callable

from .. import research
from ..kb import load_kb, retrieve
from ..models import Document
from ..parsing import load_rules, load_template, sentences
from .contradictions import facts_table

Tool = dict  # {"name", "description", "input_schema", "fn"}


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _search_kb(doc: Document, query: str) -> str:
    hits = retrieve(query, k=3) or []
    out = []
    for d in hits:
        checks = [{"title": c.get("title"), "question": c.get("question"), "why": c.get("why")} for c in d.get("checks", [])][:6]
        out.append({"source": d.get("title") or d["file"], "summary": d["body"][:600], "checks": checks})
    return json.dumps(out or [{"note": "в базе знаний ничего не найдено"}], ensure_ascii=False)


def _get_facts(doc: Document) -> str:
    facts = facts_table(doc, load_rules()["fact_keys"])
    by_key: dict[str, list] = {}
    for f in facts:
        by_key.setdefault(f["name"], []).append({"п.": f["ref"], "значение": f["raw"]})
    return json.dumps(by_key or {"note": "числовых фактов (лимиты, сроки, комиссии) в ТЗ нет"}, ensure_ascii=False)


def _template_checklist(doc: Document) -> str:
    tpl = load_template()
    rows = []
    for t in tpl["sections"]:
        rows.append({"раздел": t["name"], "обязательный": bool(t.get("required")),
                     "есть в ТЗ": bool(doc.by_template(t["key"])), "что должно быть": t.get("hint", "")})
    return json.dumps(rows, ensure_ascii=False)


def _search_tz(doc: Document, query: str) -> str:
    words = [w for w in re.findall(r"[а-яёa-z0-9]{3,}", query.lower())]
    hits = []
    for sec in doc.sections:
        for s in sentences(sec.text or ""):
            low = s.lower()
            score = sum(1 for w in words if w[:5] in low)
            if score:
                hits.append((score, sec.ref, s))
    hits.sort(key=lambda h: -h[0])
    return json.dumps([{"п.": r, "текст": s} for _, r, s in hits[:6]] or [{"note": "в ТЗ не упоминается"}], ensure_ascii=False)


def _get_section(doc: Document, ref: str) -> str:
    sec = next((s for s in doc.sections if s.ref == ref.strip()), None)
    return json.dumps({"п.": sec.ref, "заголовок": sec.title, "текст": sec.text} if sec else {"error": f"пункта {ref} нет"}, ensure_ascii=False)


async def _web_search(doc: Document, query: str, official: bool) -> str:
    return await research.search(query, official)


async def _read_page(doc: Document, url: str, focus: str) -> str:
    return await research.read(url, focus)


TOOLS: dict[str, Tool] = {
    "web_search": {"name": "web_search", "fn": _web_search,
                   "description": "Бесплатный веб-поиск. Только если в базе знаний (search_kb) нет нужной нормы или надо "
                                  "уточнить номер, название или редакцию закона/правила. official=true — только официальные "
                                  "источники РК (adilet.zan.kz, nationalbank.kz, gov.kz). В запросе — только общая тема "
                                  "нормы, без названий, цифр и данных из ТЗ клиента.",
                   "input_schema": _schema({"query": {"type": "string", "description": "например «закон о платежах РК идентификация клиента»"},
                                            "official": {"type": "boolean"}}, ["query", "official"])},
    "read_page": {"name": "read_page", "fn": _read_page,
                  "description": "Открыть страницу из результатов web_search и получить только фрагменты по теме focus.",
                  "input_schema": _schema({"url": {"type": "string"}, "focus": {"type": "string", "description": "что искать на странице"}},
                                          ["url", "focus"])},
    "search_kb": {"name": "search_kb", "fn": _search_kb,
                  "description": "Поиск по базе знаний регуляторных требований РК (KYC/AML, ПДн, PCI DSS, НБ РК, ИБ). "
                                 "Возвращает источники и обязательные проверки.",
                  "input_schema": _schema({"query": {"type": "string", "description": "о чём требование, например «идентификация клиента»"}}, ["query"])},
    "get_facts": {"name": "get_facts", "fn": _get_facts,
                  "description": "Таблица числовых фактов ТЗ (лимиты, комиссии, сроки, проценты) с пунктами — чтобы найти расхождения.",
                  "input_schema": _schema({}, [])},
    "template_checklist": {"name": "template_checklist", "fn": _template_checklist,
                           "description": "Чек-лист разделов шаблона ТЗ банка: какие обязательные разделы есть в документе, а каких нет.",
                           "input_schema": _schema({}, [])},
    "search_tz": {"name": "search_tz", "fn": _search_tz,
                  "description": "Найти все места в ТЗ, где упоминается тема (все пункты и фразы).",
                  "input_schema": _schema({"query": {"type": "string"}}, ["query"])},
    "get_section": {"name": "get_section", "fn": _get_section,
                    "description": "Точный текст пункта ТЗ по номеру, например «3.2».",
                    "input_schema": _schema({"ref": {"type": "string"}}, ["ref"])},
}

# which agent gets which tools (registry `tools`: rag | facts_table | regex | none)
BY_KIND = {"rag": ["search_kb", "template_checklist"], "facts_table": ["get_facts"], "web_search": ["web_search", "read_page"]}
COMMON = ["search_tz", "get_section"]


# what the agent should look up first — the data is not in the TZ text, so the agent can't guess it
HINTS = {
    "rag": "Сначала вызови search_kb по каждой регуляторной теме ТЗ (идентификация клиента, ПДн, карты, безопасность) "
           "и template_checklist — и только потом ищи пробелы: требования регулятора бери из базы знаний, а не по памяти.",
    "facts_table": "Сначала вызови get_facts и сравни значения одного и того же параметра в разных пунктах.",
    "web_search": "Веб-поиск (web_search → read_page) — только когда в базе знаний нет ответа или нужно подтвердить "
                  "точное название/номер нормы; не больше двух поисков; ссылайся на найденный источник.",
}


def _kinds(agent_cfg: dict) -> list[str]:
    return [k for k in agent_cfg.get("tools", []) if k != "web_search" or research.enabled()]


def tool_hint(agent_cfg: dict) -> str:
    return " ".join(HINTS[k] for k in _kinds(agent_cfg) if k in HINTS)


def tools_for(agent_cfg: dict) -> list[Tool]:
    names = [n for kind in _kinds(agent_cfg) for n in BY_KIND.get(kind, [])] + COMMON
    return [TOOLS[n] for n in dict.fromkeys(names)]


async def run_tool(name: str, args: dict, doc: Document) -> str:
    t = TOOLS.get(name)
    if not t:
        return json.dumps({"error": f"нет инструмента {name}"}, ensure_ascii=False)
    try:
        out = t["fn"](doc, **args)
        return await out if inspect.isawaitable(out) else out
    except TypeError as e:
        return json.dumps({"error": f"неверные аргументы: {e}"}, ensure_ascii=False)


def definitions(tools: list[Tool]) -> list[dict]:
    """Tool definitions for the Messages API (strict schemas, sorted for a stable cached prefix)."""
    return [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"], "strict": True}
            for t in sorted(tools, key=lambda t: t["name"])]
