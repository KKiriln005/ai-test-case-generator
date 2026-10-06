"""Локальный стенд для ручного тестирования веб-интерфейса без API-ключа и без затрат на токены.

Поднимает настоящее приложение `app.main:app`, но подменяет AIService фейком, который отдаёт
кейсы с задержкой — так видно, как они появляются в UI по одному.

Запуск (из корня проекта):
    python scripts/fake_stream_server.py            # сценарий ok
    python scripts/fake_stream_server.py error      # ошибка посреди потока (после 2-го кейса)
    python scripts/fake_stream_server.py early      # ошибка до первого кейса (429)
    python scripts/fake_stream_server.py drop       # обрыв соединения: поток закрылся без `done`
    python scripts/fake_stream_server.py hang       # 2 кейса, затем тишина (кнопка «Остановить»)
Переменная FAKE_DELAY задаёт паузу между кейсами в секундах (по умолчанию 0.8).
Открыть: http://127.0.0.1:8000
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("ANTHROPIC_API_KEY", "fake-key")  # реальный API не вызывается

import uvicorn  # noqa: E402

from app.api.deps import get_ai_service  # noqa: E402
from app.core.exceptions import AIRateLimitError, AIUnavailableError  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import TestCase, TestSuite  # noqa: E402
from app.services.ai_service import StreamEvent  # noqa: E402

SCENARIOS = {"ok", "error", "early", "drop", "hang"}
TYPES = ["Positive", "Negative", "Boundary", "Equivalence"]
PRIORITIES = ["Critical", "High", "Medium", "Low"]


def fake_case(n: int) -> TestCase:
    return TestCase(
        id=f"TC-{n:03d}",
        title=f"Демо-кейс №{n}: вход с паролем длиной {7 + n} символов",
        test_type=TYPES[n % 4],
        priority=PRIORITIES[n % 4],
        preconditions="Пользователь зарегистрирован",
        steps=["Открыть страницу входа", "Ввести email и пароль", "Нажать «Войти»"],
        expected_result="Система реагирует согласно требованиям",
        test_data=f"password: {'a' * (7 + n)}",
    )


class FakeAIService:
    def __init__(self, scenario: str, delay: float) -> None:
        self.scenario, self.delay = scenario, delay

    def _suite(self, count: int) -> TestSuite:
        return TestSuite(
            summary="Демо-набор от фейкового сервиса: проверка UI без обращения к Claude.",
            assumptions=["Это тестовые данные, а не ответ модели."],
            test_cases=[fake_case(i) for i in range(1, count + 1)],
        )

    async def generate_test_suite(self, request):
        await asyncio.sleep(self.delay)
        return self._suite(request.max_cases)

    async def stream_test_suite(self, request):
        if self.scenario == "early":
            await asyncio.sleep(self.delay)
            raise AIRateLimitError()
        for n in range(1, request.max_cases + 1):
            await asyncio.sleep(self.delay)
            yield StreamEvent("case", fake_case(n).model_dump(mode="json"))
            if n == 2 and self.scenario == "error":
                raise AIUnavailableError()
            if n == 2 and self.scenario == "drop":
                return
            if n == 2 and self.scenario == "hang":
                await asyncio.sleep(3600)
        yield StreamEvent("done", self._suite(request.max_cases).model_dump(mode="json"))


def main() -> None:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "ok"
    if scenario not in SCENARIOS:
        sys.exit(f"Неизвестный сценарий {scenario!r}. Доступны: {', '.join(sorted(SCENARIOS))}")
    service = FakeAIService(scenario, float(os.environ.get("FAKE_DELAY", "0.8")))
    app.dependency_overrides[get_ai_service] = lambda: service
    print(f"Fake AI scenario: {scenario}. Открой http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
