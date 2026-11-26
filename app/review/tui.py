"""Terminal animation for `specta check`.

The agents are chafa renders of the same glass characters as on the website, stored as .ans files
(app/review/term_art/<agent>/<frame>.ans, built by scripts/build_term_art.py). A scripted timeline plays them:

  * entering agent — grows in (in0 → in1 → neutral) while the previous one dissolves away;
  * the eyes morph from neutral to the agent's own emotion (m0…m3, same easing as the site);
  * while it works the gaze drifts left and right (gL2…gR2, same amplitude as the site's cursor-following) with
    pauses, and every few seconds the agent blinks — a fixed, eased rhythm, never random jitter.

Next to the picture: who the agent is, what it does now, the team checklist and a progress bar.
Falls back to plain log lines when the output is not a terminal (CI, redirect) or with --no-anim."""
from __future__ import annotations

import asyncio
import sys
import time
from functools import lru_cache
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..agents.registry import AGENTS

ART_DIR = Path(__file__).with_name("term_art")
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
STEPS = [("read", "parser", "Чтение документа"), ("slice", "dispatcher", "Нарезка на требования"),
         ("rules", "ambiguity", "Проверки правилами"), ("analyse", "testability", "Каждое требование · ISO 29148 §5.2.5"),
         ("set", "contradictions", "Набор целиком · §5.2.6, IEEE 830"), ("critic", "critic", "Критик: цитаты и обоснованность"),
         ("questions", "clarifier", "Вопросы аналитику"), ("verdict", "reporter", "Итог и отчёт")]
STAGE_IDX = {s: i for i, (s, _, _) in enumerate(STEPS)}

ENTER = 0.9            # seconds: grow in + eyes morph
GAZE = [(0.0, 0), (1.1, -1), (1.7, -2), (2.4, -2), (3.0, -1), (3.7, 0), (4.5, 1), (5.1, 2), (5.9, 2), (6.5, 1), (7.2, 0)]
GAZE_LOOP = 8.4
BLINK_EVERY, BLINK_LEN = 3.6, 0.22


@lru_cache(maxsize=None)
def _ans(agent: str, frame: str) -> list[str]:
    f = ART_DIR / agent / f"{frame}.ans"
    if not f.exists():
        f = ART_DIR / "dispatcher" / f"{frame}.ans"
    return f.read_text().rstrip("\n").split("\n")


def have_art() -> bool:
    return (ART_DIR / "dispatcher" / "m3.ans").exists()


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


def _gaze_pos(t: float) -> float:
    """Smooth interpolation through the scripted gaze keyframes: -2 (far left) … +2 (far right)."""
    t = t % GAZE_LOOP
    keys = GAZE + [(GAZE_LOOP, 0)]
    for (t0, a), (t1, b) in zip(keys, keys[1:]):
        if t0 <= t < t1:
            return a + (b - a) * _ease((t - t0) / (t1 - t0))
    return 0.0


def frame_name(age: float) -> str:
    """Which stored frame to show `age` seconds after the agent took the stage: entrance → morph → gaze / blink."""
    if age < ENTER:
        k = age / ENTER
        if k < 0.22:
            return "in0"
        if k < 0.42:
            return "in1"
        return ["m0", "m1", "m2", "m3"][min(3, int((k - 0.42) / 0.58 * 4))]
    t = age - ENTER
    if (t % BLINK_EVERY) > BLINK_EVERY - BLINK_LEN:
        return "blink"
    g = _gaze_pos(t)
    if abs(g) < 0.5:
        return "m3"
    return ("gL2" if g < -1.5 else "gL1") if g < 0 else ("gR2" if g > 1.5 else "gR1")


class ReviewUI:
    def __init__(self, filename: str, model: str, console: Console | None = None, animate: bool = True):
        self.console = console or Console(highlight=False)
        self.animate = (animate and self.console.is_terminal and self.console.color_system in ("truecolor", "256")
                        and self.console.width >= 100 and have_art())      # the picture (40 cols) + the text need ~100
        self.filename, self.model = filename, model
        self.agent, self.prev, self.agent_t0, self.prev_t0 = "parser", None, time.time(), 0.0
        self.stage, self.text = "read", ""
        self.done_stages: set[str] = set()
        self.t0 = time.time()
        self._live = None
        self._task = None

    # ---- events from the pipeline
    def event(self, agent: str, stage: str, text: str) -> None:
        if stage in STAGE_IDX:
            for s, _, _ in STEPS[:STAGE_IDX[stage]]:
                self.done_stages.add(s)
        if stage == "done":
            self.done_stages = {s for s, _, _ in STEPS}
        if agent != self.agent and (ART_DIR / agent).exists():
            self.prev, self.prev_t0 = self.agent, time.time()
            self.agent, self.agent_t0 = agent, time.time()
        self.stage, self.text = stage, text
        if not self.animate:
            name = AGENTS.get(agent, {}).get("name", agent)
            self.console.print(f"[dim]{time.time() - self.t0:5.1f}s[/] [bold]{name}[/] · {text}")

    # ---- drawing
    def _picture(self) -> Text:
        now = time.time()
        lines = _ans(self.agent, frame_name(now - self.agent_t0))
        if self.prev and now - self.prev_t0 < 0.35:          # the previous agent dissolves away from the bottom up
            old = _ans(self.prev, "m3")
            keep = (now - self.prev_t0) / 0.35
            lines = [(o if (i / max(1, len(lines) - 1)) > keep else n) for i, (o, n) in enumerate(zip(old, lines))]
        return Text.from_ansi("\n".join(lines))

    def _render(self):
        a = AGENTS.get(self.agent, {})
        color = a.get("color", "#a48bff")
        spin = SPIN[int(time.time() * 12) % len(SPIN)]
        info = Text()
        info.append(f"{a.get('name', self.agent)}\n", style=f"bold {color}")
        info.append(f"{a.get('role', '')}\n", style="grey70")
        info.append(f"{a.get('line', '')}\n\n", style="italic grey50")
        info.append(f"{spin} ", style=color)
        info.append(f"{self.text}\n\n", style="white")
        for s, ag, label in STEPS:
            if s in self.done_stages:
                info.append("  ✓ ", style="green")
                info.append(f"{label}\n", style="grey62")
            elif s == self.stage:
                info.append(f"  {spin} ", style=AGENTS.get(ag, {}).get("color", "white"))
                info.append(f"{label}\n", style="bold white")
            else:
                info.append("  · ", style="grey35")
                info.append(f"{label}\n", style="grey35")
        grid = Table.grid(padding=(0, 3))
        grid.add_column(no_wrap=True)
        grid.add_column(vertical="middle")
        grid.add_row(self._picture(), info)
        n, bar_w = len(self.done_stages), 34
        fill = round(bar_w * n / len(STEPS))
        foot = Text()
        foot.append("█" * fill, style="green")
        foot.append("░" * (bar_w - fill), style="grey23")
        foot.append(f"  {n}/{len(STEPS)}  ·  {time.time() - self.t0:4.0f} с  ·  {self.model}", style="grey50")
        return Panel(Group(grid, Text(""), foot), title=f"[bold]Specta[/] · проверка «{self.filename}»", title_align="left",
                     border_style="grey30", padding=(1, 2))

    async def _loop(self):
        while True:
            self._live.update(self._render())
            await asyncio.sleep(1 / 20)

    def __enter__(self):
        if self.animate:
            self._live = Live(self._render(), console=self.console, refresh_per_second=20, transient=True)
            self._live.__enter__()
            self._task = asyncio.get_event_loop().create_task(self._loop())
        else:
            self.console.print(f"[bold]Specta[/] · проверка «{self.filename}» · {self.model}")
        return self

    def __exit__(self, *exc):
        if self._task:
            self._task.cancel()
        if self._live:
            self._live.__exit__(*exc)
        return False

    def summary(self, rev, out_path: str) -> None:
        from .standards import SEVERITY
        alld = rev.req_defects + rev.set_defects
        sev = {k: sum(1 for d in alld if d.severity == k) for k in SEVERITY}
        v = rev.verdict or {}
        body = Text()
        body.append("Отчёт готов → ", style="grey70")
        body.append(f"{out_path}\n\n", style="bold green")
        body.append(f"Требований: {len(rev.requirements)}   ", style="white")
        body.append(f"нарушений: {len(alld)}   ", style="white")
        body.append(f"●{sev['critical']} ", style="red")
        body.append(f"●{sev['major']} ", style="dark_orange")
        body.append(f"●{sev['minor']}\n", style="grey62")
        body.append(f"Разработку начинать: {v.get('development', '—')}   ·   тестирование: {v.get('testing', '—')}\n", style="bold")
        n = rev.usage.get("calls", 0) + rev.usage.get("cache_hits", 0)
        body.append(f"{rev.finished - rev.started:.0f} с · обращений к модели: {n} · {rev.model}\n", style="grey50")
        body.append("Тот же документ в браузере, ответ сразу правит текст: uvicorn app.main:app → http://localhost:8000", style="grey70")
        grid = Table.grid(padding=(0, 3))
        if self.animate:
            grid.add_column(no_wrap=True)
            grid.add_column(vertical="middle")
            grid.add_row(Text.from_ansi("\n".join(_ans("reporter", "m3"))), body)
        else:
            grid.add_column()
            grid.add_row(body)
        self.console.print(Panel(grid, title="[bold]Specta[/] · готово", title_align="left", border_style="green", padding=(1, 2)))


def is_tty() -> bool:
    return sys.stdout.isatty()
