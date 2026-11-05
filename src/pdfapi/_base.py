"""Общее для синхронного и асинхронного клиентов: настройки, тела запросов, повторы.

Сетевой части здесь нет — она в _client.py, своя у каждого клиента.
"""

from __future__ import annotations

import base64
import json
import math
import os
import platform
import random
import re
from pathlib import Path
from typing import IO, Any, Mapping, Optional, Union

import httpx

from ._errors import retry_after_seconds
from ._version import __version__

DEFAULT_BASE_URL = "https://pdfapi.ru/api"
DEFAULT_TIMEOUT = 40.0  # рендер — до 30 с, плюс запас на сеть и очередь
DEFAULT_MAX_RETRIES = 2
MAX_RETRY_AFTER = 60.0
# Тело запроса ограничено 5 МБ, а base64 раздувает файл на треть.
OFFICE_MAX_BYTES = 3_700_000
OFFICE_EXTENSIONS = (".docx", ".xlsx", ".pptx")
# docx, xlsx и pptx — ZIP-архивы, начинаются с «PK\x03\x04».
ZIP_MAGIC = b"PK\x03\x04"
# Число и единица, как понимает рендер. Без единицы сервер считает дюймами,
# но "20" почти всегда задумано как миллиметры.
_SIZE = re.compile(r"(\d+(\.\d*)?|\.\d+)(pt|px|in|mm|cm|pc)")
# waitDelay — как на сервере: число и s или ms, не больше 10 секунд.
_WAIT_DELAY = re.compile(r"(\d+(?:\.\d+)?)(ms|s)")
MAX_WAIT_DELAY = 10.0

FileInput = Union[str, "os.PathLike[str]", bytes, bytearray, IO[bytes]]

USER_AGENT = (
    f"pdfapi-python/{__version__} (python {platform.python_version()}; httpx {httpx.__version__})"
)


def resolve_settings(api_key: Optional[str], base_url: Optional[str]) -> tuple[str, str]:
    key = api_key if api_key is not None else os.environ.get("PDFAPI_KEY")
    if not key or not key.strip():
        raise ValueError(
            "Не задан ключ API: передайте api_key=... или задайте переменную окружения PDFAPI_KEY."
        )
    url = base_url or os.environ.get("PDFAPI_BASE_URL") or DEFAULT_BASE_URL
    return key.strip(), url.rstrip("/")


def check_timeout(timeout: float) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError(f"timeout: {timeout!r} — нужно число секунд больше нуля, например 40")
    return float(timeout)


def check_max_retries(max_retries: int) -> int:
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        raise ValueError(f"max_retries: {max_retries!r} — нужно целое число от 0")
    return max_retries


def default_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
        "Accept": "application/pdf, application/json",
    }


JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}


def encode_json(body: Optional[Mapping[str, Any]]) -> Optional[bytes]:
    """JSON в UTF-8 без \\uXXXX: русский HTML в экранированном виде вырос бы втрое
    и раньше упёрся бы в лимит тела 5 МБ (httpx по умолчанию экранирует)."""
    if body is None:
        return None
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# ------------------------------------------------------------------ тела запросов

_OPTION_NAMES = {
    "paper_width": "paperWidth",
    "paper_height": "paperHeight",
    "margin_top": "marginTop",
    "margin_bottom": "marginBottom",
    "margin_left": "marginLeft",
    "margin_right": "marginRight",
    "wait_delay": "waitDelay",
}


def page_options(landscape: Optional[bool] = None, **sizes: Optional[str]) -> dict[str, Any]:
    """snake_case → camelCase API. В тело уходят только заданные параметры."""
    out: dict[str, Any] = {}
    if landscape is not None:
        if not isinstance(landscape, bool):
            raise TypeError("landscape: ожидается True или False")
        out["landscape"] = landscape
    for name, value in sizes.items():
        if value is None:
            continue
        if not isinstance(value, str):
            # Число тут почти наверняка ошибка: 20 — это мм? пиксели? Лучше сказать сразу.
            raise TypeError(f'{name}: ожидается строка с единицами, например "20mm" или "2s"')
        if name == "wait_delay":
            match = _WAIT_DELAY.fullmatch(value)
            seconds = float(match[1]) / (1000 if match[2] == "ms" else 1) if match else None
            if seconds is None or seconds > MAX_WAIT_DELAY:
                raise ValueError(f'wait_delay: "{value}" — нужно от 0 до 10 секунд в s или ms, например "2s" или "500ms"')
        elif not _SIZE.fullmatch(value):
            # Иначе рендер падает с 502, и опечатка выглядит как сбой сервиса.
            raise ValueError(
                f'{name}: "{value}" — нужно число с единицами pt, px, in, mm, cm или pc без пробела, например "20mm"'
            )
        out[_OPTION_NAMES[name]] = value
    return out


def text_body(source: str, value: str, options: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: пустое содержимое")
    if source == "url":
        value = value.strip()  # пробелы по краям рендер не прощает
        if not re.match(r"https?://\S", value, re.IGNORECASE):
            raise ValueError(f'url: "{value}" — нужен полный адрес с http:// или https://, например https://example.com')
    body: dict[str, Any] = {"source": source, source: value}
    if options:
        body["options"] = dict(options)
    return body


def office_body(file: FileInput, filename: Optional[str], landscape: Optional[bool]) -> dict[str, Any]:
    if isinstance(file, (bytes, bytearray)):
        data = bytes(file)
    elif isinstance(file, (str, os.PathLike)):
        path = Path(file)
        data = path.read_bytes()
        filename = filename or path.name
    elif hasattr(file, "read"):
        data = file.read()
        filename = filename or Path(getattr(file, "name", "") or "").name or None
    else:
        raise TypeError("file: путь, bytes или открытый файл в режиме 'rb'")

    if not filename:
        raise ValueError("filename: укажите имя файла с расширением, например filename='report.docx'")
    if not filename.lower().endswith(OFFICE_EXTENSIONS):
        raise ValueError(f"{filename}: поддерживаются только .docx, .xlsx и .pptx")
    if not data:
        raise ValueError(f"{filename}: файл пустой")
    if not data.startswith(ZIP_MAGIC):
        # Старый .doc, PDF или картинка с чужим расширением: сервер всё равно отклонит.
        raise ValueError(f"{filename}: не похож на docx, xlsx или pptx — это не ZIP-архив")
    if len(data) > OFFICE_MAX_BYTES:
        raise ValueError(
            f"{filename}: {len(data) / 1_000_000:.1f} МБ — больше предела 3,7 МБ "
            "(после base64 тело запроса превысило бы 5 МБ)"
        )
    body: dict[str, Any] = {
        "source": "office",
        "filename": filename,
        "fileBase64": base64.b64encode(data).decode("ascii"),
    }
    options = page_options(landscape=landscape)
    if options:
        body["options"] = options
    return body


# ------------------------------------------------------------------ повторы


def backoff(attempt: int) -> float:
    """0,5 → 1 → 2 с … с разбросом ±25%, чтобы клиенты не били хором."""
    return 0.5 * (2.0 ** attempt) * random.uniform(0.75, 1.25)


def retry_delay(attempt: int, status: int, headers: Mapping[str, str], body: bytes) -> Optional[float]:
    """Через сколько повторить ответ со статусом ``status``; ``None`` — не повторять.

    Повторяются только 429 (по Retry-After или ``retry_after_sec``) и 503: в обоих
    случаях сервер ничего не сделал и страниц не списал.
    """
    if status == 429:
        after = retry_after_seconds(headers, body)
        return min(after if after is not None else backoff(attempt), MAX_RETRY_AFTER)
    if status == 503:
        return backoff(attempt)
    return None


# Ошибки, при которых запрос точно не ушёл на сервер, — их безопасно повторить.
# Таймаут чтения и обрыв посреди ответа не повторяются: сервер мог успеть
# отрендерить и списать страницы, повтор списал бы их второй раз.
SAFE_TO_RETRY = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
