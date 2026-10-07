"""HTTP-ендпоінти. Містять мінімум логіки: валідація -> сервіс -> відповідь."""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.api.deps import get_ai_service
from app.core.exceptions import AIServiceError
from app.schemas import ExportRequest, GenerateRequest, TestSuite
from app.services.ai_service import AIService
from app.services.export_service import export_suite

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["req2test"])


@router.post("/generate", response_model=TestSuite, summary="Згенерувати тест-кейси")
async def generate(payload: GenerateRequest, service: AIService = Depends(get_ai_service)) -> TestSuite:
    return await service.generate_test_suite(payload)


def _sse(event: str, data: dict) -> str:
    """Один кадр Server-Sent Events: event + data (JSON в один рядок) + порожній рядок."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/generate-stream", summary="Згенерувати тест-кейси потоком (SSE)")
async def generate_stream(
    payload: GenerateRequest, service: AIService = Depends(get_ai_service)
) -> StreamingResponse:
    """Події: `case` (один кейс), `done` (повний набір), `error` (збій посеред потоку)."""

    async def event_source():
        try:
            async for item in service.stream_test_suite(payload):
                yield _sse(item.event, item.data)
        except AIServiceError as exc:
            yield _sse("error", {"detail": exc.public_message, "status": exc.status_code})
        except Exception:
            logger.exception("Unexpected error while streaming")
            yield _sse("error", {"detail": "Внутрішня помилка сервера.", "status": 500})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        # no-cache + вимкнення буферизації nginx, інакше кадри прийдуть пачкою в кінці.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/export", summary="Завантажити набір тест-кейсів (JSON / CSV / Zephyr / TestRail)")
def export(payload: ExportRequest) -> Response:
    result = export_suite(payload.suite, payload.format)
    filename = f"req2test_{payload.format.value}_{datetime.now():%Y%m%d_%H%M%S}.{result.extension}"
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
