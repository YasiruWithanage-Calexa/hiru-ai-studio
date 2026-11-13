"""The Sable lab's page: each message with today's Sable and the lightweight editor side by side."""

from __future__ import annotations

import html
import json
from typing import Any

Row = dict[str, Any]
CSS = """
:root{--bg:#f6f6f8;--surface:#fff;--ink:#17181f;--muted:#5d606f;--line:#d7d8e0;--code:#eef0f5;--a:#6b4fd8;--a-t:#efeafd;
--b:#0f7a72;--b-t:#e3f3f1;--hl:#d98c00;--hl-t:#fff4dc;--warn:#b4410f;--on:#fff}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121319;--surface:#1b1d25;--ink:#eceef4;
--muted:#a2a6b6;--line:#343745;--code:#252834;--a:#a993ff;--a-t:#2a2340;--b:#4cc7bb;--b-t:#15322f;--hl:#ffb52e;
--hl-t:#3b2d10;--warn:#ff8a57;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#121319;--surface:#1b1d25;--ink:#eceef4;--muted:#a2a6b6;--line:#343745;--code:#252834;
--a:#a993ff;--a-t:#2a2340;--b:#4cc7bb;--b-t:#15322f;--hl:#ffb52e;--hl-t:#3b2d10;--warn:#ff8a57;color-scheme:dark}
*{box-sizing:border-box}body{background:var(--bg);color:var(--ink);font:15px/1.55 "IBM Plex Sans","Segoe UI",system-ui,sans-serif;
margin:0;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:32px 64px}
.wrap{max-width:1100px;margin:0 auto;display:flex;flex-direction:column;gap:22px}h1,h2{font-family:"Space Grotesk","Segoe UI",sans-serif;margin:0}
h1{font-size:32px}p{margin:0;max-width:76ch}.muted{color:var(--muted)}
.totals{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.tot{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px 14px}.tot b{font-size:22px;font-family:"Space Grotesk",sans-serif}
.tot.t{border-top:3px solid var(--a)}.tot.l{border-top:3px solid var(--b)}
.msg{border-top:1px solid var(--line);padding-top:14px;display:flex;flex-direction:column;gap:10px}
.me{align-self:flex-start;background:var(--ink);color:var(--surface);border-radius:14px 14px 14px 4px;padding:6px 12px;font-weight:500}
.arms{display:grid;grid-template-columns:1fr 1fr;gap:12px}.arm{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px;min-width:0}
.arm.t{border-left:4px solid var(--a)}.arm.l{border-left:4px solid var(--b)}
.tag{font-size:11px;font-family:"IBM Plex Mono",Consolas,monospace;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
.reply{font-size:14px;white-space:pre-wrap}.cost{font-family:"IBM Plex Mono",Consolas,monospace}
ul{margin:0;padding-left:18px;font-size:12.5px}.card{border:1.5px solid var(--hl);background:var(--hl-t);border-radius:8px;padding:6px 10px;font-size:12.5px}
.chg{background:var(--code);border-radius:6px;padding:6px 10px;font-family:"IBM Plex Mono",Consolas,monospace;font-size:12px;list-style:none}
.skip{color:var(--muted);font-size:13px;font-style:italic}.bad{color:var(--warn)}
details summary{cursor:pointer;color:var(--muted);font-size:12px}pre{white-space:pre-wrap;font-size:11.5px;background:var(--code);padding:8px;border-radius:6px;margin:4px 0 0;overflow-x:auto}
@media (max-width:760px){.arms{grid-template-columns:1fr}}
"""


def e(x: Any) -> str:
    return html.escape(str(x))


def _ul(items: list[str], cls: str = "") -> str:
    return f'<ul class="{cls}">' + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>" if items else ""


def _today(r: Row | None) -> str:
    if r is None:
        return '<div class="arm t"><div class="tag"><span>Today\'s Sable</span></div><div class="skip">not run</div></div>'
    if r.get("skipped") or r.get("stopped"):
        return (f'<div class="arm t"><div class="tag"><span>Today\'s Sable</span></div><div class="skip">'
                f'{e(r.get("skipped") or r.get("stopped"))}</div></div>')
    models = sorted({str(c.get("model")) for c in r.get("calls") or []})
    cards = "".join(f'<div class="card"><b>{e(c.get("kind"))}</b> {e(c.get("summary") or c.get("title") or "")}'
                    f'{_ul([json.dumps(o, ensure_ascii=False)[:160] for o in c.get("ops") or []])}</div>'
                    for c in r.get("cards") or [])
    calls = " · ".join(f"{c.get('phase')} {c.get('model')} ${c.get('dollars', 0):.4f}" for c in r.get("calls") or [])
    return (f'<div class="arm t"><div class="tag"><span>Today\'s Sable · {e(", ".join(models))}</span>'
            f'<span class="cost">${r.get("dollars", 0):.5f} · {len(r.get("calls") or [])} calls · {r.get("seconds")} s'
            f'</span></div><div class="reply">{e(r.get("reply") or "(no reply)")}</div>{cards}'
            + (f'<div class="bad">error: {e(r["error"])}</div>' if r.get("error") else "")
            + (f"<details><summary>steps and calls</summary><pre>{e(' / '.join(r.get('statuses') or []))}\n{e(calls)}"
               "</pre></details>") + "</div>")


def _light(r: Row | None) -> str:
    if r is None:
        return '<div class="arm l"><div class="tag"><span>Lightweight editor</span></div><div class="skip">not run</div></div>'
    if r.get("stopped"):
        return f'<div class="arm l"><div class="tag"><span>Lightweight editor</span></div><div class="skip">{e(r["stopped"])}</div></div>'
    how = "read by code" if r.get("by_code") else r.get("lane", "")
    body = f'<div class="reply">{e(r.get("reply") or "")}</div>'
    if r.get("card"):
        body += '<div class="card"><b>Needs your OK</b>' + _ul(r["card"]["lines"]) + "</div>"
    if r.get("done"):
        body += _ul(r["done"], "chg")
    for k, label in (("refused", "Refused"), ("reported", "Heads-up"), ("guard_cut", "Guard cut")):
        if r.get(k):
            body += f'<div class="{"bad" if k != "reported" else "muted"}" style="font-size:12.5px">{label}:{_ul(r[k])}</div>'
    calls = " · ".join(f"{c.get('role')} {c.get('model')} ${c.get('dollars', 0):.5f}" for c in r.get("calls") or [])
    return (f'<div class="arm l"><div class="tag"><span>Lightweight editor · {e(how)}'
            f'{" · " + e(r.get("status")) if r.get("status") else ""}</span><span class="cost">${r.get("dollars", 0):.5f}'
            f' · {len(r.get("calls") or [])} calls</span></div>{body}'
            + (f'<details><summary>calls</summary><pre>{e(calls)}</pre></details>' if calls else "") + "</div>")


def _sum(records: list[Row] | None) -> tuple[float, int, int]:
    rs = [r for r in records or [] if not r.get("skipped") and not r.get("stopped")]
    return sum(r.get("dollars", 0) for r in rs), sum(len(r.get("calls") or []) for r in rs), len(rs)


def page(name: str, today: list[Row] | None, light: list[Row] | None) -> str:
    seen: set[str] = set()  # run 1 shared one card store across turns: show a card only on the turn that made it
    for r in today or []:
        fresh = []
        for c in r.get("cards") or []:
            key = json.dumps(c, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                fresh.append(c)
        r["cards"] = fresh
    t_by = {r["slot"]: r for r in today or []}
    l_by = {r["slot"]: r for r in light or []}
    slots = list(dict.fromkeys([*(r["slot"] for r in light or []), *(r["slot"] for r in today or [])]))
    msgs = {r["slot"]: r["message"] for r in (light or []) + (today or [])}
    td, tc, tn = _sum(today)
    ld, lc, ln = _sum(light)
    head = (f"<title>Sable Light Lab {e(name)}</title>\n<style>{CSS}</style>\n<div class=\"wrap\"><header>"
            "<p class=\"muted\">Hiru Short Combined 2 · Scene 03 · 20 Raphael clips · no database</p>"
            f"<h1>Sable as a lightweight shot editor: {e(name)}</h1><p>The same messages to today's Sable (its real code) "
            "and to the lightweight editor built from the Zora lab, side by side.</p></header>"
            f'<div class="totals"><div class="tot t">Today\'s Sable<br><b>${td:.4f}</b><br><span class="muted">{tn} '
            f'turns · {tc} model calls · ${(td / tn if tn else 0):.4f} a turn</span></div><div class="tot l">'
            f'Lightweight editor<br><b>${ld:.4f}</b><br><span class="muted">{ln} turns · {lc} model calls · '
            f'${(ld / ln if ln else 0):.4f} a turn</span></div></div>')
    rows = "".join(f'<section class="msg"><div class="me">{e(msgs[s])}</div><div class="arms">{_today(t_by.get(s))}'
                   f"{_light(l_by.get(s))}</div></section>" for s in slots)
    return head + rows + "</div>"
