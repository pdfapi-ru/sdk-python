"""Официальный Python SDK pdfapi: HTML, URL, Markdown и Office в PDF одним вызовом.

    from pdfapi import PdfApi

    client = PdfApi()  # ключ из переменной окружения PDFAPI_KEY
    pdf = client.html("<h1>Счёт №42</h1>", margin_top="20mm")
    pdf.save("invoice.pdf")
    print(pdf.pages, pdf.quota.remaining)

Документация: https://pdfapi.ru/docs
"""

from ._client import AsyncPdfApi, PdfApi
from ._errors import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    InvalidRequestError,
    PayloadTooLargeError,
    PdfApiError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitError,
    RenderError,
    RenderTimeoutError,
    UnavailableError,
)
from ._models import Account, PdfResult, Quota
from ._version import __version__

__all__ = [
    "PdfApi",
    "AsyncPdfApi",
    "PdfResult",
    "Quota",
    "Account",
    "PdfApiError",
    "AuthenticationError",
    "PermissionDeniedError",
    "QuotaExceededError",
    "InvalidRequestError",
    "PayloadTooLargeError",
    "RateLimitError",
    "RenderError",
    "RenderTimeoutError",
    "UnavailableError",
    "APIConnectionError",
    "APITimeoutError",
    "__version__",
]
