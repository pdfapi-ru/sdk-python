"""Страница по адресу в PDF (тариф premium и выше).

    PDFAPI_KEY=pdf_live_... python examples/from_url.py https://example.com
"""

import sys

from pdfapi import InvalidRequestError, PdfApi, PermissionDeniedError

url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"

with PdfApi() as client:
    try:
        # wait_delay — подождать, пока скрипты на странице дорисуют содержимое.
        pdf = client.url(url, landscape=True, wait_delay="1s")
    except PermissionDeniedError as e:
        raise SystemExit(f"{e.message} — нужен тариф premium")
    except InvalidRequestError as e:
        raise SystemExit(e.message)  # например, url_not_allowed: адрес во внутреннюю сеть
    print(f"{pdf.save('page.pdf')}: {pdf.pages} стр.")
