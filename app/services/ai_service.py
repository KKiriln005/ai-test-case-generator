"""Сервис интеграции с Anthropic API.

Гарантия структуры: заставляем Claude вызвать инструмент `submit_test_suite`
(tool_choice = конкретный tool), входная схема которого - JSON Schema нашей Pydantic-модели.
Ответ дополнительно валидируется Pydantic, при сбое - одна повторная попытка.

Два режима: `generate_test_suite` (весь набор разом) и `stream_test_suite`
(кейсы по мере генерации, для SSE).
"""
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import ValidationError

from app.config import Settings
from app.core.exceptions import (
    AIConfigError,
    AIOutputError,
    AIRateLimitError,
    AIRequestRejectedError,
    AIServiceError,
    AIUnavailableError,
)
from app.prompts import TOOL_DESCRIPTION, TOOL_NAME, build_system_prompt, build_user_prompt
from app.schemas import GenerateRequest, TestCase, TestSuite
from app.services.stream_parser import CaseExtractor

logger = logging.getLogger(__name__)

_MAX_VALIDATION_ATTEMPTS = 2
# Все ошибки SDK, которые мы переводим в доменные исключения.
_API_ERRORS = (APIStatusError, APIConnectionError)


@dataclass(frozen=True)
class StreamEvent:
    """Событие потока: "case" (один тест-кейс) или "done" (весь набор, для экспорта)."""

    event: str
    data: dict


def _translate_api_error(exc: Exception) -> AIServiceError:
    """Перевод ошибок SDK в доменные. Подробности - только в лог."""
    # Порядок важен: специфичные классы идут раньше базовых (APITimeoutError -> APIConnectionError,
    # AuthenticationError и др. -> APIStatusError).
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        logger.error("Anthropic auth/permission error: %s", exc)
        return AIConfigError()
    if isinstance(exc, RateLimitError):
        logger.warning("Anthropic rate limit: %s", exc)
        return AIRateLimitError()
    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        logger.error("Anthropic connection/timeout error: %s", exc)
        return AIUnavailableError()
    if isinstance(exc, BadRequestError):
        logger.error("Anthropic rejected request: %s", exc)
        return AIRequestRejectedError()
    if isinstance(exc, APIStatusError):
        logger.error("Anthropic API status %s: %s", exc.status_code, exc)
        if exc.status_code == 404:  # неверное имя модели
            return AIConfigError()
        if exc.status_code >= 500:  # включая 529 overloaded
            return AIUnavailableError()
    return AIServiceError()


class AIService:
    def __init__(self, settings: Settings, client: AsyncAnthropic | None = None) -> None:
        self._settings = settings
        # client можно подменить в тестах (dependency injection).
        self._client = client or AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=settings.anthropic_timeout_s,
            max_retries=settings.anthropic_max_retries,
        )
        self._tool = {
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "input_schema": TestSuite.model_json_schema(),
        }

    # ------------------------------------------------------------------ обычный режим

    async def generate_test_suite(self, request: GenerateRequest) -> TestSuite:
        system, messages = self._build_prompt(request)

        for attempt in range(1, _MAX_VALIDATION_ATTEMPTS + 1):
            response = await self._call_api(system, messages)

            if response.stop_reason == "max_tokens":
                # Ответ обрезан -> JSON невалиден, повтор с теми же параметрами не поможет.
                logger.error("Response truncated by max_tokens (attempt %s)", attempt)
                raise AIOutputError()

            tool_block = self._find_tool_block(response)
            if tool_block is None:
                logger.warning("No tool_use block in response (attempt %s)", attempt)
                continue

            try:
                suite = TestSuite.model_validate(tool_block.input)
            except ValidationError as exc:
                logger.warning("Schema validation failed (attempt %s): %s", attempt, exc.errors()[:3])
                continue

            return self._postprocess(suite, request.max_cases)

        raise AIOutputError()

    # ------------------------------------------------------------------ потоковый режим

    async def stream_test_suite(self, request: GenerateRequest) -> AsyncIterator[StreamEvent]:
        """Отдаёт "case" по мере готовности каждого кейса и в конце "done" с полным набором.

        Ретраев нет: часть данных уже ушла клиенту, повтор дал бы дубликаты.
        """
        system, messages = self._build_prompt(request)
        extractor = CaseExtractor()
        emitted = 0

        try:
            async with self._client.messages.stream(**self._request_kwargs(system, messages)) as stream:
                async for event in stream:
                    if event.type != "content_block_delta" or event.delta.type != "input_json_delta":
                        continue
                    for raw in extractor.feed(event.delta.partial_json):
                        if emitted >= request.max_cases:
                            continue
                        try:
                            case = TestCase.model_validate(raw)
                        except ValidationError as exc:
                            logger.warning("Streamed case failed validation: %s", exc.errors()[:3])
                            raise AIOutputError() from exc
                        emitted += 1
                        case.id = f"TC-{emitted:03d}"
                        yield StreamEvent("case", case.model_dump(mode="json"))
                final = await stream.get_final_message()
        except _API_ERRORS as exc:
            raise _translate_api_error(exc) from exc
        except ValueError as exc:  # json.JSONDecodeError из парсера потока
            logger.error("Broken JSON in stream: %s", exc)
            raise AIOutputError() from exc

        if final.stop_reason == "max_tokens":
            raise AIOutputError()
        block = self._find_tool_block(final)
        if block is None:
            raise AIOutputError()
        try:
            suite = TestSuite.model_validate(block.input)
        except ValidationError as exc:
            logger.warning("Final suite failed validation: %s", exc.errors()[:3])
            raise AIOutputError() from exc
        yield StreamEvent("done", self._postprocess(suite, request.max_cases).model_dump(mode="json"))

    # ------------------------------------------------------------------ внутреннее

    @staticmethod
    def _build_prompt(request: GenerateRequest) -> tuple[str, list[dict]]:
        system = build_system_prompt(max_cases=request.max_cases, language=request.language)
        return system, [{"role": "user", "content": build_user_prompt(request.requirements)}]

    def _request_kwargs(self, system: str, messages: list[dict]) -> dict:
        return {
            "model": self._settings.anthropic_model,
            "max_tokens": self._settings.anthropic_max_tokens,
            "system": system,
            "messages": messages,
            "tools": [self._tool],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
        }

    async def _call_api(self, system: str, messages: list[dict]):
        try:
            return await self._client.messages.create(**self._request_kwargs(system, messages))
        except _API_ERRORS as exc:
            raise _translate_api_error(exc) from exc

    @staticmethod
    def _find_tool_block(message):
        return next((b for b in message.content if b.type == "tool_use" and b.name == TOOL_NAME), None)

    @staticmethod
    def _postprocess(suite: TestSuite, max_cases: int) -> TestSuite:
        """Не доверяем модели в мелочах: обрезаем по лимиту и перенумеровываем ID."""
        suite.test_cases = suite.test_cases[:max_cases]
        for index, case in enumerate(suite.test_cases, start=1):
            case.id = f"TC-{index:03d}"
        return suite
