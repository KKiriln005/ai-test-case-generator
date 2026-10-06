"""Доменные исключения. Каждое знает свой HTTP-статус и безопасное для клиента сообщение.

Внутренние детали (трейсбеки, тексты ошибок SDK) пишутся только в лог и клиенту не отдаются.
"""


class AIServiceError(Exception):
    status_code: int = 502
    public_message: str = "Не удалось получить ответ от AI-сервиса."


class AIConfigError(AIServiceError):
    status_code = 500
    public_message = "Сервер настроен неверно: проверьте ANTHROPIC_API_KEY и доступ к модели."


class AIRateLimitError(AIServiceError):
    status_code = 429
    public_message = "Превышен лимит запросов к AI. Повторите попытку через минуту."


class AIUnavailableError(AIServiceError):
    status_code = 503
    public_message = "AI-сервис временно недоступен или не ответил вовремя. Попробуйте ещё раз."


class AIRequestRejectedError(AIServiceError):
    status_code = 502
    public_message = "AI-сервис отклонил запрос. Попробуйте сократить текст требований."


class AIOutputError(AIServiceError):
    status_code = 502
    public_message = (
        "Модель вернула неполный или некорректный результат. "
        "Попробуйте уменьшить число тест-кейсов или повторить запрос."
    )
