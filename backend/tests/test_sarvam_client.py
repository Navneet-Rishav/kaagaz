"""SarvamProvider against a mocked HTTP transport: no real API calls."""

import base64
import json

import httpx
import pytest
from pydantic import BaseModel

from app.ai.base import AiError, ChatResult, complete_json, extract_json
from app.ai.sarvam import BASE_URL, SarvamProvider


def _provider(handler) -> SarvamProvider:
    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return SarvamProvider(api_key="k-test", client=client, sleep=lambda s: None, ocr_poll_s=0)


def _chat_ok(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
    )


def test_chat_sends_key_schema_and_parses_reply() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["key"] = req.headers["api-subscription-key"]
        seen["body"] = json.loads(req.content)
        return _chat_ok('{"ok": true}')

    r = _provider(handler).chat("classify", "sys", "user", {"name": "classify", "schema": {"type": "object"}})
    assert r.text == '{"ok": true}' and r.tokens == 10
    assert seen["key"] == "k-test"
    assert seen["body"]["model"] == "sarvam-105b"
    assert seen["body"]["response_format"]["type"] == "json_schema"
    assert "reasoning_effort" not in seen["body"]


def test_retries_429_and_5xx_then_succeeds() -> None:
    codes = iter([429, 503])
    calls = []

    def handler(req):
        calls.append(1)
        code = next(codes, 200)
        return _chat_ok("{}") if code == 200 else httpx.Response(code)

    assert _provider(handler).chat("t", "s", "u").text == "{}"
    assert len(calls) == 3


def test_does_not_retry_other_4xx() -> None:
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(402, json={"error": {"message": "No credits available."}})

    with pytest.raises(AiError) as e:
        _provider(handler).chat("t", "s", "u")
    assert e.value.status == 402 and not e.value.retryable and len(calls) == 1


def test_timeouts_are_retryable_and_give_up() -> None:
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(AiError) as e:
        _provider(handler).chat("t", "s", "u")
    assert e.value.retryable


def test_ocr_job_flow_polls_until_complete() -> None:
    statuses = iter(["running", "completed"])

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/doc-ai/v1/job/parse":
            assert b'name="language"' in req.content and b"hi-IN" in req.content
            return httpx.Response(200, json={"job_id": "j1", "status": "queued"})
        if req.url.path == "/doc-ai/v1/job/j1/status":
            return httpx.Response(200, json={"status": next(statuses)})
        if req.url.path == "/doc-ai/v1/job/j1/results":
            return httpx.Response(
                200, json={"documents": [{"pages": [{"page_number": 2, "content": "दो"}, {"page_number": 1, "content": "एक"}]}]}
            )
        return httpx.Response(404)

    pages = _provider(handler).parse_document(b"%PDF-", "a.pdf", "hi-IN")
    assert [(p.page, p.text) for p in pages] == [(1, "एक"), (2, "दो")]


def test_ocr_failed_job_raises() -> None:
    def handler(req):
        if req.url.path.endswith("/parse"):
            return httpx.Response(200, json={"job_id": "j2", "status": "queued"})
        return httpx.Response(200, json={"status": "failed"})

    with pytest.raises(AiError):
        _provider(handler).parse_document(b"%PDF-", "a.pdf", "en-IN")


def test_stt_and_tts() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/speech-to-text":
            assert b"saaras:v4" in req.content and b"codemix" in req.content
            return httpx.Response(200, json={"transcript": " kiraya kitna hai ", "language_code": "hi-IN"})
        if req.url.path == "/text-to-speech":
            assert json.loads(req.content)["language_code"] == "hi-IN"
            return httpx.Response(200, json={"audios": [base64.b64encode(b"RIFFwav").decode()]})
        return httpx.Response(404)

    p = _provider(handler)
    t = p.transcribe(b"audio", "q.webm", "audio/webm")
    assert t.text == "kiraya kitna hai" and t.language == "hi-IN"
    assert p.speak("नमस्ते", "hi-IN") == b"RIFFwav"


# ---- JSON helper ------------------------------------------------------------------------------------------


class Out(BaseModel):
    answer: str


class Scripted:
    name, model, is_demo = "scripted", "test", False

    def __init__(self, *replies: str) -> None:
        self.replies, self.prompts = list(replies), []

    def chat(self, task, system, user, schema=None):
        self.prompts.append(user)
        return ChatResult(self.replies.pop(0))


def test_extract_json_strips_reasoning_and_fences() -> None:
    assert extract_json('<think>hmm {"x":1}</think>\n```json\n{"answer": "ok"}\n```') == '{"answer": "ok"}'


def test_complete_json_retries_once_with_the_error() -> None:
    p = Scripted("not json", '{"answer": "ok"}')
    assert complete_json(p, "t", "s", "u", Out).answer == "ok"
    assert "previous reply was invalid" in p.prompts[1]


def test_complete_json_gives_up_after_two_invalid_replies() -> None:
    with pytest.raises(AiError):
        complete_json(Scripted('{"wrong": 1}', "nope"), "t", "s", "u", Out)
