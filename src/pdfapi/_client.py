"""Клиенты pdfapi: синхронный PdfApi и асинхронный AsyncPdfApi.

Методы у них одинаковые; отличается только транспорт (httpx.Client и
httpx.AsyncClient). Вся логика, не связанная с сетью, — в _base.py.
"""

from __future__ import annotations

import time
from typing import Any, Mapping, Optional

import anyio
import httpx

from ._base import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    JSON_HEADERS,
    SAFE_TO_RETRY,
    FileInput,
    backoff,
    check_max_retries,
    check_timeout,
    default_headers,
    encode_json,
    office_body,
    page_options,
    resolve_settings,
    retry_delay,
    text_body,
)
from ._errors import APIConnectionError, APITimeoutError, PdfApiError, error_from_response
from ._models import Account, PdfResult, account_from_json, result_from_response

# Сон между повторами — отдельными именами, чтобы тесты могли его подменить.
_sleep = time.sleep
_async_sleep = anyio.sleep


def _transport_error(exc: Exception, base_url: str, timeout: float) -> PdfApiError:
    if isinstance(exc, httpx.TimeoutException):
        return APITimeoutError(
            f"API не ответил за {timeout:g} с. Запрос мог быть выполнен — повторять его "
            "автоматически небезопасно: страницы списались бы дважды.",
            code="timeout",
        )
    return APIConnectionError(f"Нет связи с {base_url}: {exc}", code="connection_error")


class PdfApi:
    """Клиент pdfapi.

    >>> from pdfapi import PdfApi
    >>> client = PdfApi()                      # ключ из PDFAPI_KEY
    >>> pdf = client.html("<h1>Счёт №42</h1>")
    >>> pdf.save("invoice.pdf")

    :param api_key: ключ API; по умолчанию — переменная окружения ``PDFAPI_KEY``.
    :param base_url: адрес API; по умолчанию ``PDFAPI_BASE_URL`` или ``https://pdfapi.ru/api``.
    :param timeout: таймаут одного запроса, секунд. У каждого метода есть и свой ``timeout=`` — для одного вызова.
    :param max_retries: сколько раз повторять 429, 503 и ошибки соединения.
    :param http_client: свой ``httpx.Client`` (прокси, сертификаты). Закрывать его — ваша забота.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self._api_key, self.base_url = resolve_settings(api_key, base_url)
        self.timeout = check_timeout(timeout)
        self.max_retries = check_max_retries(max_retries)
        self._headers = default_headers(self._api_key)
        self._own_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)

    # ------------------------------------------------------------- конвертация

    def html(
        self,
        html: str,
        *,
        landscape: Optional[bool] = None,
        paper_width: Optional[str] = None,
        paper_height: Optional[str] = None,
        margin_top: Optional[str] = None,
        margin_bottom: Optional[str] = None,
        margin_left: Optional[str] = None,
        margin_right: Optional[str] = None,
        wait_delay: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> PdfResult:
        """HTML → PDF. Размеры — строками с единицами: ``"20mm"``, ``"8.27in"``; ``wait_delay="2s"``."""
        options = page_options(landscape, paper_width=paper_width, paper_height=paper_height,
                               margin_top=margin_top, margin_bottom=margin_bottom,
                               margin_left=margin_left, margin_right=margin_right, wait_delay=wait_delay)
        return self.convert(text_body("html", html, options), timeout=timeout)

    def url(
        self,
        url: str,
        *,
        landscape: Optional[bool] = None,
        paper_width: Optional[str] = None,
        paper_height: Optional[str] = None,
        margin_top: Optional[str] = None,
        margin_bottom: Optional[str] = None,
        margin_left: Optional[str] = None,
        margin_right: Optional[str] = None,
        wait_delay: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> PdfResult:
        """Страница по публичному адресу → PDF (тариф premium и выше)."""
        options = page_options(landscape, paper_width=paper_width, paper_height=paper_height,
                               margin_top=margin_top, margin_bottom=margin_bottom,
                               margin_left=margin_left, margin_right=margin_right, wait_delay=wait_delay)
        return self.convert(text_body("url", url, options), timeout=timeout)

    def markdown(
        self,
        markdown: str,
        *,
        landscape: Optional[bool] = None,
        paper_width: Optional[str] = None,
        paper_height: Optional[str] = None,
        margin_top: Optional[str] = None,
        margin_bottom: Optional[str] = None,
        margin_left: Optional[str] = None,
        margin_right: Optional[str] = None,
        wait_delay: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> PdfResult:
        """Markdown → PDF (тариф premium и выше)."""
        options = page_options(landscape, paper_width=paper_width, paper_height=paper_height,
                               margin_top=margin_top, margin_bottom=margin_bottom,
                               margin_left=margin_left, margin_right=margin_right, wait_delay=wait_delay)
        return self.convert(text_body("markdown", markdown, options), timeout=timeout)

    def office(self, file: FileInput, *, filename: Optional[str] = None,
               landscape: Optional[bool] = None, timeout: Optional[float] = None) -> PdfResult:
        """docx, xlsx или pptx → PDF. ``file`` — путь, bytes или открытый файл (``'rb'``).

        Для bytes нужно ``filename`` — по расширению сервер понимает формат.
        """
        return self.convert(office_body(file, filename, landscape), timeout=timeout)

    def convert(self, body: Mapping[str, Any], *, timeout: Optional[float] = None) -> PdfResult:
        """Низкоуровневый вызов ``POST /v1/convert`` с телом как есть."""
        response = self._send("POST", "/v1/convert", dict(body), timeout)
        return result_from_response(response.headers, response.content)

    def me(self, *, timeout: Optional[float] = None) -> Account:
        """Тариф, расход и остаток страниц в текущем периоде."""
        return account_from_json(self._send("GET", "/v1/me", None, timeout).json())

    # ------------------------------------------------------------- сеть

    def _request_headers(self, body: Optional[dict[str, Any]]) -> dict[str, str]:
        return {**self._headers, **JSON_HEADERS} if body is not None else self._headers

        def _send(self, method: str, path: str, json: Optional[dict[str, Any]] = None,
                    timeout: Optional[float] = None) -> httpx.Response:
        timeout = self.timeout if timeout is None else check_timeout(timeout)
        attempt = 0
        while True:
            try:
                response = self._http.request(method, self.base_url + path, content=encode_json(json),
                                              headers=self._request_headers(json), timeout=timeout)
            except SAFE_TO_RETRY as exc:
                if attempt < self.max_retries:
                    _sleep(backoff(attempt))
                    attempt += 1
                    continue
                raise _transport_error(exc, self.base_url, timeout) from exc
            except httpx.TransportError as exc:
                raise _transport_error(exc, self.base_url, timeout) from exc

            if response.is_success:
                return response
            delay = retry_delay(attempt, response.status_code, response.headers, response.content)
            if delay is not None and attempt < self.max_retries:
                _sleep(delay)
                attempt += 1
                continue
            raise error_from_response(response.status_code, response.headers, response.content)

    def close(self) -> None:
        if self._own_http:
            self._http.close()

    def __enter__(self) -> "PdfApi":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:  # ключ — никогда
        return f"PdfApi(base_url={self.base_url!r})"


class AsyncPdfApi:
    """Асинхронный клиент pdfapi — те же методы, что у :class:`PdfApi`, но ``async``.

    >>> async with AsyncPdfApi() as client:
    ...     pdf = await client.html("<h1>Отчёт</h1>")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._api_key, self.base_url = resolve_settings(api_key, base_url)
        self.timeout = check_timeout(timeout)
        self.max_retries = check_max_retries(max_retries)
        self._headers = default_headers(self._api_key)
        self._own_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)

    async def html(
        self,
        html: str,
        *,
        landscape: Optional[bool] = None,
        paper_width: Optional[str] = None,
        paper_height: Optional[str] = None,
        margin_top: Optional[str] = None,
        margin_bottom: Optional[str] = None,
        margin_left: Optional[str] = None,
        margin_right: Optional[str] = None,
        wait_delay: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> PdfResult:
        """HTML → PDF. См. :meth:`PdfApi.html`."""
        options = page_options(landscape, paper_width=paper_width, paper_height=paper_height,
                               margin_top=margin_top, margin_bottom=margin_bottom,
                               margin_left=margin_left, margin_right=margin_right, wait_delay=wait_delay)
        return await self.convert(text_body("html", html, options), timeout=timeout)

    async def url(
        self,
        url: str,
        *,
        landscape: Optional[bool] = None,
        paper_width: Optional[str] = None,
        paper_height: Optional[str] = None,
        margin_top: Optional[str] = None,
        margin_bottom: Optional[str] = None,
        margin_left: Optional[str] = None,
        margin_right: Optional[str] = None,
        wait_delay: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> PdfResult:
        """Страница по адресу → PDF. См. :meth:`PdfApi.url`."""
        options = page_options(landscape, paper_width=paper_width, paper_height=paper_height,
                               margin_top=margin_top, margin_bottom=margin_bottom,
                               margin_left=margin_left, margin_right=margin_right, wait_delay=wait_delay)
        return await self.convert(text_body("url", url, options), timeout=timeout)

    async def markdown(
        self,
        markdown: str,
        *,
        landscape: Optional[bool] = None,
        paper_width: Optional[str] = None,
        paper_height: Optional[str] = None,
        margin_top: Optional[str] = None,
        margin_bottom: Optional[str] = None,
        margin_left: Optional[str] = None,
        margin_right: Optional[str] = None,
        wait_delay: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> PdfResult:
        """Markdown → PDF. См. :meth:`PdfApi.markdown`."""
        options = page_options(landscape, paper_width=paper_width, paper_height=paper_height,
                               margin_top=margin_top, margin_bottom=margin_bottom,
                               margin_left=margin_left, margin_right=margin_right, wait_delay=wait_delay)
        return await self.convert(text_body("markdown", markdown, options), timeout=timeout)

    async def office(self, file: FileInput, *, filename: Optional[str] = None,
                     landscape: Optional[bool] = None, timeout: Optional[float] = None) -> PdfResult:
        """docx, xlsx или pptx → PDF. Файл читается синхронно: он не больше 3,7 МБ."""
        return await self.convert(office_body(file, filename, landscape), timeout=timeout)

    async def convert(self, body: Mapping[str, Any], *, timeout: Optional[float] = None) -> PdfResult:
        response = await self._send("POST", "/v1/convert", dict(body), timeout)
        return result_from_response(response.headers, response.content)

    async def me(self, *, timeout: Optional[float] = None) -> Account:
        return account_from_json((await self._send("GET", "/v1/me", None, timeout)).json())

    def _request_headers(self, body: Optional[dict[str, Any]]) -> dict[str, str]:
        return {**self._headers, **JSON_HEADERS} if body is not None else self._headers

    async def _send(self, method: str, path: str, json: Optional[dict[str, Any]] = None,
                    timeout: Optional[float] = None) -> httpx.Response:
        timeout = self.timeout if timeout is None else check_timeout(timeout)
        attempt = 0
        while True:
            try:
                response = await self._http.request(method, self.base_url + path, content=encode_json(json),
                                                    headers=self._request_headers(json), timeout=timeout)
            except SAFE_TO_RETRY as exc:
                if attempt < self.max_retries:
                    await _async_sleep(backoff(attempt))
                    attempt += 1
                    continue
                raise _transport_error(exc, self.base_url, timeout) from exc
            except httpx.TransportError as exc:
                raise _transport_error(exc, self.base_url, timeout) from exc

            if response.is_success:
                return response
            delay = retry_delay(attempt, response.status_code, response.headers, response.content)
            if delay is not None and attempt < self.max_retries:
                await _async_sleep(delay)
                attempt += 1
                continue
            raise error_from_response(response.status_code, response.headers, response.content)

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()

    async def __aenter__(self) -> "AsyncPdfApi":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"AsyncPdfApi(base_url={self.base_url!r})"
