"""Тести HTTP-шару: сервіс підмінюється через dependency_overrides."""
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_ai_service
from app.core.exceptions import AIConfigError, AIRateLimitError
from app.main import app
from app.schemas import TestSuite
from app.services.ai_service import StreamEvent
from tests.factories import make_case, make_payload

REQUIREMENTS = {"requirements": "As a user I want to log in with email and password."}


class FakeService:
    def __init__(self, result=None, error=None, events=None):
        self._result, self._error, self._events = result, error, events or []

    async def generate_test_suite(self, request):
        if self._error:
            raise self._error
        return self._result

    async def stream_test_suite(self, request):
        for event in self._events:
            yield event
        if self._error:
            raise self._error


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(service):
    app.dependency_overrides[get_ai_service] = lambda: service


def test_health_and_index(client):
    assert client.get("/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200 and "Req2Test" in page.text


def test_generate_success(client):
    use(FakeService(result=TestSuite.model_validate(make_payload(2))))

    response = client.post("/api/generate", json=REQUIREMENTS)

    assert response.status_code == 200
    assert len(response.json()["test_cases"]) == 2


def test_generate_rejects_too_short_requirements(client):
    assert client.post("/api/generate", json={"requirements": "short"}).status_code == 422


@pytest.mark.parametrize("error, status", [(AIRateLimitError(), 429), (AIConfigError(), 500)])
def test_domain_errors_become_http_errors(client, error, status):
    use(FakeService(error=error))

    response = client.post("/api/generate", json=REQUIREMENTS)

    assert response.status_code == status
    assert response.json() == {"detail": error.public_message}


def test_export_returns_attachment(client):
    suite = make_payload(2)

    response = client.post("/api/export", json={"format": "zephyr", "suite": suite})

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition and "zephyr" in disposition and disposition.endswith('.csv"')


def test_export_rejects_unknown_format(client):
    assert client.post("/api/export", json={"format": "xml", "suite": make_payload(1)}).status_code == 422


def test_stream_endpoint_sends_sse_frames(client):
    events = [StreamEvent("case", make_case(1)), StreamEvent("done", make_payload(1))]
    use(FakeService(events=events))

    response = client.post("/api/generate-stream", json=REQUIREMENTS)

    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: case") == 1
    assert "event: done" in response.text


def test_stream_endpoint_reports_midstream_error_as_event(client):
    use(FakeService(events=[StreamEvent("case", make_case(1))], error=AIRateLimitError()))

    response = client.post("/api/generate-stream", json=REQUIREMENTS)

    assert response.status_code == 200  # заголовки вже надіслано, помилка йде подією
    assert "event: error" in response.text
    assert AIRateLimitError.public_message in response.text


def test_stream_endpoint_hides_unexpected_errors(client):
    use(FakeService(error=RuntimeError("secret internal detail")))

    response = client.post("/api/generate-stream", json=REQUIREMENTS)

    assert "event: error" in response.text
    assert '"status": 500' in response.text
    assert "secret internal detail" not in response.text


def test_stream_endpoint_validates_before_streaming(client):
    response = client.post("/api/generate-stream", json={"requirements": "short"})

    assert response.status_code == 422  # звичайний JSON, потік не починається
    assert response.headers["content-type"].startswith("application/json")


def test_stream_endpoint_disables_proxy_buffering(client):
    use(FakeService(events=[StreamEvent("done", make_payload(1))]))

    response = client.post("/api/generate-stream", json=REQUIREMENTS)

    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-cache"


def test_index_uses_streaming_endpoint(client):
    page = client.get("/").text

    assert "/api/generate-stream" in page
    assert 'id="stop"' in page


def test_russian_language_is_not_supported(client):
    response = client.post("/api/generate", json={**REQUIREMENTS, "language": "ru"})

    assert response.status_code == 422
