"""Phase 1 end-to-end smoke test on the LOCAL stack: documents → doc_ingest → search.

Needs the same setup as smoke_local.py (Supabase, admin, API on :8000, functions running via
scripts/start-functions.ps1 — echo :8201 and doc_ingest :8202).

    python scripts/smoke_phase1.py you@hirutv.lk <admin password>
"""
from __future__ import annotations

import sys
import time
import uuid

import httpx
from _common import ROOT, Rest, load_env

load_env()
import os  # noqa: E402

SUPABASE = os.environ.get("SUPABASE__URL", "http://127.0.0.1:54321")
API = os.environ.get("API__PUBLIC_URL", "http://localhost:8000")
ANON = os.environ["SUPABASE__ANON_KEY"]
CORPUS = ROOT / "tests" / "fixtures" / "corpus"


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'' if ok else f'  -> {detail}'}")
    if not ok:
        sys.exit(1)


def sign_in(email: str, password: str) -> dict[str, str]:
    r = httpx.post(f"{SUPABASE}/auth/v1/token?grant_type=password", headers={"apikey": ANON},
                   json={"email": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def local_user(email: str, password: str, production_id: str, role: str) -> None:
    """Invite-then-create, the same path a real invite takes (the trigger applies the role)."""
    db = Rest()
    db.insert("invitations", {"email": email, "production_id": production_id, "production_role": role})
    r = db.c.post(f"{SUPABASE}/auth/v1/admin/users", headers=db.h,
                  json={"email": email, "password": password, "email_confirm": True})
    r.raise_for_status()


def main(admin_email: str, admin_password: str) -> None:
    admin = httpx.Client(base_url=API, headers=sign_in(admin_email, admin_password), timeout=30)
    pid = admin.post("/v1/productions", json={"title": f"Phase 1 smoke {uuid.uuid4().hex[:6]}",
                                              "orientation": "horizontal"}).json()["id"]
    tag = uuid.uuid4().hex[:6]
    producer_email, writer_email = f"producer-{tag}@hirutv.lk", f"writer-{tag}@hirutv.lk"
    local_user(producer_email, "local-producer-123", pid, "producer")
    local_user(writer_email, "local-writer-123", pid, "writer")
    producer = httpx.Client(base_url=API, headers=sign_in(producer_email, "local-producer-123"), timeout=30)
    writer = httpx.Client(base_url=API, headers=sign_in(writer_email, "local-writer-123"), timeout=30)
    check("producer invited through the trigger can see the production",
          producer.get(f"/v1/productions/{pid}").status_code == 200)

    docs = f"/v1/productions/{pid}/documents"
    w = writer.post(docs, files={"file": ("x.md", b"# hi\ntext", "text/markdown")})
    check("writer cannot upload (403)", w.status_code == 403, w.text)

    uploaded = {}
    for path in sorted(p for p in CORPUS.iterdir() if p.name != "README.md"):
        r = producer.post(docs, files={"file": (path.name, path.read_bytes(), "application/octet-stream")})
        check(f"upload {path.name}", r.status_code == 201, r.text)
        uploaded[path.name] = r.json()["document"]["id"]
    bad = producer.post(docs, files={"file": ("latin1.txt", "café crème".encode("latin-1"), "text/plain")})
    check("upload of a non-UTF-8 text file is accepted for reading", bad.status_code == 201, bad.text)
    dup = producer.post(docs, files={"file": ("again.md", (CORPUS / "harbour-lights-bible.md").read_bytes(),
                                              "text/markdown")})
    check("the same file twice is one document", dup.status_code == 200 and dup.json()["duplicate"], dup.text)

    deadline = time.time() + 120
    listing: list[dict] = []
    while time.time() < deadline:
        listing = producer.get(docs).json()
        if all(d["status"] in ("ready", "rejected", "failed") for d in listing):
            break
        time.sleep(1)
    by_name = {d["filename"]: d for d in listing}
    check("every fixture document is ready", all(by_name[n]["status"] == "ready" for n in uploaded),
          {n: by_name[n]["status"] for n in uploaded})
    check("roles detected", by_name["harbour-lights-ep01-script.fountain"]["detected_role"] == "script"
          and by_name["harbour-lights-canon-index.md"]["detected_role"] == "canon_index",
          {n: d["detected_role"] for n, d in by_name.items()})
    check("non-UTF-8 file rejected with a fix", by_name["latin1.txt"]["status"] == "rejected"
          and "UTF-8" in (by_name["latin1.txt"]["error"] or ""), by_name["latin1.txt"])
    check("files needing a role come first in the list", listing[0]["role_needs_confirmation"] is True)
    check("file links are API tickets", all("/files/" in d["file_url"] for d in listing))

    s = writer.post(f"/v1/productions/{pid}/search", json={"query": "Who wants to sell the family boat?"}).json()
    check("search answers from the production's documents, with a citation", bool(s["hits"])
          and s["hits"][0]["citation"]["filename"] in uploaded, s)
    print(f"      mode={s['mode']} top={s['hits'][0]['citation']['filename']} / {s['hits'][0]['heading']}")
    s = writer.post(f"/v1/productions/{pid}/search", json={"query": "බෝට්ටුව විකුණන්න එපා"}).json()
    check("Sinhala query finds the Sinhala line", "FRONT YARD" in s["hits"][0]["heading"], s["hits"][:1])
    s = writer.post(f"/v1/productions/{pid}/search",
                    json={"query": "when to use close-ups", "corpora": ["craft"]}).json()
    check("craft knowledge is searchable", s["hits"] and s["hits"][0]["citation"]["source"].endswith(".md"), s)
    t = writer.post("/v1/craft/techniques/search", json={"query": "make the location feel like a character"}).json()
    check("technique lookup by effect", t and t[0]["name"] == "Extreme Wide Shot", t[:1])

    notes_id = uploaded["director-notes.txt"]
    r = producer.patch(f"{docs}/{notes_id}", json={"role": "script"})
    check("confirming a different chunking role re-ingests", r.status_code == 200 and r.json()["job_id"], r.text)
    r = producer.delete(f"{docs}/{uploaded['harbour-lights-outline.txt']}")
    check("delete a document", r.status_code == 204)
    s = writer.post(f"/v1/productions/{pid}/search", json={"query": "hotel agent offers cash"}).json()
    check("deleted document no longer answers",
          all(h["citation"]["filename"] != "harbour-lights-outline.txt" for h in s["hits"]), s)

    other = admin.post("/v1/productions", json={"title": "Other", "orientation": "vertical"}).json()["id"]
    r = producer.post(f"/v1/productions/{other}/search", json={"query": "boat"})
    check("cannot search a production you are not on (404)", r.status_code == 404)
    print("phase 1 smoke test passed")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
