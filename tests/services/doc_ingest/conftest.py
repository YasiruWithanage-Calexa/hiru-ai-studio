from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "services" / "doc_ingest"))
CORPUS = ROOT / "tests" / "fixtures" / "corpus"


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF, one Helvetica text line per input line (ASCII only)."""
    objects: list[bytes] = []
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font_id = 3 + 2 * len(pages)
    for i, text in enumerate(pages):
        ops = ["BT /F1 11 Tf 50 780 Td 14 TL"]
        for line in text.split("\n"):
            esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"({esc}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode() if text else b""
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                       f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {4 + 2 * i} 0 R >>".encode())
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


class FakeOpenAI:
    """Just enough of the OpenAI SDK: chat.completions.create and embeddings.create."""

    def __init__(self, replies: list[dict[str, Any]] | None = None, fail_embed: bool = False) -> None:
        self.replies = list(replies or [])
        self.fail_embed = fail_embed
        self.chat_calls: list[dict[str, Any]] = []
        self.embed_calls: list[list[str]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _chat(self, **kwargs: Any) -> Any:
        self.chat_calls.append(kwargs)
        name = kwargs["response_format"]["json_schema"]["name"]
        if name == "chunk_headers":
            ords = [int(p.split('"')[1]) for p in kwargs["messages"][1]["content"].split("<passage ord=")[1:]]
            body = {"headers": [{"ord": o, "header": f"model header {o}"} for o in ords]}
        else:
            body = self.replies.pop(0) if self.replies else {"role": "notes", "confidence": 0.7, "reason": "x"}
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                                prompt_tokens_details=SimpleNamespace(cached_tokens=0))
        return SimpleNamespace(usage=usage,
                               choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(body)))])

    def _embed(self, *, model: str, input: list[str], dimensions: int) -> Any:
        if self.fail_embed:
            raise RuntimeError("embedding service down")
        self.embed_calls.append(input)
        data = [SimpleNamespace(index=i, embedding=[float(len(t) % 7)] * dimensions) for i, t in enumerate(input)]
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=10 * len(input)))
