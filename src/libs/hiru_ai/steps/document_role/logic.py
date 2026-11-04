"""What a document IS, by rules: free, deterministic, right for the obvious cases (a screenplay full of scene
headings is a script). The model is asked only when the rules are unsure (`LLM_THRESHOLD`) and a key is configured; that
is the `role_classifier` agent, and the system keeps these rules' guess when it fails. A low-confidence role is shown to
a person to confirm (contracts.documents.ROLE_CONFIRM_THRESHOLD): detection never has the last word.
"""
from __future__ import annotations

# Ported from services/doc_ingest/doc_ingest/engine/roles.py (plan/2026-11-03 Phase 6).
import re
from dataclasses import dataclass

from contracts.documents import DocumentRole

R = DocumentRole

SCENE_HEADING = re.compile(
    r"^\s*(?:\d+[.)]?\s+)?(?:INT|EXT|INT\.?/EXT|I/E|EXT\.?/INT)[.\s]"  # INT. HARBOUR - NIGHT
    r"|^\s*SCENE\s+\d+"  # SCENE 12
    r"|^\s*දර්ශනය\s*\d+",  # Sinhala "scene N"
    re.IGNORECASE,
)
CHARACTER_CUE = re.compile(r"^\s*[A-Z][A-Z0-9 .'\-]{1,28}(?:\s*\((?:V\.O\.|O\.S\.|CONT'D|O\.C\.)\))?\s*$")
CANON_CODE = re.compile(r"\b[CLP]\d{2}\b")
EPISODE_MARK = re.compile(r"^\s*#*\s*(?:episode|ep\.?)\s*\d+|^\s*#*\s*කථාංගය\s*\d+", re.IGNORECASE)
BIBLE_HEADINGS = re.compile(
    r"^\s*#*\s*(?:premise|logline|tone|themes?|world|setting|format|series overview|characters?)\b",
    re.IGNORECASE,
)

FILENAME_HINTS: dict[DocumentRole, tuple[str, ...]] = {
    R.BIBLE: ("bible", "world", "series-overview", "series overview"),
    R.SCRIPT: ("script", "screenplay", "teleplay", "draft", ".fountain", "තිර"),
    R.CANON_INDEX: ("canon", "index", "cast", "characters", "locations", "props"),
    R.OUTLINE: ("outline", "synopsis", "treatment", "beat-sheet", "beat sheet", "episodes"),
    R.NOTES: ("notes", "memo", "feedback", "comments"),
}

LLM_THRESHOLD = 0.8  # below this, ask the model (when one is configured)


@dataclass(frozen=True)
class RoleGuess:
    role: DocumentRole
    confidence: float
    reason: str
    source: str  # "rules" | "model"


def detect_by_rules(filename: str, text: str) -> RoleGuess:
    lines = [ln for ln in text.split("\n") if ln.strip()]
    n = max(len(lines), 1)
    scenes = sum(1 for ln in lines if SCENE_HEADING.match(ln))
    cues = sum(1 for ln in lines if CHARACTER_CUE.match(ln))
    codes = len(CANON_CODE.findall(text))
    episodes = sum(1 for ln in lines if EPISODE_MARK.match(ln))
    bible_heads = sum(1 for ln in lines if BIBLE_HEADINGS.match(ln))

    scores: dict[DocumentRole, float] = dict.fromkeys(R, 0.0)
    reasons: dict[DocumentRole, str] = {}
    if scenes >= 2:
        scores[R.SCRIPT] += 0.55 + min(0.3, scenes / 40)
        reasons[R.SCRIPT] = f"{scenes} scene headings"
        if cues / n > 0.05:
            scores[R.SCRIPT] += 0.1
    if codes >= 3:
        scores[R.CANON_INDEX] += 0.5 + min(0.3, codes / 60)
        reasons[R.CANON_INDEX] = f"{codes} canon codes (C01, L02 …)"
    if episodes >= 3:
        scores[R.OUTLINE] += 0.5 + min(0.25, episodes / 40)
        reasons[R.OUTLINE] = f"{episodes} episode headings"
    if bible_heads >= 2:
        scores[R.BIBLE] += 0.45 + min(0.3, bible_heads / 15)
        reasons[R.BIBLE] = f"{bible_heads} bible-style sections (premise, tone, characters …)"

    name = filename.lower()
    for role, hints in FILENAME_HINTS.items():
        if any(h in name for h in hints):
            scores[role] += 0.3
            reasons[role] = (reasons.get(role, "") + "; " if role in reasons else "") + "file name"

    role, score = max(scores.items(), key=lambda kv: kv[1])
    if score <= 0:
        return RoleGuess(R.OTHER, 0.2, "no clear signals", "rules")
    runner_up = sorted(scores.values(), reverse=True)[1]
    confidence = min(0.95, score) - (0.2 if score - runner_up < 0.15 else 0)
    return RoleGuess(role, round(max(confidence, 0.1), 2), reasons[role], "rules")
