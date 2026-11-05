"""Ошибки pdfapi. Все ошибки API — наследники PdfApiError (см. sdk/SPEC.md)."""

from __future__ import annotations

import json
import re
from typing import Mapping, Optional


class PdfApiError(Exception):
    """Ошибка pdfapi: код из ответа API (``code``), HTTP-статус и текст."""

    def __init__(self, message: str, *, code: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status

    def __str__(self) -> str:
        where = f"HTTP {self.status}, " if self.status else ""
        return f"{self.message} ({where}{self.code})"

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, status={self.status!r}, message={self.message!r})"


class AuthenticationError(PdfApiError):
    """401: ключа нет или он неверный/отозван."""


class PermissionDeniedError(PdfApiError):
    """403: почта не подтверждена или формат недоступен на тарифе."""


class QuotaExceededError(PdfApiError):
    """402: лимит страниц периода исчерпан или документ больше остатка."""


class InvalidRequestError(PdfApiError):
    """400: неверный запрос, параметр или запрещённый адрес."""


class PayloadTooLargeError(InvalidRequestError):
    """413: тело запроса больше 5 МБ."""


class RateLimitError(PdfApiError):
    """429: слишком часто. ``retry_after`` — через сколько секунд можно снова."""

    def __init__(self, message: str, *, code: str, status: Optional[int] = None,
                 retry_after: Optional[float] = None) -> None:
        super().__init__(message, code=code, status=status)
        self.retry_after = retry_after


class RenderError(PdfApiError):
    """502: документ не отрендерился — обычно дело в разметке."""


class RenderTimeoutError(RenderError):
    """504: рендер не уложился в 30 секунд."""


class UnavailableError(PdfApiError):
    """503: рендер временно недоступен или очередь полна."""


class APIConnectionError(PdfApiError):
    """Нет связи с API: сеть, DNS, обрыв соединения."""


class APITimeoutError(APIConnectionError):
    """API не ответил за отведённое время."""


_BY_CODE: dict[str, type[PdfApiError]] = {
    "missing_api_key": AuthenticationError,
    "invalid_api_key": AuthenticationError,
    "email_not_verified": PermissionDeniedError,
    "source_not_allowed": PermissionDeniedError,
    "quota_exceeded": QuotaExceededError,
    "invalid_request": InvalidRequestError,
    "url_not_allowed": InvalidRequestError,
    "payload_too_large": PayloadTooLargeError,
    "rate_limit_exceeded": RateLimitError,
    "render_failed": RenderError,
    "render_timeout": RenderTimeoutError,
    "unavailable": UnavailableError,
}

# Ответ не от API (Caddy отдаёт 413 текстом, прокси — 502 в HTML, сайт — 404
# страницей, Fastify — {"error": "Bad Request"}) — код по статусу.
_CODE_BY_STATUS = {
    400: "invalid_request",
    401: "invalid_api_key",
    402: "quota_exceeded",
    403: "source_not_allowed",
    404: "not_found",
    413: "payload_too_large",
    429: "rate_limit_exceeded",
    502: "render_failed",
    503: "unavailable",
    504: "render_timeout",
}

_MESSAGES = {
    "missing_api_key": "Не передан ключ API.",
    "invalid_api_key": "Неверный или отозванный ключ API.",
    "email_not_verified": "Почта аккаунта не подтверждена.",
    "source_not_allowed": "Этот формат недоступен на вашем тарифе.",
    "quota_exceeded": "Лимит страниц исчерпан.",
    "invalid_request": "Некорректный запрос.",
    "url_not_allowed": "Адрес ведёт во внутреннюю сеть и запрещён.",
    "payload_too_large": "Тело запроса больше 5 МБ.",
    "rate_limit_exceeded": "Слишком много запросов.",
    "render_failed": "Не удалось создать PDF.",
    "render_timeout": "Рендер не уложился в 30 секунд.",
    "unavailable": "Сервис временно недоступен.",
    "server_error": "Внутренняя ошибка сервера.",
    "not_found": "Адрес не найден (HTTP 404). Проверьте базовый адрес: он ведёт на API, например https://pdfapi.ru/api.",
}

# Код API — «quota_exceeded», а не название статуса вроде «Bad Request».
_API_CODE = re.compile(r"[a-z][a-z0-9_]*")


def parse_retry_after(headers: Mapping[str, str]) -> Optional[float]:
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # дата в HTTP-формате — API так не отвечает


def _parse_body(body: bytes) -> dict[str, object]:
    try:
        parsed = json.loads(body.decode("utf-8")) if body else {}
    except (ValueError, UnicodeDecodeError):
        return {}  # не JSON — разберёмся по статусу
    return parsed if isinstance(parsed, dict) else {}


def retry_after_seconds(headers: Mapping[str, str], body: bytes) -> Optional[float]:
    """Через сколько секунд можно снова: заголовок Retry-After, иначе ``retry_after_sec`` из тела."""
    after = parse_retry_after(headers)
    if after is not None:
        return after
    value = _parse_body(body).get("retry_after_sec")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return None


def error_from_response(status: int, headers: Mapping[str, str], body: bytes) -> PdfApiError:
    """Ответ API с ошибкой → исключение нужного класса (таблица в sdk/SPEC.md)."""
    data = _parse_body(body)
    code = data.get("error")
    if not isinstance(code, str) or not _API_CODE.fullmatch(code):
        code = _CODE_BY_STATUS.get(status, "server_error" if status >= 500 else "unknown_error")
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        message = _MESSAGES.get(code, f"Ошибка API (HTTP {status}).")

    cls = _BY_CODE.get(code, PdfApiError)
    if cls is RateLimitError:
        return RateLimitError(message, code=code, status=status, retry_after=retry_after_seconds(headers, body))
    return cls(message, code=code, status=status)
