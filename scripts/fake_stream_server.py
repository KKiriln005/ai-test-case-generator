"""Локальний стенд для ручного тестування веб-інтерфейсу без API-ключа і без витрат на токени.

Піднімає справжній застосунок `app.main:app`, але підмінює AIService фейком, який віддає
кейси із затримкою - так видно, як вони з'являються в UI по одному.

Запуск (з кореня проєкту):
    python scripts/fake_stream_server.py            # сценарій ok
    python scripts/fake_stream_server.py error      # помилка посеред потоку (після 2-го кейса)
    python scripts/fake_stream_server.py early      # помилка до першого кейса (429)
    python scripts/fake_stream_server.py drop       # обрив з'єднання: потік закрився без `done`
    python scripts/fake_stream_server.py hang       # 2 кейси, потім тиша (кнопка «Зупинити»)
Змінна FAKE_DELAY задає паузу між кейсами в секундах (за замовчуванням 0.8).
Відкрити: http://127.0.0.1:8000
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("ANTHROPIC_API_KEY", "fake-key")  # реальний API не викликається

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
        title=f"Демо-кейс №{n}: вхід з паролем довжиною {7 + n} символів",
        test_type=TYPES[n % 4],
        priority=PRIORITIES[n % 4],
        preconditions="Користувач зареєстрований",
        steps=["Відкрити сторінку входу", "Ввести email і пароль", "Натиснути «Увійти»"],
        expected_result="Система реагує відповідно до вимог",
        test_data=f"password: {'a' * (7 + n)}",
    )


class FakeAIService:
    def __init__(self, scenario: str, delay: float) -> None:
        self.scenario, self.delay = scenario, delay

    def _suite(self, count: int) -> TestSuite:
        return TestSuite(
            summary="Демо-набір від фейкового сервісу: перевірка UI без звернення до Claude.",
            assumptions=["Це тестові дані, а не відповідь моделі."],
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
        sys.exit(f"Невідомий сценарій {scenario!r}. Доступні: {', '.join(sorted(SCENARIOS))}")
    service = FakeAIService(scenario, float(os.environ.get("FAKE_DELAY", "0.8")))
    app.dependency_overrides[get_ai_service] = lambda: service
    print(f"Fake AI scenario: {scenario}. Відкрий http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
