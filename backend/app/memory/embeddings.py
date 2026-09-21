import logging

from langchain_openai import OpenAIEmbeddings

from app.core.config import settings

logger = logging.getLogger(__name__)

_embeddings: OpenAIEmbeddings | None = None


def _get_embeddings() -> OpenAIEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
            default_headers={"X-Title": settings.OPENROUTER_APP_NAME},
            # Bound the call so a stalled embed cannot pin a pooled DB
            # connection held by the background memory pipeline.
            timeout=settings.EMBEDDING_TIMEOUT,
            max_retries=settings.EMBEDDING_MAX_RETRIES,
        )
    return _embeddings


async def embed_text(text: str) -> list[float]:
    return await _get_embeddings().aembed_query(text)
