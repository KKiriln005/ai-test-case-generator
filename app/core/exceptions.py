"""Доменні винятки. Кожен знає свій HTTP-статус і безпечне для клієнта повідомлення.

Внутрішні деталі (трейсбеки, тексти помилок SDK) пишуться лише в лог і клієнту не віддаються.
"""


class AIServiceError(Exception):
    status_code: int = 502
    public_message: str = "Не вдалося отримати відповідь від AI-сервісу."


class AIConfigError(AIServiceError):
    status_code = 500
    public_message = "Сервер налаштовано неправильно: перевірте ANTHROPIC_API_KEY і доступ до моделі."


class AIRateLimitError(AIServiceError):
    status_code = 429
    public_message = "Перевищено ліміт запитів до AI. Спробуйте ще раз за хвилину."


class AIUnavailableError(AIServiceError):
    status_code = 503
    public_message = "AI-сервіс тимчасово недоступний або не відповів вчасно. Спробуйте ще раз."


class AIRequestRejectedError(AIServiceError):
    status_code = 502
    public_message = "AI-сервіс відхилив запит. Спробуйте скоротити текст вимог."


class AIOutputError(AIServiceError):
    status_code = 502
    public_message = (
        "Модель повернула неповний або некоректний результат. "
        "Спробуйте зменшити кількість тест-кейсів або повторити запит."
    )
