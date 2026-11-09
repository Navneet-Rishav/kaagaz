from app.ai.base import AiProvider
from app.config import get_settings

_provider: AiProvider | None = None


def get_provider() -> AiProvider:
    """The configured provider (AI_PROVIDER=demo|sarvam), created once. Tests override it with set_provider."""
    global _provider
    if _provider is None:
        s = get_settings()
        if s.ai_provider == "sarvam":
            from app.ai.sarvam import SarvamProvider

            _provider = SarvamProvider(
                api_key=s.sarvam_api_key or "", model=s.sarvam_chat_model, reasoning_effort=s.sarvam_reasoning_effort
            )
        else:
            from app.ai.demo import DemoProvider

            _provider = DemoProvider()
    return _provider


def set_provider(p: AiProvider | None) -> None:
    global _provider
    _provider = p
