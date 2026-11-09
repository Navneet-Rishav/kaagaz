"""Sarvam AI client: chat completions, Document Intelligence (OCR), speech-to-text and text-to-speech.

Every call has a timeout and is retried with backoff on 429, 5xx and network errors; other 4xx fail fast.
Endpoints follow docs.sarvam.ai (see the handover notes); re-check them there if anything returns 4xx.
"""

import base64
import time

import httpx

from app.ai.base import AiError, ChatResult, PageText, Transcript

BASE_URL = "https://api.sarvam.ai"


def _page_text(page: dict) -> str:
    """OCR results (checked against the live API, Nov 2026) give each page a list of layout `blocks` with
    `text` and `reading_order`. Blocks become paragraphs so the chunker keeps them apart. Older responses
    used a single `content` string; that is still accepted."""
    blocks = page.get("blocks")
    if isinstance(blocks, list):
        ordered = sorted(blocks, key=lambda b: b.get("reading_order", 0))
        return "\n\n".join(b.get("text", "").strip() for b in ordered if b.get("text", "").strip())
    return page.get("content") or ""


class SarvamProvider:
    name = "sarvam"
    is_demo = False

    def __init__(
        self,
        api_key: str,
        model: str = "sarvam-105b",
        reasoning_effort: str | None = None,
        client: httpx.Client | None = None,
        max_retries: int = 2,
        sleep=time.sleep,
        ocr_poll_s: float = 2.0,
        ocr_timeout_s: float = 240.0,
    ) -> None:
        self.model = model
        self._reasoning = reasoning_effort
        self._http = client or httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(90.0, connect=10.0))
        self._headers = {"api-subscription-key": api_key}
        self._retries = max_retries
        self._sleep = sleep
        self._poll = ocr_poll_s
        self._ocr_timeout = ocr_timeout_s

    # -- HTTP with retries -------------------------------------------------------------------------
    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        last: AiError | None = None
        for attempt in range(self._retries + 1):
            if attempt:
                self._sleep(2.0 * attempt if last and last.status == 429 else 0.5 * 2**attempt)
            try:
                r = self._http.request(method, path, headers=self._headers, **kw)
            except httpx.TimeoutException:
                last = AiError(f"Sarvam {path} timed out", retryable=True)
                continue
            except httpx.TransportError as e:
                last = AiError(f"Network error calling Sarvam {path}: {type(e).__name__}", retryable=True)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = AiError(f"Sarvam {path} returned HTTP {r.status_code}", retryable=True, status=r.status_code)
                continue
            if r.status_code >= 400:
                raise AiError(f"Sarvam {path} returned HTTP {r.status_code}: {r.text[:300]}", status=r.status_code)
            return r
        raise last or AiError(f"Sarvam {path} failed", retryable=True)

    # -- Chat --------------------------------------------------------------------------------------
    def chat(self, task: str, system: str, user: str, schema: dict | None = None) -> ChatResult:
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": 4096,  # reasoning tokens count toward this
        }
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": schema}
        if self._reasoning:
            body["reasoning_effort"] = self._reasoning
        t0 = time.perf_counter()
        j = self._request("POST", "/v1/chat/completions", json=body).json()
        text = ((j.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if not text:
            raise AiError("Sarvam returned an empty message", retryable=True)
        usage = j.get("usage") or {}
        return ChatResult(
            text=text,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            tokens=int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0)),
        )

    # -- Document Intelligence (OCR) -----------------------------------------------------------------
    def parse_document(self, data: bytes, filename: str, language: str) -> list[PageText]:
        job = self._request(
            "POST",
            "/doc-ai/v1/job/parse",
            files={"file": (filename, data)},
            data={"language": language},
        ).json()
        job_id = job.get("job_id")
        if not job_id:
            raise AiError("Sarvam OCR did not return a job id")
        deadline = time.monotonic() + self._ocr_timeout
        status = job.get("status", "")
        while status not in ("completed", "partially_completed", "failed", "rejected"):
            if time.monotonic() > deadline:
                raise AiError("Sarvam OCR took too long", retryable=True)
            self._sleep(self._poll)
            status = self._request("GET", f"/doc-ai/v1/job/{job_id}/status").json().get("status", "")
        if status in ("failed", "rejected"):
            raise AiError(f"Sarvam OCR job {status}")
        results = self._request("GET", f"/doc-ai/v1/job/{job_id}/results").json()
        pages: list[PageText] = []
        for doc in results.get("documents", []):
            for p in doc.get("pages", []):
                number = int(p.get("page_num") or p.get("page_number") or len(pages) + 1)
                pages.append(PageText(page=number, text=_page_text(p)))
        return sorted(pages, key=lambda p: p.page)

    # -- Voice ---------------------------------------------------------------------------------------
    def transcribe(self, audio: bytes, filename: str, content_type: str) -> Transcript:
        j = self._request(
            "POST",
            "/speech-to-text",
            files={"file": (filename, audio, content_type)},
            data={"model": "saaras:v4", "mode": "codemix"},
        ).json()
        return Transcript(text=(j.get("transcript") or "").strip(), language=j.get("language_code"))

    def speak(self, text: str, language: str) -> bytes:
        j = self._request(
            "POST", "/text-to-speech", json={"text": text[:1500], "language_code": language, "model": "bulbul:v3"}
        ).json()
        audios = j.get("audios") or []
        if not audios:
            raise AiError("Sarvam TTS returned no audio")
        return base64.b64decode(audios[0])
