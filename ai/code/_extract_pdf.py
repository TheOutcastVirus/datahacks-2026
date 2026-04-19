"""One-off helper: dump text from the DataHacks dataset bank PDF."""
from pathlib import Path

import sys

from project_paths import RAW_DATASET_BANK_PDF

_DEFAULT = RAW_DATASET_BANK_PDF
PDF = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT

try:
    import pypdf  # type: ignore
except ImportError:
    try:
        import PyPDF2 as pypdf  # type: ignore
    except ImportError:
        raise SystemExit("pip install pypdf  (or PyPDF2)")

reader = pypdf.PdfReader(str(PDF))
for i, page in enumerate(reader.pages):
    print(f"\n===== PAGE {i + 1} =====")
    print(page.extract_text() or "(no text extracted)")
