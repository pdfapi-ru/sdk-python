"""Результаты вызовов: PDF с числом страниц и квотой, сведения об аккаунте."""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Union


@dataclass(frozen=True)
class Quota:
    """Квота периода после этой конвертации — из заголовков X-Quota-*."""

    limit: int
    used: int
    remaining: int


@dataclass(frozen=True)
class PdfResult:
    """Готовый PDF.

    ``content`` — байты файла, ``pages`` — сколько страниц списано,
    ``quota`` — остаток квоты. Если сервер не прислал заголовки — ``None``.
    """

    content: bytes
    pages: Optional[int]
    quota: Optional[Quota]

    def save(self, path: Union[str, "os.PathLike[str]"]) -> Path:
        """Записать PDF в файл и вернуть путь.

        Атомарно: сначала во временный файл рядом, затем переименование поверх —
        оборвётся запись, на месте останется прежний файл, а не обрезанный PDF.
        Каталог не создаётся.
        """
        target = Path(path)
        tmp = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
        try:
            # «x» — только новый файл; права как у обычного, с учётом umask.
            with open(tmp, "xb") as f:
                f.write(self.content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except BaseException:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            raise
        return target

    def __len__(self) -> int:
        return len(self.content)

    def __bytes__(self) -> bytes:
        return self.content

    def __repr__(self) -> str:  # байты PDF в repr не нужны
        return f"PdfResult(pages={self.pages!r}, size={len(self.content)} B, quota={self.quota!r})"


@dataclass(frozen=True)
class Account:
    """Тариф и расход — ответ ``GET /v1/me``.

    ``period_start`` и ``period_end`` — в UTC; ``period_end`` — когда счётчик
    страниц начнётся с нуля. ``None`` — сервер не сообщил.
    """

    user_id: str
    plan: str
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    pages_used: int
    pages_limit: int
    pages_remaining: int
    requests_per_second: float
    burst: int


def _int_header(headers: Mapping[str, str], name: str) -> Optional[int]:
    try:
        return int(headers[name])
    except (KeyError, ValueError):
        return None


def result_from_response(headers: Mapping[str, str], content: bytes) -> PdfResult:
    limit = _int_header(headers, "x-quota-limit")
    used = _int_header(headers, "x-quota-used")
    remaining = _int_header(headers, "x-quota-remaining")
    quota = Quota(limit, used, remaining) if limit is not None and used is not None and remaining is not None else None
    return PdfResult(content=content, pages=_int_header(headers, "x-pages-rendered"), quota=quota)


def _datetime(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    # До Python 3.11 fromisoformat не понимает «Z».
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def account_from_json(data: Mapping[str, object]) -> Account:
    usage = data.get("usage")
    limits = data.get("limits")
    usage = usage if isinstance(usage, dict) else {}
    limits = limits if isinstance(limits, dict) else {}
    # Старый API присылал только дату начала — «2026-10-01», это полночь UTC.
    period = data.get("period")
    legacy_start = f"{period}T00:00:00Z" if isinstance(period, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", period) else None
    return Account(
        user_id=str(data.get("user_id", "")),
        plan=str(data.get("plan", "")),
        period_start=_datetime(data.get("period_start")) or _datetime(legacy_start),
        period_end=_datetime(data.get("period_end")),
        pages_used=int(usage.get("pages_used", 0)),
        pages_limit=int(usage.get("pages_limit", 0)),
        pages_remaining=int(usage.get("pages_remaining", 0)),
        requests_per_second=float(limits.get("requests_per_second", 0)),
        burst=int(limits.get("burst", 0)),
    )
