"""FastAPI-зависимости. Сервис создаётся один раз и переиспользуется (общий HTTP-пул)."""
from functools import lru_cache

from app.config import get_settings
from app.services.ai_service import AIService


@lru_cache
def get_ai_service() -> AIService:
    return AIService(get_settings())
