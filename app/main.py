"""Точка входа. Запуск: uvicorn app.main:app --reload"""
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.api.routes import router
from app.config import get_settings
from app.core.exceptions import AIServiceError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def create_app() -> FastAPI:
    get_settings()  # fail-fast: если нет ANTHROPIC_API_KEY, приложение не стартует

    app = FastAPI(title="Req2Test", version="0.1.0", description="AI-генератор тест-кейсов из требований")
    app.include_router(router)

    @app.exception_handler(AIServiceError)
    async def ai_error_handler(_: Request, exc: AIServiceError) -> JSONResponse:
        # Клиенту отдаём только безопасное сообщение; детали уже в логах.
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.public_message})

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "index.html", {"max_chars": get_settings().max_requirements_chars}
        )

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
