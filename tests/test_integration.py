"""Против настоящего API. Запускаются, только если заданы PDFAPI_IT_KEY и PDFAPI_IT_BASE_URL
(отдельные имена: обычные PDFAPI_* остальные тесты специально очищают):

    PDFAPI_IT_KEY=pdf_live_... PDFAPI_IT_BASE_URL=http://localhost:18080/api pytest -m integration
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest

import pdfapi

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


@pytest.fixture
def client() -> Iterator[pdfapi.PdfApi]:
    key = os.environ.get("PDFAPI_IT_KEY")
    base = os.environ.get("PDFAPI_IT_BASE_URL")
    if not key or not base:
        pytest.skip("нужны PDFAPI_IT_KEY и PDFAPI_IT_BASE_URL")
    with pdfapi.PdfApi(key, base_url=base) as c:
        yield c


def test_html_to_pdf(client: pdfapi.PdfApi) -> None:
    pdf = client.html("<h1>Интеграционный тест</h1><div style='page-break-before:always'>2</div>")
    assert pdf.content.startswith(b"%PDF")
    assert pdf.pages == 2
    assert pdf.quota is not None and pdf.quota.used >= 2


def test_all_formats_and_save(client: pdfapi.PdfApi, tmp_path: Path) -> None:
    if not FIXTURES.exists():
        pytest.skip("нет sdk/tests/fixtures")
    results = [
        client.markdown("# Отчёт\n\n- пункт один\n- пункт два"),
        client.url("https://example.com", wait_delay="500ms"),
        client.office(FIXTURES / "report.docx"),
        client.office(FIXTURES / "table.xlsx", landscape=True),
        client.office((FIXTURES / "slides.pptx").read_bytes(), filename="slides.pptx"),
    ]
    for pdf in results:
        assert pdf.content.startswith(b"%PDF") and pdf.pages is not None and pdf.pages >= 1
    path = results[0].save(tmp_path / "out.pdf")
    assert path.read_bytes() == results[0].content


def test_me(client: pdfapi.PdfApi) -> None:
    me = client.me()
    assert me.plan in {"free", "premium", "business"}
    assert me.user_id and me.pages_limit > 0
    assert me.pages_used + me.pages_remaining == me.pages_limit
    assert me.period_start is not None and me.period_end is not None and me.period_end > me.period_start


def test_bad_key(client: pdfapi.PdfApi) -> None:
    with pytest.raises(pdfapi.AuthenticationError):
        pdfapi.PdfApi("pdf_live_wrong", base_url=client.base_url).html("<p>x</p>")


def test_options_rejected_by_server_come_back_as_invalid_request(client: pdfapi.PdfApi) -> None:
    with pytest.raises(pdfapi.InvalidRequestError) as info:
        client.convert({"source": "html", "html": "<p>x</p>", "options": {"foo": "bar"}})
    assert "foo" in info.value.message
