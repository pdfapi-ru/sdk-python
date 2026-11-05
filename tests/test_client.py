"""Поведение клиента, которого нет в общих кейсах: настройки, аргументы, файлы, сеть."""

from __future__ import annotations

import base64
import io
import json
import math
import os
from pathlib import Path

import httpx
import pytest

import pdfapi
from pdfapi import _models
from pdfapi._base import OFFICE_MAX_BYTES, ZIP_MAGIC

from .conftest import BASE_URL, KEY, async_client, scripted, sync_client

PDF = httpx.Response(200, headers={"x-pages-rendered": "1"}, content=b"%PDF-1.4")


# ------------------------------------------------------------------ настройки


def test_no_key_fails_at_construction_not_at_first_request() -> None:
    with pytest.raises(ValueError, match="PDFAPI_KEY"):
        pdfapi.PdfApi()


def test_key_and_base_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDFAPI_KEY", "pdf_live_from_env")
    monkeypatch.setenv("PDFAPI_BASE_URL", "http://localhost:18080/api/")
    client = pdfapi.PdfApi()
    assert client.base_url == "http://localhost:18080/api"  # слэш на конце срезан
    assert client._headers["Authorization"] == "Bearer pdf_live_from_env"


@pytest.mark.parametrize("kwargs", [
    {"timeout": 0}, {"timeout": -1}, {"timeout": math.nan}, {"timeout": math.inf}, {"timeout": True},
    {"max_retries": -1}, {"max_retries": 1.5}, {"max_retries": True},
])
def test_bad_client_settings_fail_at_construction(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        pdfapi.PdfApi(KEY, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        pdfapi.AsyncPdfApi(KEY, **kwargs)  # type: ignore[arg-type]


def test_per_call_timeout() -> None:
    seen: list[httpx.Request] = []
    client = sync_client(scripted([PDF], seen))
    client.html("<p>x</p>", timeout=5)
    assert seen[0].extensions["timeout"]["read"] == 5.0
    with pytest.raises(ValueError, match="timeout"):
        client.html("<p>x</p>", timeout=0)
    assert len(seen) == 1


def test_default_base_url() -> None:
    assert pdfapi.PdfApi(KEY).base_url == "https://pdfapi.ru/api"


def test_headers_sent() -> None:
    seen: list[httpx.Request] = []
    sync_client(scripted([PDF], seen)).html("<p>x</p>")
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert seen[0].headers["user-agent"].startswith(f"pdfapi-python/{pdfapi.__version__} (python ")
    assert str(seen[0].url) == f"{BASE_URL}/v1/convert"


def test_json_body_has_content_type_and_get_does_not() -> None:
    seen: list[httpx.Request] = []
    me = httpx.Response(200, json={"plan": "free", "usage": {}, "limits": {}})
    client = sync_client(scripted([PDF, me], seen))
    client.html("<p>Счёт</p>")
    client.me()
    assert seen[0].headers["content-type"] == "application/json; charset=utf-8"
    assert "<p>Счёт</p>" in seen[0].content.decode("utf-8")
    assert "content-type" not in seen[1].headers and seen[1].content == b""


def test_key_never_leaks_into_repr_or_errors() -> None:
    client = sync_client(scripted([httpx.Response(401, json={"error": "invalid_api_key"})], []))
    assert KEY not in repr(client)
    with pytest.raises(pdfapi.AuthenticationError) as info:
        client.html("<p>x</p>")
    assert KEY not in str(info.value) and KEY not in repr(info.value)


# ------------------------------------------------------------------ аргументы


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"margin_top": 20}, TypeError),           # число вместо "20mm"
        ({"margin_top": "  "}, ValueError),
        ({"margin_top": "20"}, ValueError),        # без единицы: мм? дюймы?
        ({"wait_delay": "11s"}, ValueError),       # больше 10 секунд
        ({"landscape": "yes"}, TypeError),
    ],
)
def test_bad_options_fail_before_request(kwargs: dict[str, object], error: type[Exception]) -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(error):
        sync_client(scripted([PDF], seen)).html("<p>x</p>", **kwargs)  # type: ignore[arg-type]
    assert seen == []


def test_empty_content_fails_before_request() -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(ValueError, match="пустое"):
        sync_client(scripted([PDF], seen)).markdown("   ")
    assert seen == []


def test_all_page_options_are_camel_case() -> None:
    seen: list[httpx.Request] = []
    sync_client(scripted([PDF], seen)).html(
        "<p>x</p>", landscape=False, paper_width="8.27in", paper_height="11.7in", margin_top="1mm",
        margin_bottom="2mm", margin_left="3mm", margin_right="4mm", wait_delay="500ms",
    )
    assert json.loads(seen[0].content)["options"] == {
        "landscape": False, "paperWidth": "8.27in", "paperHeight": "11.7in", "marginTop": "1mm",
        "marginBottom": "2mm", "marginLeft": "3mm", "marginRight": "4mm", "waitDelay": "500ms",
    }


# ------------------------------------------------------------------ office


def test_office_from_path(tmp_path: Path) -> None:
    doc = tmp_path / "Отчёт.docx"
    doc.write_bytes(b"PK\x03\x04docx")
    seen: list[httpx.Request] = []
    sync_client(scripted([PDF], seen)).office(doc, landscape=True)
    body = json.loads(seen[0].content)
    assert body == {"source": "office", "filename": "Отчёт.docx",
                    "fileBase64": base64.b64encode(b"PK\x03\x04docx").decode(), "options": {"landscape": True}}


def test_office_from_bytes_needs_filename() -> None:
    with pytest.raises(ValueError, match="filename"):
        sync_client(scripted([PDF], [])).office(b"PK\x03\x04")


def test_office_from_file_object() -> None:
    f = io.BytesIO(b"PK\x03\x04xlsx")
    f.name = "/tmp/table.xlsx"  # type: ignore[attr-defined]
    seen: list[httpx.Request] = []
    sync_client(scripted([PDF], seen)).office(f)
    assert json.loads(seen[0].content)["filename"] == "table.xlsx"


def test_office_rejects_other_extensions_and_big_files() -> None:
    seen: list[httpx.Request] = []
    client = sync_client(scripted([PDF], seen))
    with pytest.raises(ValueError, match="docx"):
        client.office(b"%PDF", filename="scan.pdf")
    with pytest.raises(ValueError, match="3,7 МБ"):
        client.office(ZIP_MAGIC + b"0" * OFFICE_MAX_BYTES, filename="big.pptx")
    assert seen == []


# ------------------------------------------------------------------ результат


def test_save_and_repr(tmp_path: Path) -> None:
    result = sync_client(scripted([PDF], [])).html("<p>x</p>")
    path = result.save(tmp_path / "out.pdf")
    assert path.read_bytes() == b"%PDF-1.4"
    assert bytes(result) == b"%PDF-1.4" and len(result) == 8
    assert "%PDF" not in repr(result)


def test_save_replaces_file_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "out.pdf"
    target.write_bytes(b"old content that is longer than the new one")
    pdfapi.PdfResult(b"%PDF-new", 1, None).save(target)
    assert target.read_bytes() == b"%PDF-new"
    assert [p.name for p in tmp_path.iterdir()] == ["out.pdf"]


def test_save_failure_keeps_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "out.pdf"
    target.write_bytes(b"%PDF-old")

    def broken_fsync(fd: int) -> None:
        raise OSError("диск отвалился")

    monkeypatch.setattr(_models.os, "fsync", broken_fsync)
    with pytest.raises(OSError, match="диск отвалился"):
        pdfapi.PdfResult(b"%PDF-new", 1, None).save(target)
    assert target.read_bytes() == b"%PDF-old"
    assert [p.name for p in tmp_path.iterdir()] == ["out.pdf"]


def test_save_permissions_like_a_normal_file(tmp_path: Path) -> None:
    umask = os.umask(0)
    os.umask(umask)
    path = pdfapi.PdfResult(b"%PDF", 1, None).save(tmp_path / "out.pdf")
    assert path.stat().st_mode & 0o777 == 0o666 & ~umask


def test_save_into_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        pdfapi.PdfResult(b"%PDF", 1, None).save(tmp_path / "нет" / "out.pdf")
    assert list(tmp_path.iterdir()) == []


# ------------------------------------------------------------------ сеть


def test_connection_error_before_sending_is_retried(sleeps: list[float]) -> None:
    seen: list[httpx.Request] = []
    client = sync_client(scripted([httpx.ConnectError("refused"), PDF], seen))
    assert client.html("<p>x</p>").pages == 1
    assert len(seen) == 2 and len(sleeps) == 1 and 0.375 <= sleeps[0] <= 0.625


def test_connection_error_after_retries_is_api_connection_error(sleeps: list[float]) -> None:
    seen: list[httpx.Request] = []
    client = sync_client(scripted([httpx.ConnectError("refused")], seen))
    with pytest.raises(pdfapi.APIConnectionError) as info:
        client.html("<p>x</p>")
    assert len(seen) == 3 and info.value.code == "connection_error"


@pytest.mark.parametrize("exc, cls", [
    (httpx.ReadTimeout("slow"), pdfapi.APITimeoutError),
    (httpx.RemoteProtocolError("dropped"), pdfapi.APIConnectionError),
])
def test_timeout_and_broken_response_are_not_retried(exc: Exception, cls: type[Exception],
                                                     sleeps: list[float]) -> None:
    # Сервер мог успеть отрендерить и списать страницы — повтор списал бы их дважды.
    seen: list[httpx.Request] = []
    with pytest.raises(cls):
        sync_client(scripted([exc, PDF], seen)).html("<p>x</p>")
    assert len(seen) == 1 and sleeps == []


def test_max_retries_zero(sleeps: list[float]) -> None:
    seen: list[httpx.Request] = []
    unavailable = httpx.Response(503, json={"error": "unavailable"})
    with pytest.raises(pdfapi.UnavailableError):
        sync_client(scripted([unavailable, PDF], seen), max_retries=0).html("<p>x</p>")
    assert len(seen) == 1


def test_own_http_client_is_closed_but_foreign_is_not() -> None:
    with pdfapi.PdfApi(KEY) as own:
        pass
    assert own._http.is_closed

    foreign = httpx.Client(transport=httpx.MockTransport(scripted([PDF], [])))
    with pdfapi.PdfApi(KEY, http_client=foreign):
        pass
    assert not foreign.is_closed


@pytest.mark.anyio
async def test_async_retry_and_close(sleeps: list[float]) -> None:
    seen: list[httpx.Request] = []
    async with async_client(scripted([httpx.ConnectError("refused"), PDF], seen)) as client:
        assert (await client.html("<p>x</p>")).pages == 1
    assert len(seen) == 2 and len(sleeps) == 1

    async with pdfapi.AsyncPdfApi(KEY) as own:
        pass
    assert own._http.is_closed
