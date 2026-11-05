"""Отдавать PDF из веб-приложения: FastAPI и асинхронный клиент.

    pip install pdfapi fastapi uvicorn
    cd examples && PDFAPI_KEY=pdf_live_... uvicorn web_fastapi:app
    curl -o invoice.pdf 'http://127.0.0.1:8000/invoice/42?customer=ООО%20Ромашка'

Клиент один на приложение: он держит пул соединений, а закрывается вместе с ним.
"""

from contextlib import asynccontextmanager
from html import escape
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, Response

from pdfapi import AsyncPdfApi, PdfApiError, RateLimitError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncPdfApi() as client:
        app.state.pdfapi = client
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/invoice/{number}")
async def invoice(number: int, request: Request, customer: str = "Покупатель") -> Response:
    client: AsyncPdfApi = request.app.state.pdfapi
    # Всё, что пришло от пользователя, — только через escape: иначе это HTML-инъекция в документ.
    html = f"<h1>Счёт №{number}</h1><p>Покупатель: {escape(customer)}</p><p>К оплате: 12 000 ₽</p>"
    try:
        pdf = await client.html(html, margin_top="20mm")
    except RateLimitError as e:
        raise HTTPException(429, "Слишком часто, повторите позже", headers={"Retry-After": str(int(e.retry_after or 1))})
    except PdfApiError as e:
        raise HTTPException(502, f"PDF не получился: {e.message}")
    return Response(
        pdf.content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="invoice-{number}.pdf"'},
    )
