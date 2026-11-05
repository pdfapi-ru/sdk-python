# Изменения

## 0.1.0

Первая версия.

- `PdfApi` и `AsyncPdfApi`: `html`, `url`, `markdown`, `office`, `convert`, `me`.
- Параметры страницы — `landscape`, `paper_width`, `paper_height`, `margin_*`, `wait_delay`; проверяются до запроса.
- Результат `PdfResult`: байты PDF, число страниц, квота, `save()`.
- Исключения по кодам API — наследники `PdfApiError`.
- Проверки до запроса: размеры — число с единицей `pt`, `px`, `in`, `mm`, `cm` или `pc`; `wait_delay` — до 10 секунд; адрес — с `http(s)://`; Office-файл — ZIP-архив не больше 3,7 МБ.
- Повторы при 429 (по `Retry-After` или `retry_after_sec`), 503 и ошибках соединения; таймауты не повторяются, чтобы не списать страницы дважды.
- Ответы не от API (страница 404, формат Fastify, текст от прокси) разбираются по статусу; 404 — `not_found` с подсказкой про базовый адрес.
- `save()` пишет атомарно: прерванная запись не портит прежний файл.
- `me()`: `user_id`, `period_start`, `period_end` — когда обнулится квота.
- `timeout=` у каждого метода; неверные `timeout` и `max_retries` — ошибка при создании клиента.
- Примеры: `invoice`, `from_url`, `office`, `async_batch`, `quota` (для cron), `web_fastapi`.
