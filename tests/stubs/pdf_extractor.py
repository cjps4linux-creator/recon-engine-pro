"""
Minimal stand-in for ``corp-recon-engine/pdf_extractor.py``.

Only used when the sibling ``corp-recon-engine`` checkout is unavailable
(the CI case). It provides the one symbol ``backend/main.py`` imports from
that module - ``PDFExtractionError`` - plus a tiny ``process_pdf`` helper so
the import contract is preserved.

The real sibling module wins whenever it is present, because
``backend/main.py`` puts the sibling checkout at the front of ``sys.path``.
"""

from __future__ import annotations

from typing import Any, Dict


class PDFExtractionError(Exception):
    """Raised when PDF extraction fails (mirrors the real engine)."""


def process_pdf(file_path: str) -> Dict[str, Any]:
    """Not implemented in the stub - PDFs are not exercised by the tests."""
    return {
        "success": False,
        "doc_type": "unknown",
        "data": None,
        "message": "PDF extraction is not available in the stub engine.",
    }


def detect_document_type(text_sample: str, df_sample) -> str:
    """Not implemented in the stub."""
    return "unknown"
