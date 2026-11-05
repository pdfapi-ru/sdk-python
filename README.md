# pdfapi — Python SDK

Официальная библиотека [pdfapi](https://pdfapi.ru): HTML, страница по адресу, Markdown или docx/xlsx/pptx — в PDF одним вызовом. Синхронный и асинхронный клиенты, понятные исключения, повторы при перегрузке. Python 3.9+, одна зависимость — `httpx`.

```bash
pip install pdfapi
```

```python
from pdfapi import PdfApi

client = PdfApi()  # ключ берётся из переменной окружения PDFAPI_KEY

pdf = client.html("<h1>Счёт №42</h1><p>К оплате: 12 000 ₽</p>", margin_top="20mm")
pdf.save("invoice.pdf")

print(pdf.pages)    # 1 — сколько страниц списано
print(pdf.quota)    # Quota(limit=10000, used=143, remaining=9857) — остаток периода
```

Ключ выпускается в кабинете на [pdfapi.ru](https://pdfapi.ru). Держите его в переменной окружения, а не в коде:

```bash
export PDFAPI_KEY=pdf_live_...
```

## Методы

| Метод | Что делает |
|---|---|
| `client.html(html, **параметры)` | HTML → PDF |
| `client.url(url, **параметры)` | публичная страница по адресу → PDF (тариф premium и выше). Адрес — полный, с `http://` или `https://` |
| `client.markdown(text, **параметры)` | Markdown → PDF (тариф premium и выше) |
| `client.office(file, filename=None, landscape=None)` | docx, xlsx, pptx → PDF (тариф premium и выше). `file` — путь, `bytes` или файл, открытый как `'rb'` |
| `client.convert(body)` | запрос `POST /v1/convert` с телом как есть — для всего остального |
| `client.me()` | тариф, расход, остаток страниц и границы периода |

У каждого метода есть и `timeout=` — секунд на этот вызов.

### Параметры страницы

Все необязательные:

| Параметр | Пример | По умолчанию |
|---|---|---|
| `landscape` | `True` | `False` |
| `paper_width`, `paper_height` | `"8.27in"`, `"297mm"` | A4 |
| `margin_top`, `margin_bottom`, `margin_left`, `margin_right` | `"20mm"` | `"0.39in"` |
| `wait_delay` | `"2s"`, `"500ms"` — подождать, пока скрипт на странице дорисует график; до 10 секунд | `"0s"` |

Размер — число и единица `pt`, `px`, `in`, `mm`, `cm` или `pc` без пробела: `"20mm"`, `"1.5cm"`, `".5in"`. Остальное — ошибка сразу, без запроса: `20` и `"20"` — это миллиметры или дюймы? А `"20 mm"` и `"20MM"` рендер не понимает.

### Office-документы

```python
pdf = client.office("report.docx")                         # путь
pdf = client.office(data, filename="report.docx")          # bytes — нужно имя с расширением
with open("table.xlsx", "rb") as f:
    pdf = client.office(f, landscape=True)                  # открытый файл
```

Файл — не больше 3,7 МБ: после кодирования в base64 тело запроса не должно превысить 5 МБ. docx, xlsx и pptx — ZIP-архивы, поэтому старый `.doc` или PDF, переименованный в `.docx`, отклоняется сразу, не отправляя мегабайты на сервер.

## Результат

`PdfResult`:
- `content` — байты PDF (то же — `bytes(pdf)`);
- `pages` — сколько страниц списано;
- `quota` — `Quota(limit, used, remaining)` после этой конвертации;
- `save(path)` — записать в файл и вернуть путь.

`save` пишет атомарно: сначала во временный файл рядом, потом переименовывает поверх. Оборвётся запись или кончится место — на месте останется прежний файл, а не обрезанный PDF. Каталог не создаётся: опечатка в пути — ошибка.

## Отдать PDF из веб-приложения

PDF уже в памяти — отдавайте байты, на диск сохранять незачем:

```python
# FastAPI — асинхронный клиент, один на приложение; целиком — examples/web_fastapi.py
return Response(pdf.content, media_type="application/pdf",
                headers={"Content-Disposition": 'inline; filename="invoice.pdf"'})

# Django
return HttpResponse(pdf.content, content_type="application/pdf")

# Flask
return Response(pdf.content, mimetype="application/pdf")
```

Данные пользователя в HTML — только через `html.escape` (в Django и Jinja — шаблоны с автоэкранированием), иначе это HTML-инъекция в документ.

## Аккаунт и квота

```python
me = client.me()
print(me.plan, me.pages_remaining, "из", me.pages_limit)
print("обнулится", me.period_end)    # datetime в UTC
```

`Account`: `user_id`, `plan` (`free`, `premium`, `business`), `period_start` и `period_end` (когда счётчик начнётся с нуля; `datetime` в UTC или `None`, если сервер не сообщил), `pages_used`, `pages_limit`, `pages_remaining`, `requests_per_second`, `burst`. Запрос страниц не тратит. Проверка для cron — пример `examples/quota.py` и руководство [Контроль квоты](https://pdfapi.ru/docs/guides/quota).

## Ошибки

Все ошибки API — наследники `PdfApiError`; у каждой есть `code`, `status` и `message` (по-русски).

```python
from pdfapi import PdfApi, QuotaExceededError, RateLimitError, RenderError, PdfApiError

try:
    pdf = client.html(html)
except QuotaExceededError as e:
    print("Страницы кончились:", e.message)
except RateLimitError as e:
    print(f"Слишком часто, повторите через {e.retry_after} с")
except RenderError:
    print("Документ не отрендерился — проверьте разметку")
except PdfApiError as e:
    print(e.code, e.status, e.message)
```

| Исключение | Когда |
|---|---|
| `AuthenticationError` | 401: ключа нет, он неверный или отозван |
| `PermissionDeniedError` | 403: почта не подтверждена или формат недоступен на тарифе |
| `QuotaExceededError` | 402: страницы периода кончились или документ больше остатка |
| `InvalidRequestError` | 400: неверный параметр или адрес во внутреннюю сеть (`code == "url_not_allowed"`) |
| `PayloadTooLargeError` | 413: тело больше 5 МБ (наследник `InvalidRequestError`) |
| `RateLimitError` | 429: слишком часто; `retry_after` — через сколько секунд можно снова |
| `RenderError` | 502: документ не отрендерился |
| `RenderTimeoutError` | 504: рендер дольше 30 секунд (наследник `RenderError`) |
| `UnavailableError` | 503: рендер временно недоступен |
| `APIConnectionError` | нет связи с API |
| `APITimeoutError` | API не ответил за `timeout` (наследник `APIConnectionError`) |
| `PdfApiError` с `code == "not_found"` | 404: неверный базовый адрес — обычно в нём забыли `/api` |

Ошибки в аргументах (пустой HTML, `"20 mm"` вместо `"20mm"`, адрес без `https://`, файл `.pdf` вместо `.docx`) — обычные `ValueError` и `TypeError`, ещё до запроса. Лимит частоты на них не тратится.

## Повторы

SDK сам повторяет запрос, когда это безопасно — по умолчанию до 2 раз (`max_retries`):
- **429** — через `Retry-After` секунд (или `retry_after_sec` из ответа), но не дольше минуты;
- **503** и **нет соединения** — через 0,5 и 1 с (с небольшим разбросом).

**Таймаут и обрыв посреди ответа не повторяются.** Сервер мог успеть сделать PDF и списать страницы, и повтор списал бы их второй раз. Такие ошибки приходят как `APITimeoutError` / `APIConnectionError` — решайте сами, повторять ли.

## Асинхронный клиент

Те же методы, только с `await`:

```python
import asyncio
from pdfapi import AsyncPdfApi

async def main():
    async with AsyncPdfApi() as client:
        invoices = ["<h1>Счёт 1</h1>", "<h1>Счёт 2</h1>", "<h1>Счёт 3</h1>"]
        pdfs = await asyncio.gather(*(client.html(h) for h in invoices))
        for i, pdf in enumerate(pdfs, 1):
            pdf.save(f"invoice-{i}.pdf")

asyncio.run(main())
```

Помните про лимит частоты тарифа: на Free — 1 запрос в секунду и до 3 подряд. Большую пачку лучше ограничить `asyncio.Semaphore`, см. пример `examples/async_batch.py`.

## Настройки клиента

```python
client = PdfApi(
    api_key="pdf_live_...",              # иначе PDFAPI_KEY
    base_url="https://pdfapi.ru/api",     # иначе PDFAPI_BASE_URL
    timeout=40,                          # секунд на один запрос; для одного вызова — html(..., timeout=10)
    max_retries=2,
)
```

- **Один клиент на приложение.** Клиент держит пул соединений: создайте его один раз и переиспользуйте, а в конце закройте — `client.close()` или `with PdfApi() as client:`.
- **Неверные настройки** — таймаут не больше нуля или отрицательное число повторов — `ValueError` сразу.
- **Прокси и свои сертификаты:** передайте свой `httpx.Client(proxy=..., verify=...)` в `http_client=`. Закрывать его — ваша забота.
- **Ключ не утекает:** его нет ни в `repr(client)`, ни в текстах ошибок.

## Примеры

В папке `examples/` архива с исходниками пакета; запуск — `PDFAPI_KEY=pdf_live_... python examples/<файл>`:

| Файл | Что показывает |
|---|---|
| `invoice.py` | счёт из HTML-шаблона с экранированием данных |
| `from_url.py` | страница по адресу, альбомная, с ожиданием скриптов |
| `office.py` | docx, xlsx или pptx в PDF рядом с исходным файлом |
| `async_batch.py` | пачка документов параллельно, в пределах лимита частоты |
| `quota.py` | остаток страниц и дата обнуления — для cron, код выхода 2 при нехватке |
| `web_fastapi.py` | отдача PDF из FastAPI, клиент на всё приложение |

## Разработка

```bash
pip install -e ".[dev]"
pytest              # юнит-тесты и общие тест-кейсы SDK (../tests/cases.json)
mypy                # строгая проверка типов
```

Интеграционные тесты против настоящего API запускаются, только если заданы `PDFAPI_IT_KEY` и `PDFAPI_IT_BASE_URL`:

```bash
PDFAPI_IT_KEY=pdf_live_... PDFAPI_IT_BASE_URL=http://localhost:18080/api pytest -m integration
```

## Лицензия

MIT — см. файл `LICENSE`.
