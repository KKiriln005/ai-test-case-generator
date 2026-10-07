"""Юніт-тести AIService з повністю замоканим AsyncAnthropic (мережа не використовується)."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from app.config import Settings
from app.core.exceptions import (
    AIConfigError,
    AIOutputError,
    AIRateLimitError,
    AIRequestRejectedError,
    AIServiceError,
    AIUnavailableError,
)
from app.prompts import TOOL_NAME
from app.schemas import GenerateRequest
from app.services.ai_service import AIService
from tests.factories import make_payload

REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
SETTINGS = Settings(anthropic_api_key="test-key", anthropic_model="test-model", _env_file=None)


def status_error(cls, status: int):
    return cls("boom", response=httpx.Response(status, request=REQUEST), body=None)


def tool_response(payload: dict, stop_reason: str = "tool_use"):
    block = SimpleNamespace(type="tool_use", name=TOOL_NAME, input=payload)
    return SimpleNamespace(stop_reason=stop_reason, content=[block])


def make_request(max_cases: int = 10) -> GenerateRequest:
    return GenerateRequest(
        requirements="As a user I want to log in with email and password.", max_cases=max_cases
    )


def make_service(*side_effects):
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=list(side_effects))
    return AIService(SETTINGS, client=client), client


INVALID_PAYLOAD = {"summary": "s", "assumptions": [], "test_cases": [{"title": "no required fields"}]}


# ---------------------------------------------------------------- успішний сценарій

async def test_success_renumbers_ids():
    service, client = make_service(tool_response(make_payload(3)))

    suite = await service.generate_test_suite(make_request())

    assert [c.id for c in suite.test_cases] == ["TC-001", "TC-002", "TC-003"]
    assert client.messages.create.await_count == 1


async def test_truncates_to_max_cases():
    service, _ = make_service(tool_response(make_payload(5)))

    suite = await service.generate_test_suite(make_request(max_cases=3))

    assert [c.id for c in suite.test_cases] == ["TC-001", "TC-002", "TC-003"]


async def test_request_forces_tool_and_embeds_limits():
    service, client = make_service(tool_response(make_payload(3)))

    await service.generate_test_suite(make_request(max_cases=7))

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert kwargs["tools"][0]["name"] == TOOL_NAME
    assert "at most 7" in kwargs["system"]
    assert "<requirements>" in kwargs["messages"][0]["content"]


# ---------------------------------------------------------------- retry при невалідній структурі

async def test_retries_once_on_invalid_structure():
    service, client = make_service(tool_response(INVALID_PAYLOAD), tool_response(make_payload(2)))

    suite = await service.generate_test_suite(make_request())

    assert len(suite.test_cases) == 2
    assert client.messages.create.await_count == 2


async def test_retries_when_tool_block_is_missing():
    text_only = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="hi")])
    service, client = make_service(text_only, tool_response(make_payload(2)))

    suite = await service.generate_test_suite(make_request())

    assert len(suite.test_cases) == 2
    assert client.messages.create.await_count == 2


async def test_gives_up_after_second_invalid_response():
    service, client = make_service(tool_response(INVALID_PAYLOAD), tool_response(INVALID_PAYLOAD))

    with pytest.raises(AIOutputError) as info:
        await service.generate_test_suite(make_request())

    assert info.value.status_code == 502
    assert client.messages.create.await_count == 2


# ---------------------------------------------------------------- max_tokens

async def test_max_tokens_is_not_retried():
    service, client = make_service(tool_response(make_payload(1), stop_reason="max_tokens"))

    with pytest.raises(AIOutputError):
        await service.generate_test_suite(make_request())

    assert client.messages.create.await_count == 1


# ---------------------------------------------------------------- помилки API -> доменні

API_ERRORS = [
    pytest.param(status_error(AuthenticationError, 401), AIConfigError, 500, id="401-auth"),
    pytest.param(status_error(PermissionDeniedError, 403), AIConfigError, 500, id="403-permission"),
    pytest.param(status_error(NotFoundError, 404), AIConfigError, 500, id="404-unknown-model"),
    pytest.param(status_error(RateLimitError, 429), AIRateLimitError, 429, id="429-rate-limit"),
    pytest.param(status_error(BadRequestError, 400), AIRequestRejectedError, 502, id="400-bad-request"),
    pytest.param(status_error(APIStatusError, 529), AIUnavailableError, 503, id="529-overloaded"),
    pytest.param(status_error(APIStatusError, 418), AIServiceError, 502, id="other-status"),
    pytest.param(APITimeoutError(request=REQUEST), AIUnavailableError, 503, id="timeout"),
    pytest.param(APIConnectionError(request=REQUEST), AIUnavailableError, 503, id="connection"),
]


@pytest.mark.parametrize("error, expected, http_status", API_ERRORS)
async def test_api_errors_are_translated(error, expected, http_status):
    service, client = make_service(error)

    with pytest.raises(AIServiceError) as info:
        await service.generate_test_suite(make_request())

    assert type(info.value) is expected
    assert info.value.status_code == http_status
    assert client.messages.create.await_count == 1  # ретраї мережі робить SDK, не сервіс


# ---------------------------------------------------------------- потоковий режим

class FakeStream:
    """Підробка `client.messages.stream(...)`: async context manager + async iterator подій."""

    def __init__(self, chunks, final):
        self._chunks, self._final = chunks, final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._events()

    async def _events(self):
        for chunk in self._chunks:
            delta = SimpleNamespace(type="input_json_delta", partial_json=chunk)
            yield SimpleNamespace(type="content_block_delta", delta=delta)

    async def get_final_message(self):
        return self._final


def make_stream_service(stream):
    client = MagicMock()
    client.messages.stream = MagicMock(return_value=stream)
    return AIService(SETTINGS, client=client)


def split(text: str, size: int = 11) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


async def test_stream_emits_cases_then_done():
    payload = make_payload(3)
    stream = FakeStream(split(json.dumps(payload)), tool_response(payload))
    service = make_stream_service(stream)

    events = [e async for e in service.stream_test_suite(make_request())]

    assert [e.event for e in events] == ["case", "case", "case", "done"]
    assert [e.data["id"] for e in events[:3]] == ["TC-001", "TC-002", "TC-003"]
    assert len(events[-1].data["test_cases"]) == 3


async def test_stream_respects_max_cases():
    payload = make_payload(5)
    service = make_stream_service(FakeStream(split(json.dumps(payload)), tool_response(payload)))

    events = [e async for e in service.stream_test_suite(make_request(max_cases=3))]

    assert [e.event for e in events].count("case") == 3
    assert len(events[-1].data["test_cases"]) == 3


async def test_stream_translates_api_errors():
    class Broken(FakeStream):
        async def __aenter__(self):
            raise status_error(RateLimitError, 429)

    service = make_stream_service(Broken([], None))

    with pytest.raises(AIRateLimitError):
        [e async for e in service.stream_test_suite(make_request())]


def stream_service_for(payload: dict, final=None):
    final = final if final is not None else tool_response(payload)
    return make_stream_service(FakeStream(split(json.dumps(payload)), final))


async def test_stream_max_tokens_after_cases_raises_output_error():
    payload = make_payload(2)
    service = stream_service_for(payload, tool_response(payload, stop_reason="max_tokens"))

    events, error = [], None
    try:
        async for e in service.stream_test_suite(make_request()):
            events.append(e)
    except AIOutputError as exc:
        error = exc

    assert [e.event for e in events] == ["case", "case"]  # уже надіслані кейси не губляться
    assert isinstance(error, AIOutputError)


async def test_stream_without_tool_block_in_final_message():
    text_only = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="hi")])
    service = stream_service_for(make_payload(1), text_only)

    with pytest.raises(AIOutputError):
        [e async for e in service.stream_test_suite(make_request())]


async def test_stream_invalid_case_stops_stream():
    service = stream_service_for(INVALID_PAYLOAD)

    with pytest.raises(AIOutputError):
        [e async for e in service.stream_test_suite(make_request())]


async def test_stream_broken_json_becomes_output_error():
    broken = FakeStream(['{"test_cases": [{"title": "x",,}]}'], None)
    service = make_stream_service(broken)

    with pytest.raises(AIOutputError):
        [e async for e in service.stream_test_suite(make_request())]


async def test_stream_invalid_final_suite_raises():
    payload = make_payload(1)
    service = stream_service_for(payload, tool_response({"test_cases": payload["test_cases"]}))  # немає summary

    with pytest.raises(AIOutputError):
        [e async for e in service.stream_test_suite(make_request())]


async def test_stream_ignores_non_json_events():
    payload = make_payload(1)

    class WithNoise(FakeStream):
        async def _events(self):
            yield SimpleNamespace(type="message_start")
            yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="hi"))
            async for e in super()._events():
                yield e

    service = make_stream_service(WithNoise(split(json.dumps(payload)), tool_response(payload)))

    events = [e async for e in service.stream_test_suite(make_request())]

    assert [e.event for e in events] == ["case", "done"]


async def test_default_language_is_ukrainian():
    service, client = make_service(tool_response(make_payload(3)))

    await service.generate_test_suite(make_request())

    assert make_request().language == "uk"
    assert "Ukrainian" in client.messages.create.call_args.kwargs["system"]
