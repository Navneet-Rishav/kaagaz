"""The AI provider interface. The pipeline and Q&A only depend on this Protocol, so the real Sarvam client
and the offline demo provider are interchangeable (tests never call a paid API)."""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError


class AiError(Exception):
    """A provider call failed. `retryable` is True for timeouts, 429 and 5xx (already retried by the client)."""

    def __init__(self, message: str, retryable: bool = False, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable, self.status = retryable, status


class AiUnavailable(AiError):
    """The capability is not available with this provider (e.g. OCR or voice in the offline demo)."""


@dataclass
class ChatResult:
    text: str
    latency_ms: int = 0
    tokens: int = 0


@dataclass
class Transcript:
    text: str
    language: str | None = None


@dataclass
class PageText:
    page: int
    text: str


@dataclass
class Usage:
    calls: int = 0
    tokens: int = 0
    latency_ms: int = 0
    notes: list[str] = field(default_factory=list)


class AiProvider(Protocol):
    name: str
    model: str
    #: Shown in the UI so a reviewer always knows whether real AI produced a result.
    is_demo: bool

    def chat(self, task: str, system: str, user: str, schema: dict | None = None) -> ChatResult: ...

    def parse_document(self, data: bytes, filename: str, language: str) -> list[PageText]: ...

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> Transcript: ...

    def speak(self, text: str, language: str) -> bytes: ...


M = TypeVar("M", bound=BaseModel)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(text: str) -> str:
    """Strips reasoning blocks and code fences, then returns the outermost JSON object."""
    t = _FENCE.sub("", _THINK.sub("", text)).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model output")
    return t[start : end + 1]


def complete_json[M: BaseModel](
    provider: AiProvider, task: str, system: str, user: str, model_cls: type[M], usage: Usage | None = None
) -> M:
    """Calls the model with a JSON schema and validates the reply with Pydantic. On invalid output it retries
    once, telling the model what was wrong. Raises AiError if the second reply is still invalid."""
    schema = {"name": task, "schema": model_cls.model_json_schema(), "strict": False}
    prompt = user
    last_error = ""
    for attempt in range(2):
        t0 = time.perf_counter()
        res = provider.chat(task, system, prompt, schema)
        if usage is not None:
            usage.calls += 1
            usage.tokens += res.tokens
            usage.latency_ms += res.latency_ms or int((time.perf_counter() - t0) * 1000)
        try:
            return model_cls.model_validate(json.loads(extract_json(res.text)))
        except (ValueError, ValidationError) as e:
            last_error = str(e)[:500]
            prompt = f"{user}\n\nYour previous reply was invalid: {last_error}\nReply again with ONLY a JSON object matching the schema."
            if usage is not None and attempt == 0:
                usage.notes.append(f"{task}: invalid JSON, retried")
    raise AiError(f"model returned invalid JSON for {task}: {last_error}")
