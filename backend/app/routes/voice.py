from typing import Annotated, Literal

from fastapi import APIRouter, File, Response, UploadFile
from pydantic import BaseModel, Field

from app.ai import get_provider
from app.ai.base import AiError, AiUnavailable
from app.config import get_settings
from app.errors import ApiError
from app.ratelimit import limiter
from app.security import CurrentUser

router = APIRouter(prefix="/api/voice", tags=["voice"])

MAX_AUDIO_BYTES = 2 * 1024 * 1024  # ~1 minute of compressed browser audio
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4"}


def _call(fn, *args):
    try:
        return fn(*args)
    except AiUnavailable as e:
        raise ApiError(503, "voice_unavailable", str(e)) from e
    except AiError as e:
        raise ApiError(502, "ai_error", "The speech service is not responding. Please try again.") from e


@router.post("/transcribe")
async def transcribe(user: CurrentUser, audio: Annotated[UploadFile, File()]) -> dict:
    limiter.hit("voice", user.id, get_settings().voice_per_hour)
    ctype = (audio.content_type or "").split(";")[0].strip()
    if ctype not in AUDIO_TYPES:
        raise ApiError(415, "unsupported_type", "Unsupported audio format")
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise ApiError(400, "empty_file", "No audio was recorded")
    if len(data) > MAX_AUDIO_BYTES:
        raise ApiError(413, "file_too_large", "Recordings can be at most about one minute long")
    t = _call(get_provider().transcribe, data, audio.filename or "question.webm", ctype)
    return {"text": t.text, "language": t.language}


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    language: Literal["hi-IN", "en-IN"] = "hi-IN"


@router.post("/speak")
def speak(body: SpeakIn, user: CurrentUser) -> Response:
    limiter.hit("voice", user.id, get_settings().voice_per_hour)
    audio = _call(get_provider().speak, body.text, body.language)
    return Response(content=audio, media_type="audio/wav")
