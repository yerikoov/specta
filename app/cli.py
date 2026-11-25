"""specta — command line: review a requirements document and write the report.

    specta check docs/requirements.pdf report.md
    python -m app.cli check docs/requirements.pdf report.md      (same, without installing)

The model comes from .env: GEMINI_API_KEY (free, Google AI Studio), ANTHROPIC_API_KEY, OPENAI_API_KEY,
DEEPSEEK_API_KEY or any OpenAI-compatible API (LLM_BASE_URL + LLM_MODEL). --provider forces one.
--offline runs the rule checks only (no model)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

FORMATS = (".pdf", ".docx", ".md", ".markdown", ".txt")


def _args(argv):
    p = argparse.ArgumentParser(prog="specta", description="Specta — ИИ-агент статической проверки требований (ISO/IEC/IEEE 29148, IEEE 830).")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="проверить документ и записать отчёт")
    c.add_argument("input", help="файл требований: .pdf, .docx, .md или .txt")
    c.add_argument("output", nargs="?", help="файл отчёта (.md); без него — reports/<имя>_report.md")
    c.add_argument("-o", "--output", dest="output_flag", help="то же, что второй аргумент")
    c.add_argument("--provider", choices=["gemini", "anthropic", "openai", "deepseek", "custom"],
                   help="LLM API: по умолчанию первый, чей ключ есть в .env")
    c.add_argument("--offline", action="store_true", help="без модели — только проверки правилами")
    c.add_argument("--json", dest="json_out", help="дополнительно сохранить результат в JSON")
    c.add_argument("--no-anim", action="store_true", help="без анимации (простой лог)")
    c.add_argument("--demo", action="store_true", help="показать анимацию агентов без модели: проверки правилами, с паузами")
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = _args(argv if argv is not None else sys.argv[1:])
    root = Path(__file__).resolve().parents[1]
    try:
        from dotenv import load_dotenv
        load_dotenv(root / ".env")
        load_dotenv()            # .env in the current directory, if any
    except ImportError:
        pass
    if a.demo:
        a.offline = True
    if a.offline:
        os.environ["LLM_PROVIDER"] = "rules"
    elif a.provider:
        os.environ["LLM_PROVIDER"] = a.provider
    os.environ.setdefault("SUPABASE_URL", "")     # the CLI never touches the website's database

    src = Path(a.input)
    if not src.exists():
        print(f"Файл не найден: {src}", file=sys.stderr)
        return 2
    if src.suffix.lower() not in FORMATS:
        print(f"Формат {src.suffix} не поддерживается: {', '.join(FORMATS)}", file=sys.stderr)
        return 2
    chosen = a.output_flag or a.output
    out = Path(chosen) if chosen else Path("reports") / f"{src.stem}_report.md"

    from rich.console import Console
    from .llm import llm
    from .review.pipeline import _model_line, run_review
    from .review.report import render
    from .review.tui import ReviewUI

    console = Console(highlight=False)
    if llm.mock and not a.offline:
        console.print("[bold red]Модель не настроена.[/] Нужен ключ LLM в файле [bold].env[/]:\n"
                      "  1. Ключ Claude (для сдачи он точнее): https://console.anthropic.com/settings/keys\n"
                      "     cp .env.example .env  и впишите  ANTHROPIC_API_KEY=…\n"
                      "     Бесплатно, слабее: https://aistudio.google.com/apikey  и  GEMINI_API_KEY=…\n"
                      "  2. Повторите команду.  (Без модели: добавьте --offline — только проверки правилами.)")
        return 3

    async def run():
        ui = ReviewUI(src.name, _model_line(not a.offline), console=console, animate=not a.no_anim)
        with ui:
            rev = await run_review(src.read_bytes(), src.name, on_event=ui.event, use_llm=not a.offline,
                                   pace=1.6 if a.demo else 0)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(rev), encoding="utf-8")
        if a.json_out:
            Path(a.json_out).write_text(rev.model_dump_json(indent=1), encoding="utf-8")
        ui.summary(rev, str(out))
        return rev

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("[yellow]Остановлено.[/]")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
