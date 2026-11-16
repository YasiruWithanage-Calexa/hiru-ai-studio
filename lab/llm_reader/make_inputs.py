"""Build the lab's documents and their expected answers (free, no model).

The two real PDFs go through the PRODUCT's extractor (`doc_ingest.engine.extract`), so the model reads exactly the text
the build would. Four more layouts are made from v2's text to prove the reading does not depend on one layout. This
file is test-fixture code: it may know the layout of the documents it writes; the reader never sees it.

    python lab/llm_reader/make_inputs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "src" / "services" / "doc_ingest")]

from doc_ingest.engine.extract import extract  # noqa: E402

DOWNLOADS = Path.home() / "Downloads"
INPUTS, GOLD = HERE / "inputs", HERE / "gold"

TITLES = [
    [1, 1, "KASUN'S EVERYDAY LIFE"], [1, 2, "ANUDI ARRIVES"], [1, 3, "THE UNEXPECTED ENCOUNTER"],
    [1, 4, "A CONVERSATION THAT CHANGES EVERYTHING"],
    [2, 1, "A FAMILIAR FACE"], [2, 2, "THE FATHER NOTICES"], [2, 3, "THE CONFRONTATION"],
    [2, 4, "KASUN'S DETERMINATION AND THE BIG OPPORTUNITY"],
    [3, 1, "THE STRUGGLE"], [3, 2, "ANUDI'S SUPPORT"], [3, 3, "AN UNEXPECTED OFFER"], [3, 4, "THE CHOICE"],
    [3, 5, "A DREAM COMES TRUE"],
]
V1 = [(25, 30), (20, 25), (15, 20), (40, 50), (30, 35), (20, 25), (35, 40), (55, 65), (30, 35), (20, 25), (35, 40),
      (30, 35), (45, 55)]
V2_MIN = [0.46, 0.38, 0.29, 0.75, 0.54, 0.38, 0.63, 1, 0.54, 0.38, 0.63, 0.54, 0.83]
WORDS = ["ONE", "TWO", "THREE"]


PDFS = {"A_v1_pdf": "Api_Denna_Script.pdf", "B_v2_pdf": "Api_Denna_Script_v2.pdf"}


def pdf_lines(name: str, stem: str, *, actual_text: bool = True) -> list[str]:
    """The PDF's text: by default with /ActualText honoured (`actualtext.py`, the fix for the damaged Sinhala);
    `actual_text=False` is today's product extractor (pypdf `extract_text`)."""
    data = (DOWNLOADS / name).read_bytes()
    pages: dict[int, list[str]] = {}
    if actual_text:
        from pypdf import PdfReader

        from actualtext import page_text

        for n, page in enumerate(PdfReader(DOWNLOADS / name).pages, 1):
            pages[n] = page_text(page).split("\n")
    else:
        for ln in extract(data, name, "application/pdf").lines:
            pages.setdefault(int(ln.page or 0), []).append(ln.text)
    (INPUTS / f"{stem}.pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=0), encoding="utf-8")
    return [t for n in sorted(pages) for t in pages[n]]


def scenes(seconds: list[tuple[float, float] | None]) -> list[dict]:
    return [{"episode": e, "number": n, "title": t,
             "low": s[0] if s else None, "high": s[1] if s else None} for (e, n, t), s in zip(TITLES, seconds, strict=True)]


def gold(kind: str, verdict: str, sc: list[dict], *, damaged: bool, note: str) -> dict:
    return {"story": kind == "story", "verdict": verdict, "episodes": 3 if sc else 0, "scenes": sc,
            "main": ["kasun", "anudi"] if sc else [], "damaged_text": damaged, "note": note}


def screenplay(v2: list[str]) -> tuple[list[str], list[tuple[float, float]]]:
    """v2 in another layout: PART headings, numbered scene headings with the place and the length in brackets, the
    title on the next line, upper-case speaker cues above the words, running page headers, no Location/Duration lines."""
    out: list[str] = []
    secs: list[tuple[float, float]] = []
    i, part, page = 0, 0, 1
    while i < len(v2):
        ln = v2[i]
        if ln.startswith("EPISODE "):
            part += 1
            out.append(f"PART {WORDS[part - 1]}: {ln.split('—', 1)[1].strip().title()}")
        elif ln.startswith("SCENE "):
            num = int(ln.split()[1])
            title = ln.split("—", 1)[1].strip()
            place = v2[i + 1].split(":", 1)[1].strip()
            minutes = float(v2[i + 2].split(":", 1)[1].split()[0])
            s = round(minutes * 60)
            secs.append((s, s))
            out += [f"{num}. {place.upper()}  [approx. {s} sec]", f"({title.title()})"]
            i += 3
            continue
        elif ln.startswith("END EPISODE"):
            out.append("— end of part —")
        elif ":" in ln[:40] and ln.split(":", 1)[1].strip().startswith('"') and ln.split(":", 1)[0][:1].isupper():
            who, words = ln.split(":", 1)
            who = who.replace("(over the phone)", "(V.O.)").strip().upper()
            out += [who, words.strip().strip('"').strip()]
        else:
            out.append(ln)
        if len(out) >= page * 45:
            page += 1
            out.append(f"Api Denna · shooting draft 3 · page {page}")
        i += 1
    return out, secs


def no_lengths(v2: list[str]) -> list[str]:
    out = []
    for ln in v2:
        if ln.startswith("Duration:"):
            continue
        if ln.startswith("One evening, Anudi is talking"):
            out.append("This short moment should play for about half a minute on screen.")
        out.append(ln)
    return out


def glued(v2: list[str]) -> list[str]:
    """The fault seen in the product: the line before two SCENE 04 headings glued to the heading."""
    out: list[str] = []
    for ln in v2:
        if ln.startswith("SCENE 04") and out and out[-1].endswith((".", "!")) and not out[-1].startswith("Duration"):
            if "daughter" in out[-1] or "father." in out[-1]:
                out[-1] = out[-1] + ln
                continue
        out.append(ln)
    return out


def not_a_story(v2: list[str]) -> list[str]:
    return v2[:10] + [
        "CAST & CREW NOTES",
        "Kasun — 28, runs a small food three-wheeler in Colombo. Casting: TBC",
        "Anudi — 26, works in an office in Colombo. Casting: TBC",
        "Anudi's father — 58, a businessman. Casting: TBC",
        "Driver — 45. Casting: local",
        "BUDGET (draft)",
        "Three-wheeler rental — Rs. 15,000 per day",
        "Location permits, Colombo roadside — Rs. 40,000",
        "Restaurant set dressing — Rs. 120,000",
        "SHOOT DAYS: 6 (3 night)",
        "Contact the line producer for the call sheet.",
    ]


def main() -> None:
    INPUTS.mkdir(exist_ok=True)
    GOLD.mkdir(exist_ok=True)
    v1, v2 = pdf_lines(PDFS["A_v1_pdf"], "A_v1_pdf"), pdf_lines(PDFS["B_v2_pdf"], "B_v2_pdf")
    v2_secs = [(m * 60, m * 60) for m in V2_MIN]
    docs = {
        "A_v1_pdf": (v1, gold("story", "go", scenes(V1), damaged=False,
                                note="the person's v1: 'Estimated Duration: 25–30 seconds' on its own line")),
        "B_v2_pdf": (v2, gold("story", "go", scenes(v2_secs), damaged=False,
                                note="the person's v2: 'Duration: 0.46 minutes' on its own line")),
    }
    # The other layouts are made from B's CLEAN transcription (run.py writes it): text with no PDF behind it must be
    # clean, or the build stops at Gate 0.
    clean_file = INPUTS / "B_v2_pdf.clean.txt"
    if clean_file.exists():
        clean = clean_file.read_text(encoding="utf-8").rstrip("\n").split("\n")
        sp, sp_secs = screenplay(clean)
        nl_secs: list[tuple[float, float] | None] = [None] * 13
        nl_secs[5] = (30, 30)
        docs |= {
            "C_other_layout": (sp, gold("story", "go", scenes(sp_secs), damaged=False,
                                        note="PART headings, '1. PLACE [approx. 28 sec]', title below, CUES, page headers")),
            "D_no_lengths": (no_lengths(clean), gold("story", "needs_input", scenes(nl_secs), damaged=False,
                                                     note="no lengths except E02 S02 in a sentence: 'about half a minute'")),
            "E_not_a_story": (not_a_story(clean), gold("not_story", "stop", [], damaged=False,
                                                       note="title page + cast list + budget: no story")),
            "F_glued_heading": (glued(clean), gold("story", "go", scenes(v2_secs), damaged=False,
                                                   note="v2 with two SCENE 04 headings glued to the line before")),
            # today's product extractor (pypdf, /ActualText ignored): text that really is damaged, with no PDF to fix it
            "G_damaged_no_pdf": ([ln.text for ln in extract((DOWNLOADS / PDFS["B_v2_pdf"]).read_bytes(), "x.pdf",
                                                            "application/pdf").lines],
                                 gold("story", "stop", scenes(v2_secs), damaged=True,
                                      note="v2 through today's extractor (damaged Sinhala), no PDF behind it")),
        }
    else:
        print("no inputs/B_v2_pdf.clean.txt yet: run `run.py live <run> --yes --only B` first for C-G")
    for name, (lines, g) in docs.items():
        (INPUTS / f"{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (GOLD / f"{name}.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{name}: {len(lines)} lines, {len(g['scenes'])} expected scenes, expected verdict {g['verdict']}")


if __name__ == "__main__":
    main()
