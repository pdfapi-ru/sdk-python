"""docx, xlsx или pptx в PDF (тариф premium и выше).

    PDFAPI_KEY=pdf_live_... python examples/office.py report.docx
"""

import sys
from pathlib import Path

from pdfapi import PdfApi

source = Path(sys.argv[1] if len(sys.argv) > 1 else "report.docx")

with PdfApi() as client:
    pdf = client.office(source)  # путь, bytes (с filename=) или открытый файл
    target = pdf.save(source.with_suffix(".pdf"))
    print(f"{target}: {pdf.pages} стр.")
