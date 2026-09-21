from langchain_openai import ChatOpenAI

from app.core.config import settings


def get_chat_model(model: str, **kwargs) -> ChatOpenAI:
    """Chat model routed through OpenRouter."""
    return ChatOpenAI(
        model=model,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        default_headers={"X-Title": settings.OPENROUTER_APP_NAME},
        **kwargs,
    )
