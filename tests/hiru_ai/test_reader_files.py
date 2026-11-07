"""A PDF the document reader attaches reaches OpenAI as a Chat Completions `file` part (plan/2026-11-06f §4.5): the
agent runner adds it after the text, LangChain normalises it on the way in, and `ChatOpenAI` turns it back into OpenAI's
shape on the way out. Checked on the request body, so a LangChain upgrade that drops the file fails here."""
from __future__ import annotations

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from contracts.doc_read import CanonW, PieceRead
from contracts.doc_read_run import PieceAsk, piece_message
from hiru_ai.core.agents import build
from hiru_ai.core.llm import use_models
from hiru_ai.core.testing import ScriptedChatModel


def test_the_request_carries_the_text_then_the_pdf():
    ask = PieceAsk(filename="a.pdf", mode="pages", kind="episode", episode=1, title="", first_page=3, last_page=4,
                   first_line=1, last_line=9, text="", pdf_b64="JVBERi0xLjQK", roster="(none yet)")
    model = ScriptedChatModel(replies=[PieceRead(canon=CanonW(characters=[], locations=[], props=[]), episodes=[],
                                                 transcription=[]).model_dump()])
    with use_models(model):
        build("reader_episode").run(ask)
    body = ChatOpenAI(api_key=SecretStr("x"), model="m")._get_request_payload([model.calls[0][-1]])
    assert body["messages"][0]["content"] == [
        {"type": "text", "text": piece_message(ask)},
        {"type": "file", "file": {"file_data": "data:application/pdf;base64,JVBERi0xLjQK",
                                  "filename": "pages-3-4.pdf"}}]
