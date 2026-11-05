"""Общие тест-кейсы SDK (sdk/tests/cases.json) — для синхронного и асинхронного клиентов."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any

import httpx
import pytest

import pdfapi

from .conftest import async_client, load_cases, scripted, snake, sync_client

CASES = load_cases()


def call_args(case: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    call = case["call"]
    kwargs = dict(call["args"])
    if call["method"] == "office":
        kwargs["file"] = base64.b64decode(kwargs.pop("file_base64"))
    kwargs.update({snake(k): v for k, v in call.get("options", {}).items()})
    return call["method"], kwargs


def as_datetime(value: Any) -> Any:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value


def check(case: dict[str, Any], outcome: Any, seen: list[httpx.Request], sleeps: list[float]) -> None:
    expect = case["expect"]
    assert len(seen) == expect["attempts"], f"попыток: {len(seen)}"

    if "request" in expect:
        req = seen[0]
        assert req.method == expect["request"]["method"]
        assert req.url.path.endswith(expect["request"]["path"])
        if "json" in expect["request"]:
            assert json.loads(req.content) == expect["request"]["json"]
        if "raw_contains" in expect["request"]:
            assert expect["request"]["raw_contains"] in req.content.decode("utf-8")

    if "result" in expect:
        assert isinstance(outcome, pdfapi.PdfResult), outcome
        want = expect["result"]
        assert outcome.content == base64.b64decode(want["content_base64"])
        assert outcome.pages == want["pages"]
        if want["quota"] is None:
            assert outcome.quota is None
        else:
            assert outcome.quota == pdfapi.Quota(**want["quota"])

    if "me" in expect:
        assert isinstance(outcome, pdfapi.Account)
        for field, value in expect["me"].items():
            want = as_datetime(value) if field.startswith("period_") else value
            assert getattr(outcome, field) == want, field

    if "argument_error" in expect:
        # Ошибка языка, а не API: запрос не ушёл.
        assert isinstance(outcome, (ValueError, TypeError)), f"ждали ошибку аргумента, получили {outcome!r}"
        assert expect["argument_error"]["mentions"].lower() in str(outcome).lower(), str(outcome)

    if "error" in expect:
        want = expect["error"]
        assert isinstance(outcome, pdfapi.PdfApiError), f"ждали ошибку, получили {outcome!r}"
        assert type(outcome).__name__ == want["class"]
        assert outcome.code == want["code"]
        assert outcome.status == want["status"]
        if "message_contains" in want:
            assert want["message_contains"] in outcome.message
        if "retry_after" in want:
            assert isinstance(outcome, pdfapi.RateLimitError)
            assert outcome.retry_after == want["retry_after"]

    if "sleeps" in expect:
        assert sleeps == expect["sleeps"]
    if "sleeps_between" in expect:
        low, high = expect["sleeps_between"]
        assert sleeps and all(low <= s <= high for s in sleeps), sleeps


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_sync(case: dict[str, Any], sleeps: list[float]) -> None:
    seen: list[httpx.Request] = []
    method, kwargs = call_args(case)
    with sync_client(scripted(case["responses"], seen)) as client:
        try:
            outcome: Any = getattr(client, method)(**kwargs)
        except (pdfapi.PdfApiError, ValueError, TypeError) as exc:
            outcome = exc
    check(case, outcome, seen, sleeps)


@pytest.mark.anyio
@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
async def test_async(case: dict[str, Any], sleeps: list[float]) -> None:
    seen: list[httpx.Request] = []
    method, kwargs = call_args(case)
    async with async_client(scripted(case["responses"], seen)) as client:
        try:
            outcome: Any = await getattr(client, method)(**kwargs)
        except (pdfapi.PdfApiError, ValueError, TypeError) as exc:
            outcome = exc
    check(case, outcome, seen, sleeps)
