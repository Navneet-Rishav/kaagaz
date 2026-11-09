import json

import pytest

from app.ai import set_provider
from app.ai.base import ChatResult, Transcript
from app.ai.demo import DemoProvider
from app.services import jobs
from app.services.qa import NOT_FOUND, Answer, question_language, validate_citations
from tests.pdfgen import RENT_EN, make_pdf

# ---- citation validation (pure) -------------------------------------------------------------------------


def test_valid_citations_are_kept() -> None:
    r = validate_citations(Answer(found=True, answer="Rent is ₹18,500 [p.1].", citations=[1]), {1, 2})
    assert r == ("Rent is ₹18,500 [p.1].", [1])


def test_citations_to_pages_not_retrieved_are_removed() -> None:
    r = validate_citations(Answer(found=True, answer="Rent is ₹18,500 [p.1] [p.9].", citations=[1, 9]), {1, 2})
    assert r == ("Rent is ₹18,500 [p.1].", [1])


def test_answer_citing_only_unretrieved_pages_is_refused() -> None:
    assert validate_citations(Answer(found=True, answer="Rent is ₹20,000 [p.7].", citations=[7]), {1, 2}) is None


@pytest.mark.parametrize("ans", [Answer(found=False, answer="", citations=[]), Answer(found=True, answer="   ", citations=[1])])
def test_not_found_or_empty_is_refused(ans: Answer) -> None:
    assert validate_citations(ans, {1}) is None


def test_missing_markers_are_added_from_citations_list() -> None:
    assert validate_citations(Answer(found=True, answer="Two months.", citations=[2]), {2}) == ("Two months. [p.2]", [2])


def test_question_language() -> None:
    assert question_language("किराया कितना है?") == "hi"
    assert question_language("What is the rent?") == "en"


# ---- API --------------------------------------------------------------------------------------------------


def _upload(client, headers, data: bytes, name="rent.pdf", language="en-IN"):
    return client.post(
        "/api/documents", headers=headers, files={"file": (name, data, "application/pdf")}, data={"language": language}
    )


def _ready_doc(client, headers, db) -> str:
    r = _upload(client, headers, make_pdf(RENT_EN))
    assert r.status_code == 202, r.text
    while jobs.process_next(db):
        pass
    return r.json()["id"]


def test_upload_process_and_read_document(client, auth_headers, db) -> None:
    doc_id = _ready_doc(client, auth_headers, db)
    listing = client.get("/api/documents", headers=auth_headers).json()["items"]
    assert [d["status"] for d in listing] == ["ready"]
    d = client.get(f"/api/documents/{doc_id}", headers=auth_headers).json()
    assert d["doc_type"] == "rent_agreement" and d["original_deleted"] is True
    rent = next(f for f in d["fields"] if f["name"] == "monthly_rent_inr")
    assert rent == {
        "name": "monthly_rent_inr",
        "label_en": "Monthly rent (₹)",
        "label_hi": "मासिक किराया (₹)",
        "value": "18500",
        "page": 1,
        "confidence": "medium",
    }
    pages = client.get(f"/api/documents/{doc_id}/pages", headers=auth_headers).json()["pages"]
    assert [p["page"] for p in pages] == [1, 2] and "<PHONE>" in pages[0]["text"]


def test_upload_rejects_bad_type_and_duplicates(client, auth_headers) -> None:
    bad = client.post("/api/documents", headers=auth_headers, files={"file": ("x.pdf", b"GIF89a fake", "application/pdf")})
    assert bad.status_code == 415 and bad.json()["error"]["code"] == "unsupported_type"
    pdf = make_pdf(RENT_EN)
    first = _upload(client, auth_headers, pdf)
    dup = _upload(client, auth_headers, pdf)
    assert dup.status_code == 409 and dup.json()["error"]["details"]["document_id"] == first.json()["id"]


def test_upload_rejects_too_many_pages(client, auth_headers) -> None:
    r = _upload(client, auth_headers, make_pdf(["page"] * 31))
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_many_pages"


def test_other_users_cannot_see_a_document(client, auth_headers, db) -> None:
    doc_id = _ready_doc(client, auth_headers, db)
    other = client.post("/api/auth/register", json={"name": "Eve", "email": "eve@example.com", "password": "eve-password"}).json()
    h = {"Authorization": f"Bearer {other['token']}"}
    for path in ("", "/pages", "/history"):
        assert client.get(f"/api/documents/{doc_id}{path}", headers=h).status_code == 404
    assert client.post(f"/api/documents/{doc_id}/ask", headers=h, json={"question": "rent?"}).status_code == 404
    assert client.delete(f"/api/documents/{doc_id}", headers=h).status_code == 404


def test_ask_answers_with_valid_citation(client, auth_headers, db) -> None:
    doc_id = _ready_doc(client, auth_headers, db)
    r = client.post(f"/api/documents/{doc_id}/ask", headers=auth_headers, json={"question": "What is the notice period?"}).json()
    assert r["refused"] is False and r["citations"] == [2] and "[p.2]" in r["answer"] and "two months" in r["answer"]
    assert r["demo_mode"] is True and r["sources"][0]["page"] == 2


def test_cross_language_question_finds_english_text(client, auth_headers, db) -> None:
    doc_id = _ready_doc(client, auth_headers, db)
    r = client.post(f"/api/documents/{doc_id}/ask", headers=auth_headers, json={"question": "नोटिस अवधि क्या है?"}).json()
    assert r["refused"] is False and r["language"] == "hi" and r["citations"] == [2]


def test_ask_refuses_when_not_in_document(client, auth_headers, db) -> None:
    doc_id = _ready_doc(client, auth_headers, db)
    r = client.post(
        f"/api/documents/{doc_id}/ask", headers=auth_headers, json={"question": "Who won the cricket world cup?"}
    ).json()
    assert r["refused"] is True and r["answer"] == NOT_FOUND and r["citations"] == []


class LyingProvider(DemoProvider):
    """Answers confidently but cites a page that was not retrieved: must be refused."""

    def chat(self, task, system, user, schema=None):
        if task == "answer":
            return ChatResult(json.dumps({"found": True, "answer": "Rent is ₹99,999 [p.5]", "citations": [5]}))
        return super().chat(task, system, user, schema)


def test_hallucinated_citation_is_refused(client, auth_headers, db) -> None:
    doc_id = _ready_doc(client, auth_headers, db)
    set_provider(LyingProvider())
    try:
        r = client.post(
            f"/api/documents/{doc_id}/ask", headers=auth_headers, json={"question": "What is the monthly rent?"}
        ).json()
        assert r["refused"] is True and "99,999" not in r["answer"]
    finally:
        set_provider(None)


def test_history_is_logged(client, auth_headers, db) -> None:
    doc_id = _ready_doc(client, auth_headers, db)
    client.post(f"/api/documents/{doc_id}/ask", headers=auth_headers, json={"question": "What is the notice period?"})
    client.post(f"/api/documents/{doc_id}/ask", headers=auth_headers, json={"question": "Who won the cricket world cup?"})
    items = client.get(f"/api/documents/{doc_id}/history", headers=auth_headers).json()["items"]
    assert [i["refused"] for i in items] == [False, True]


def test_ask_rate_limited_per_user(client, auth_headers, db, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ask_per_hour", 2)
    doc_id = _ready_doc(client, auth_headers, db)
    codes = [
        client.post(f"/api/documents/{doc_id}/ask", headers=auth_headers, json={"question": "notice period?"}).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_ask_before_ready_is_rejected(client, auth_headers) -> None:
    doc_id = _upload(client, auth_headers, make_pdf(RENT_EN)).json()["id"]
    r = client.post(f"/api/documents/{doc_id}/ask", headers=auth_headers, json={"question": "rent?"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_ready"


def test_delete_document(client, auth_headers, db) -> None:
    doc_id = _ready_doc(client, auth_headers, db)
    assert client.delete(f"/api/documents/{doc_id}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/documents/{doc_id}", headers=auth_headers).status_code == 404


def test_demo_login_gives_each_visitor_an_isolated_seeded_account(client, db) -> None:
    a = client.post("/api/auth/demo").json()
    b = client.post("/api/auth/demo").json()
    assert a["user"]["id"] != b["user"]["id"] and a["user"]["is_demo"]
    ha = {"Authorization": f"Bearer {a['token']}"}
    assert len(client.get("/api/documents", headers=ha).json()["items"]) == 3
    _upload(client, ha, make_pdf(RENT_EN))
    hb = {"Authorization": f"Bearer {b['token']}"}
    assert len(client.get("/api/documents", headers=hb).json()["items"]) == 3  # b does not see a's upload


def test_meta_labels_demo_mode(client) -> None:
    m = client.get("/api/meta").json()
    assert m["demo_mode"] is True and m["voice_enabled"] is False and m["provider"] == "demo"


# ---- voice ------------------------------------------------------------------------------------------------


def test_voice_is_unavailable_in_demo_mode(client, auth_headers) -> None:
    r = client.post(
        "/api/voice/transcribe", headers=auth_headers, files={"audio": ("q.webm", b"\x1a\x45\xdf\xa3....", "audio/webm")}
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "voice_unavailable"


class VoiceProvider(DemoProvider):
    is_demo = False

    def transcribe(self, audio, filename, content_type):
        return Transcript(text="kiraya kitna hai", language="hi-IN")

    def speak(self, text, language):
        return b"RIFF....WAVE"


def test_voice_routes_with_a_working_provider(client, auth_headers) -> None:
    set_provider(VoiceProvider())
    try:
        r = client.post(
            "/api/voice/transcribe", headers=auth_headers, files={"audio": ("q.webm", b"audio-bytes", "audio/webm;codecs=opus")}
        )
        assert r.status_code == 200 and r.json() == {"text": "kiraya kitna hai", "language": "hi-IN"}
        s = client.post("/api/voice/speak", headers=auth_headers, json={"text": "किराया ₹18,500 है", "language": "hi-IN"})
        assert s.status_code == 200 and s.headers["content-type"] == "audio/wav" and s.content.startswith(b"RIFF")
    finally:
        set_provider(None)


def test_voice_rejects_bad_audio(client, auth_headers) -> None:
    set_provider(VoiceProvider())
    try:
        assert (
            client.post(
                "/api/voice/transcribe", headers=auth_headers, files={"audio": ("q.exe", b"MZ", "application/x-msdownload")}
            ).status_code
            == 415
        )
        big = b"0" * (2 * 1024 * 1024 + 1)
        assert (
            client.post("/api/voice/transcribe", headers=auth_headers, files={"audio": ("q.webm", big, "audio/webm")}).status_code
            == 413
        )
    finally:
        set_provider(None)
