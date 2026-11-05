"""Пачка документов параллельно, с ограничением одновременных запросов.

Тариф ограничивает частоту (Free — 1 запрос в секунду и до 3 подряд,
Premium — 10 и 30). SDK сам подождёт и повторит при 429, но ровнее —
не отправлять больше, чем позволяет тариф.

    PDFAPI_KEY=pdf_live_... python examples/async_batch.py
"""

import asyncio

from pdfapi import AsyncPdfApi, PdfApiError

PARALLEL = 3


async def main() -> None:
    documents = {f"invoice-{n}.pdf": f"<h1>Счёт №{n}</h1>" for n in range(1, 11)}
    limit = asyncio.Semaphore(PARALLEL)

    async with AsyncPdfApi() as client:

        async def render(name: str, html: str) -> None:
            async with limit:
                try:
                    pdf = await client.html(html)
                except PdfApiError as e:
                    print(f"{name}: ошибка {e.code} — {e.message}")
                    return
            pdf.save(name)
            print(f"{name}: {pdf.pages} стр.")

        await asyncio.gather(*(render(name, html) for name, html in documents.items()))


asyncio.run(main())
