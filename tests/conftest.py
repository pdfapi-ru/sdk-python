from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

import pdfapi
from pdfapi import _client

CASES_FILE = Path(__file__).resolve().parents[2] / "tests" / "cases.json"
BASE_URL = "https://pdfapi.test/api"
KEY = "pdf_live_secret_test_key_123"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тесты не должны зависеть от PDFAPI_* в окружении разработчика."""
    monkeypatch.delenv("PDFAPI_KEY", raising=False)
    monkeypatch.delenv("PDFAPI_BASE_URL", raising=False)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Сон между повторами не ждём, а записываем."""
    recorded: list[float] = []

    async def fake_async_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(_client, "_sleep", recorded.append)
    monkeypatch.setattr(_client, "_async_sleep", fake_async_sleep)
    return recorded


def load_cases() -> list[dict[str, Any]]:
    # В sdist общих кейсов нет (они уровнем выше, в sdk/tests) — тогда пропускаем.
    if not CASES_FILE.exists():
        return []
    return json.loads(CASES_FILE.read_text("utf-8"))["cases"]


def response_from_spec(spec: dict[str, Any]) -> httpx.Response:
    headers = dict(spec.get("headers", {}))
    if "json" in spec:
        return httpx.Response(spec["status"], headers=headers, json=spec["json"])
    if "text" in spec:
        return httpx.Response(spec["status"], headers=headers, text=spec["text"])
    return httpx.Response(spec["status"], headers=headers, content=base64.b64decode(spec.get("body_base64", "")))


def scripted(responses: list[Any], seen: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    """Обработчик MockTransport: отвечает по очереди; исключение в списке — бросает его."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = responses[min(len(seen) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            # Свежая копия: один и тот же ответ могут отдавать и sync-, и async-тесты.
            return httpx.Response(item.status_code, headers=item.headers, content=item.content)
        return response_from_spec(item)

    return handler


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def sync_client(handler: Callable[[httpx.Request], httpx.Response], **kw: Any) -> pdfapi.PdfApi:
    return pdfapi.PdfApi(KEY, base_url=BASE_URL, http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def async_client(handler: Callable[[httpx.Request], httpx.Response], **kw: Any) -> pdfapi.AsyncPdfApi:
    return pdfapi.AsyncPdfApi(
        KEY, base_url=BASE_URL, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw
    )
