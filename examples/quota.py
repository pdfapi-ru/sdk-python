"""Сколько страниц осталось и когда квота обнулится — для cron и мониторинга.

    PDFAPI_KEY=pdf_live_... python examples/quota.py        # предупредить, если осталось меньше 10%
    PDFAPI_KEY=pdf_live_... python examples/quota.py 25     # …меньше 25%

Код выхода 2 — страниц меньше порога: cron пришлёт письмо, мониторинг поднимет тревогу.
Запрос страниц не тратит.
"""

import sys

from pdfapi import PdfApi

threshold = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0

with PdfApi() as client:
    me = client.me()

left = 100 * me.pages_remaining / me.pages_limit if me.pages_limit else 0.0
reset = me.period_end.strftime("%d.%m.%Y %H:%M UTC") if me.period_end else "неизвестно когда"
print(f"Тариф {me.plan}: использовано {me.pages_used} из {me.pages_limit}, осталось {me.pages_remaining} ({int(left)}%).")
print(f"Счётчик обнулится {reset}.")
if left < threshold:
    print(f"Осталось меньше {threshold:g}% — пора докупить страницы или сменить тариф.", file=sys.stderr)
    sys.exit(2)
