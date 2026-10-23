from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from api.routers import documents as documents_router
from api.workers import task_manager
from tests.api.conftest import World

SCRIPT = "INT. HOUSE - DAY\n\nNIMAL\nඅම්මේ, මම ආපහු ආවා.\n".encode()


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(task_manager, "_fire_local",
                        lambda url, payload: calls.append({"url": url, **payload.model_dump(mode="json")}))
    return calls


def _upload(world: World, user, name="ep1.fountain", data=SCRIPT, production=None):
    pid = production or world.production
    return world.client.post(f"/v1/productions/{pid}/documents",
                             files={"file": (name, data, "application/octet-stream")},
                             headers=world.headers(user))


def test_upload_stores_file_creates_row_and_starts_ingest(world: World, fired: list[dict]):
    r = _upload(world, world.producer)
    assert r.status_code == 201, r.text
    body = r.json()
    doc = body["document"]
    assert doc["filename"] == "ep1.fountain" and doc["status"] == "uploaded"
    assert doc["mime_type"] == "text/plain" and doc["role_needs_confirmation"] is True
    (bucket, path), data = next(iter(world.repos.storage.objects.items()))  # type: ignore[attr-defined]
    assert bucket == "documents" and path.startswith(f"{world.production}/{doc['id']}/") and data == SCRIPT
    assert fired[0]["url"].endswith(":8202/") and fired[0]["state"] == {"document_id": doc["id"]}
    assert body["job_id"] == fired[0]["job_id"]


def test_file_url_is_a_ticket_not_a_storage_url(world: World, fired: list[dict]):
    url = _upload(world, world.producer).json()["document"]["file_url"]
    assert "/files/" in url and "supabase" not in url and "storage" not in url and "?dl=" in url


@pytest.mark.parametrize("role", ["writer", "crew", "reviewer"])
def test_roles_without_manage_documents_cannot_upload(world: World, fired: list[dict], role: str):
    assert _upload(world, getattr(world, role)).status_code == 403
    assert fired == []


def test_non_member_upload_is_404(world: World, fired: list[dict]):
    assert _upload(world, world.producer, production=world.other_production).status_code == 404


@pytest.mark.parametrize(("name", "data", "code"), [
    ("photo.jpg", b"\xff\xd8\xff", 415),
    ("notes.docx", b"PK\x03\x04", 415),
    ("noext", b"text", 415),
    ("fake.pdf", b"not a pdf", 422),
    ("binary.txt", b"\x00\x01\x02binary", 422),
    ("empty.md", b"", 422),
])
def test_upload_validation(world: World, fired: list[dict], name: str, data: bytes, code: int):
    assert _upload(world, world.producer, name=name, data=data).status_code == code
    assert world.repos.storage.objects == {}  # type: ignore[attr-defined]


def test_utf16_text_with_bom_is_allowed(world: World, fired: list[dict]):
    assert _upload(world, world.producer, name="u16.txt", data="නිමල්".encode("utf-16")).status_code == 201


def test_too_large_is_413(world: World, fired: list[dict], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(documents_router, "MAX_UPLOAD_BYTES", 10)
    assert _upload(world, world.producer, data=b"x" * 11).status_code == 413


def test_same_file_twice_is_one_document(world: World, fired: list[dict]):
    first = _upload(world, world.producer).json()
    again = _upload(world, world.director, name="copy.fountain")
    assert again.status_code == 200
    assert again.json()["duplicate"] is True and again.json()["document"]["id"] == first["document"]["id"]
    assert len(fired) == 1


def test_list_puts_documents_needing_a_role_first(world: World, fired: list[dict]):
    docs = world.repos.documents.rows  # type: ignore[attr-defined]
    base = {"production_id": str(world.production), "mime_type": "text/plain", "size_bytes": 1,
            "sha256": "x", "storage_path": "p", "status": "ready", "role_reason": "", "chunk_count": 0,
            "warnings": [], "error": None, "page_count": None, "char_count": None, "confirmed_role": None}
    now = datetime.now(UTC)
    for name, role, conf, age in [("sure.md", "bible", 0.9, 1), ("unsure.txt", "other", 0.3, 5),
                                  ("newest.md", "script", 0.95, 0)]:
        did = str(uuid4())
        docs[did] = {**base, "id": did, "filename": name, "detected_role": role, "role_confidence": conf,
                     "created_at": (now - timedelta(minutes=age)).isoformat(), "updated_at": now.isoformat()}
    names = [d["filename"] for d in world.client.get(f"/v1/productions/{world.production}/documents",
                                                     headers=world.headers(world.reviewer)).json()]
    assert names == ["unsure.txt", "newest.md", "sure.md"]


def test_confirming_script_role_reingests(world: World, fired: list[dict]):
    doc = _upload(world, world.producer, name="notes.txt", data=b"Some notes").json()["document"]
    world.repos.documents.rows[doc["id"]].update(status="ready", detected_role="notes",  # type: ignore[attr-defined]
                                                 role_confidence=0.5)
    url = f"/v1/productions/{world.production}/documents/{doc['id']}"
    r = world.client.patch(url, json={"role": "script"}, headers=world.headers(world.director))
    assert r.status_code == 200 and r.json()["document"]["effective_role"] == "script"
    assert r.json()["document"]["role_needs_confirmation"] is False
    assert r.json()["job_id"] is not None and len(fired) == 2
    r = world.client.patch(url, json={"role": "script"}, headers=world.headers(world.director))
    assert r.json()["job_id"] is None  # no change in chunking, nothing to redo


def test_writer_cannot_confirm_roles(world: World, fired: list[dict]):
    doc = _upload(world, world.producer).json()["document"]
    r = world.client.patch(f"/v1/productions/{world.production}/documents/{doc['id']}",
                           json={"role": "bible"}, headers=world.headers(world.writer))
    assert r.status_code == 403


def test_reingest_refuses_while_processing(world: World, fired: list[dict]):
    doc = _upload(world, world.producer).json()["document"]
    world.repos.documents.rows[doc["id"]]["status"] = "processing"  # type: ignore[attr-defined]
    r = world.client.post(f"/v1/productions/{world.production}/documents/{doc['id']}/reingest",
                          headers=world.headers(world.producer))
    assert r.status_code == 409


def test_delete_removes_row_and_file(world: World, fired: list[dict]):
    doc = _upload(world, world.producer).json()["document"]
    r = world.client.delete(f"/v1/productions/{world.production}/documents/{doc['id']}",
                            headers=world.headers(world.producer))
    assert r.status_code == 204
    assert world.repos.documents.rows == {} and world.repos.storage.objects == {}  # type: ignore[attr-defined]


def test_document_of_another_production_is_404(world: World, fired: list[dict]):
    doc = _upload(world, world.admin, production=world.other_production).json()["document"]
    r = world.client.get(f"/v1/productions/{world.production}/documents/{doc['id']}",
                         headers=world.headers(world.admin))
    assert r.status_code == 404


def test_upload_with_a_role_confirms_it_from_the_start(world: World, fired: list[dict]):
    r = world.client.post(f"/v1/productions/{world.production}/documents",
                          files={"file": ("bible.md", b"# Bible\n\nA harbour town.\n", "text/markdown")},
                          data={"role": "bible"}, headers=world.headers(world.producer))
    assert r.status_code == 201, r.text
    doc = r.json()["document"]
    assert doc["confirmed_role"] == "bible" and doc["effective_role"] == "bible"
    assert doc["role_needs_confirmation"] is False
    assert len(fired) == 1  # one ingest, started with the role already set


def test_upload_with_an_unknown_role_is_rejected(world: World, fired: list[dict]):
    r = world.client.post(f"/v1/productions/{world.production}/documents",
                          files={"file": ("bible.md", b"# Bible\n", "text/markdown")},
                          data={"role": "banana"}, headers=world.headers(world.producer))
    assert r.status_code == 422 and fired == []
