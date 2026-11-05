"""Счёт из HTML-шаблона.

    PDFAPI_KEY=pdf_live_... python examples/invoice.py
"""

from html import escape

from pdfapi import PdfApi, PdfApiError


def rub(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " ₽"  # 12 000 ₽


items = [("Подписка Premium, октябрь", 1, 1990), ("Дополнительные страницы", 2, 500)]
rows = "".join(
    f"<tr><td>{escape(name)}</td><td>{qty}</td><td>{rub(price * qty)}</td></tr>"
    for name, qty, price in items
)
total = sum(qty * price for _, qty, price in items)

html = f"""
<style>
  body {{ font-family: sans-serif; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td, th {{ border-bottom: 1px solid #ddd; padding: 8px; text-align: left; }}
</style>
<h1>Счёт №42</h1>
<table><tr><th>Услуга</th><th>Кол-во</th><th>Сумма</th></tr>{rows}</table>
<h2>Итого: {rub(total)}</h2>
"""

with PdfApi() as client:
    try:
        pdf = client.html(html, margin_top="20mm", margin_bottom="20mm")
    except PdfApiError as e:
        raise SystemExit(f"Не получилось: {e}")
    pdf.save("invoice.pdf")
    print(f"invoice.pdf: {pdf.pages} стр., осталось {pdf.quota.remaining if pdf.quota else '?'}")
