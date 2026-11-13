"""The lab's results page: the thread as a chat, each turn with what happened behind it, and the clips before and after."""

from __future__ import annotations

import html
import json
from typing import Any

from coverage import Coverage

Row = dict[str, Any]
CSS = """
:root{--bg:#f6f6f8;--surface:#fff;--ink:#17181f;--muted:#5d606f;--line:#d7d8e0;--code:#eef0f5;--llm:#c8102e;
--store:#0f7a72;--store-t:#e3f3f1;--hl:#d98c00;--hl-t:#fff4dc;--warn:#b4410f;--warn-t:#fdece3;--on:#fff}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121319;--surface:#1b1d25;--ink:#eceef4;
--muted:#a2a6b6;--line:#343745;--code:#252834;--llm:#ff5a6e;--store:#4cc7bb;--store-t:#15322f;--hl:#ffb52e;
--hl-t:#3b2d10;--warn:#ff8a57;--warn-t:#3a2216;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#121319;--surface:#1b1d25;--ink:#eceef4;--muted:#a2a6b6;--line:#343745;--code:#252834;
--llm:#ff5a6e;--store:#4cc7bb;--store-t:#15322f;--hl:#ffb52e;--hl-t:#3b2d10;--warn:#ff8a57;--warn-t:#3a2216;color-scheme:dark}
*{box-sizing:border-box}body{background:var(--bg);color:var(--ink);font:15px/1.55 "IBM Plex Sans","Segoe UI",system-ui,sans-serif;
padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:32px 64px;margin:0}
.wrap{max-width:980px;margin:0 auto;display:flex;flex-direction:column;gap:28px}
h1,h2{font-family:"Space Grotesk","Segoe UI",sans-serif;margin:0;text-wrap:balance}h1{font-size:34px}h2{font-size:22px}
p{margin:0;max-width:72ch}.muted{color:var(--muted)}code{font-family:"IBM Plex Mono",Consolas,monospace;font-size:.88em}
.stats{display:flex;flex-wrap:wrap;gap:8px}.stats span{border:1px solid var(--line);border-radius:4px;padding:3px 10px;font-size:13px;background:var(--surface)}
.turn{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:start;border-top:1px solid var(--line);padding-top:18px}
.chat{display:flex;flex-direction:column;gap:8px;min-width:0}
.me{align-self:flex-end;background:var(--ink);color:var(--surface);border-radius:14px 14px 4px 14px;padding:8px 12px;max-width:92%}
.act{align-self:flex-end;background:var(--hl-t);border:1px solid var(--hl);border-radius:999px;padding:2px 12px;font-size:13px;font-weight:600}
.zora{background:var(--surface);border:1px solid var(--line);border-radius:14px 14px 14px 4px;padding:10px 12px;max-width:96%}
.who{font-size:12px;color:var(--muted);display:flex;gap:6px;align-items:center}.av{width:18px;height:18px;border-radius:50%;background:var(--llm);color:var(--on);display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700}
ul{margin:6px 0 0;padding-left:18px}li{font-size:13.5px}
.chg{background:var(--code);border-radius:6px;padding:6px 10px;margin-top:8px;font-family:"IBM Plex Mono",Consolas,monospace;font-size:12px;list-style:none}
.card{border:1.5px solid var(--hl);border-radius:10px;padding:8px 12px;margin-top:8px;background:var(--hl-t)}
.card b{font-size:13px}.btn{display:inline-block;font-size:12px;font-weight:600;border-radius:6px;padding:2px 10px;margin-right:6px;border:1px solid var(--line);background:var(--surface)}
.btn.y{background:var(--llm);color:var(--on);border-color:var(--llm)}
.opt{border:1px solid var(--line);border-radius:8px;padding:6px 10px;margin-top:6px;background:var(--surface);font-size:13px}
.zora.b{border-style:dashed}.opt.drop{opacity:.6}.sys{align-self:center;font-size:12px;border-radius:999px;padding:2px 10px;background:var(--store-t);color:var(--store)}
.side{font-size:13px;display:flex;flex-direction:column;gap:6px;min-width:0}
.side .k{font-family:"IBM Plex Mono",Consolas,monospace;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.lane{display:inline-block;font-family:"IBM Plex Mono",Consolas,monospace;font-size:12px;border:1px solid var(--line);border-radius:4px;padding:0 6px}
.bad{color:var(--warn)}.calls{color:var(--muted);font-size:12px}
details summary{cursor:pointer;color:var(--muted);font-size:12px}pre{white-space:pre-wrap;font-size:11.5px;background:var(--code);padding:8px;border-radius:6px;overflow-x:auto;margin:4px 0 0}
table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}.scroll{overflow-x:auto}
td.ch{background:var(--hl-t)}
@media (max-width:760px){.turn{grid-template-columns:1fr}}
"""


def e(x: Any) -> str:
    return html.escape(str(x))


def _ul(items: list[str], cls: str = "") -> str:
    return f'<ul class="{cls}">' + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>" if items else ""


def _turn(r: Row) -> str:
    msg = r["message"]
    left = [f'<div class="act">{e(msg)}</div>' if msg.startswith("[") else f'<div class="me">{e(msg)}</div>']
    if r.get("stopped"):
        left.append(f'<div class="zora bad">Stopped: {e(r["stopped"])}</div>')
        return f'<section class="turn"><div class="chat">{"".join(left)}</div><div></div></section>'
    body = e(r.get("reply", ""))
    if r.get("card"):
        body += ('<div class="card"><b>Needs your OK</b>' + _ul(r["card"]["lines"]) +
                 '<div style="margin-top:6px"><span class="btn y">Accept</span><span class="btn">Reject</span></div></div>')
    if r.get("done"):
        body += _ul(r["done"], "chg")
    for p in r.get("proposals") or []:
        tag = f' <span class="bad">(not shown: {e(p["dropped"])})</span>' if p.get("dropped") else ""
        risky = f' <span class="muted">needs your OK: {e("; ".join(p["risky"]))}</span>' if p.get("risky") else ""
        body += (f'<div class="opt{" drop" if p.get("dropped") else ""}"><b>{e(p["label"])}</b>{tag}{risky}'
                 + _ul(p["lines"]) + ('' if p.get("dropped") else '<span class="btn y">Use this</span>') + "</div>")
    if r.get("status"):
        left.append(f'<div class="sys">{e(r["status"])}</div>')
    models = r.get("reply_models") or []
    a_name = f"Zora · {models[0]}" if models else "Zora"
    left.append(f'<div class="zora"><div class="who"><span class="av">Z</span>{a_name}</div>{body}</div>')
    if r.get("reply_b"):
        left.append(f'<div class="zora b"><div class="who"><span class="av">Z</span>Compare · {e(models[1] if len(models) > 1 else "")}</div>'
                    f'{e(r["reply_b"])}</div>')
    side = [f'<div><span class="k">{e(r["slot"])}</span> <span class="lane">{e(r["lane"])}</span> '
            f'{"saved, revision " + str(r["revision"]) if r.get("saved") else "nothing saved"}'
            f' <span class="calls">· {len(r.get("calls") or [])} calls · turn ${r.get("dollars", 0):.5f}{" (" + e(r["conductor"]["by_code"] and "read by code") + ")" if (r.get("conductor") or {}).get("by_code") else ""} · compare voice ${r.get("dollars_compare", 0):.5f}</span></div>']
    c = r.get("conductor")
    if c:
        ops = [json.dumps(o, ensure_ascii=False) for o in c.get("ops") or []]
        tasks = [f"{t.get('instruction')} [{', '.join(t.get('writes') or [])}] on {t.get('shots') or 'any'}"
                 for t in c.get("tasks") or []]
        side.append(f'<div><span class="k">Conductor</span> lane {e(c["lane"])}, confidence {c["confidence"]}'
                    + (_ul(["op " + o for o in ops]) if ops else "") + (_ul(["task " + t for t in tasks]) if tasks else "")
                    + (f'<div class="muted">cannot: {e(c["cannot"])}</div>' if c.get("cannot") else "") + "</div>")
    if r.get("applied"):
        side.append('<div><span class="k">Applied</span>' + _ul([f"{a['by']}: {a['text']}" for a in r["applied"]]) + "</div>")
    for key, label, cls in (("kernel_notes", "Code moved lines", ""), ("refused", "Refused", "bad"),
                            ("team_refused", "Team's work refused", "bad"), ("undelivered", "Asked for, not done", "bad"),
                            ("reported", "Reported", ""), ("notes", "Author's note", ""),
                            ("guard_cut", "Reply guard cut (A)", "bad"), ("guard_cut_b", "Reply guard cut (B)", "bad")):
        if r.get(key):
            side.append(f'<div class="{cls}"><span class="k">{label}</span>{_ul(r[key])}</div>')
    if r.get("card"):
        side.append(f'<div><span class="k">Risk rule</span>{_ul(r["card"]["reasons"])}</div>')
    if r.get("repair"):
        rep = r["repair"]
        side.append(f'<div><span class="k">Repair</span>{_ul(["fault: " + f for f in rep["faults"]])}'
                    f'<div class="muted">{"dropped (not better)" if rep.get("dropped") else "left: " + str(len(rep["left"]))}</div></div>')
    if r.get("memory"):
        side.append(f'<div><span class="k">Remembered</span> {e(r["memory"])}</div>')
    if r.get("author"):
        side.append("<details><summary>Author's raw answers</summary><pre>" +
                    e(json.dumps(r["author"], indent=1, ensure_ascii=False)[:6000]) + "</pre></details>")
    if r.get("calls"):
        side.append('<div class="calls">' + " · ".join(
            f"{x['role']} {x.get('model', '')} {x.get('effort', '')} ${x.get('dollars', 0):.4f}"
            + (" (cache)" if x.get("cached") else "") for x in r["calls"]) + "</div>")
    return (f'<section class="turn"><div class="chat">{"".join(left)}</div>'
            f'<div class="side">{"".join(side)}</div></section>')


def _table(start: Coverage, end: Coverage) -> str:
    old = {c.h: c for c in start.clips}
    rows = []
    for c in end.clips:
        o = old.get(c.h)

        def cell(now: str, was: str | None) -> str:
            changed = was is not None and was != now
            return f'<td class="ch">{e(now)} <span class="muted">(was {e(was)})</span></td>' if changed else f"<td>{e(now)}</td>"

        perf = ", ".join(ln.lid for ln in end.performs(c.h))
        rows.append("<tr>" + f"<td>{end.code(c.h)}</td><td>{e(c.slate or 'new')}</td>"
                    + cell(f"{c.priority} {c.role}", f"{o.priority} {o.role}" if o else None)
                    + cell(c.size, o.size if o else None) + cell(f"{c.take_s} s", f"{o.take_s} s" if o else None)
                    + f"<td>b{c.first}" + (f"-b{c.last - 1}" if c.last - 1 > c.first else "") + f"</td><td>{e(perf)}</td>"
                    + cell(c.cine("angle") or "-", (o.cine("angle") or "-") if o else None)
                    + f"<td>{e(c.why[:90])}</td></tr>")
    gone = [f"{start.code(h)} {o.slate}" for h, o in old.items() if end.clip(h) is None]
    return ('<div class="scroll"><table><thead><tr><th>Shot</th><th>Slate</th><th>Role</th><th>Size</th><th>Take</th>'
            '<th>Blocks</th><th>Performs</th><th>Angle</th><th>Why</th></tr></thead><tbody>' + "".join(rows)
            + "</tbody></table></div>" + (f'<p class="muted">Removed: {e(", ".join(gone))}</p>' if gone else ""))


def page(name: str, start: Coverage, end: Coverage, records: list[Row], spent: float) -> str:
    calls = sum(len(r.get("calls") or []) for r in records)
    saved = sum(1 for r in records if r.get("saved"))
    cards = sum(1 for r in records if r.get("card"))
    return (f"<title>Zora Rows Lab {e(name)}</title>\n<style>{CSS}</style>\n<div class=\"wrap\"><header>"
            f"<p class=\"muted\">plan/2026-11-12d phase 0 · Hiru Short Combined 2 · {e(start.heading)}</p>"
            f"<h1>Zora on the shot rows: {e(name)}</h1><p>Zora edits Raphael's clips directly, with no planner. "
            "Left: the chat as the director would see it. Right: what happened behind each turn.</p></header>"
            f'<div class="stats"><span>{len(records)} turns</span><span>{calls} model calls</span>'
            f"<span>{saved} saves</span><span>{cards} Accept/Reject cards</span><span>${spent:.4f} spent</span>"
            f"<span>takes {start.total_s()} s → {end.total_s()} s</span></div>"
            + "".join(_turn(r) for r in records)
            + f"<h2>The clips at the end</h2>{_table(start, end)}</div>")
