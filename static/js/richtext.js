// Agent messages → readable text: «(1) … (2) …» and «- …» become lists, «п. 3.4/5.2» become clickable clause
// chips, «цитаты» are highlighted, **жирный** is bold, the closing remark gets its own paragraph.
// The text is HTML-escaped first, so nothing the model writes can inject markup.
import { escapeHtml as esc } from "./chain.js";

const REF = /п\.\s?(\d{1,2}(?:\.\d{1,2}){0,3}(?:\s?[/,и–-]\s?\d{1,2}(?:\.\d{1,2}){0,3})*)/g;

function inline(s) {
  return s
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/«([^«»]{1,160})»/g, '<span class="rt-q">«$1»</span>')
    .replace(REF, (_, refs) => refs.split(/\s?[/,и–-]\s?/).filter(Boolean)
      .map((r) => `<button class="ref-chip rt-ref" data-ref="${r.trim()}">п. ${r.trim()}</button>`).join(""))
    // «(п. 3.4/5.2)» → just the chips, without the brackets around them
    .replace(/\(\s*((?:<button class="ref-chip rt-ref"[^>]*>[^<]*<\/button>)+)\s*\)/g, '<span class="rt-refs">$1</span>');
}

// «Главные проблемы: (1) …; (2) …; (3) …. Итог.» → {intro, items, outro}
function enumerated(text) {
  const marks = [...text.matchAll(/(?:^|[\s:;,])\((\d{1,2})\)\s|(?:^|[\s:;])(\d{1,2})\)\s/g)];
  const nums = marks.map((m) => +(m[1] || m[2]));
  if (marks.length < 2 || nums[0] !== 1 || nums.some((n, i) => n !== i + 1)) return null;
  const starts = marks.map((m) => m.index + m[0].indexOf(m[1] || m[2]) - (m[1] ? 1 : 0));
  const intro = text.slice(0, starts[0]).replace(/[\s:;,]+$/, "");
  const items = starts.map((st, i) => text.slice(st, starts[i + 1] ?? text.length).replace(/^\(?\d{1,2}\)\s*/, "").replace(/[;,]\s*$/, "").trim());
  // a final remark glued to the last item («…не ограничена. Замечание по п. 3.3 снимаю…»)
  let outro = "";
  const last = items[items.length - 1];
  const cut = last.search(/[.!?]\s+(?=[А-ЯЁA-Z«])/);
  if (cut > 0 && last.length - cut > 25) { outro = last.slice(cut + 1).trim(); items[items.length - 1] = last.slice(0, cut + 1).trim(); }
  return { intro, items: items.map((x) => x.replace(/[;.]$/, "")), outro };
}

function block(par) {
  const lines = par.split("\n").map((l) => l.trim()).filter(Boolean);
  if (lines.length > 1 && lines.filter((l) => /^([-•*]|\d{1,2}[.)])\s/.test(l)).length >= lines.length - 1) {
    const head = /^([-•*]|\d{1,2}[.)])\s/.test(lines[0]) ? "" : lines.shift();
    const ordered = /^\d/.test(lines[0]);
    const lis = lines.map((l) => `<li>${inline(l.replace(/^([-•*]|\d{1,2}[.)])\s+/, ""))}</li>`).join("");
    return `${head ? `<p>${inline(head)}</p>` : ""}<${ordered ? "ol" : "ul"} class="rt-list">${lis}</${ordered ? "ol" : "ul"}>`;
  }
  const flat = lines.join(" ");
  const e = enumerated(flat);
  if (e) {
    return `${e.intro ? `<p class="rt-lead">${inline(e.intro)}${/[:.]$/.test(e.intro) ? "" : ":"}</p>` : ""}
      <ol class="rt-list">${e.items.map((x) => `<li>${inline(x)}</li>`).join("")}</ol>${e.outro ? `<p class="rt-outro">${inline(e.outro)}</p>` : ""}`;
  }
  return `<p>${inline(flat)}</p>`;
}

export function richText(text) {
  const safe = esc(text || "");
  return safe.split(/\n{2,}/).map(block).join("");
}
