"""Text from one arXiv PDF, including the bibliography.

arXiv's HTML conversion drops papers that have no rendered HTML, and an
abstract is not the paper. The bulk PDF is the text Lambert scans. This
module turns one of those PDFs into the string the matcher sees.

pdftotext preserves the reading order of a two-column paper better than a
naive page dump. A missing binary is a setup error, not a reason to scan
the abstract instead.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# A real paper body is longer than a title page. Shorter extracts are
# recorded as failed so they stay out of the scanned denominator.
MIN_CHARS = 2500


class PdfTextError(RuntimeError):
    """The PDF was present and the extractor could not read it."""


def pdftotext_bin() -> str:
    found = shutil.which("pdftotext")
    if not found:
        raise PdfTextError(
            "pdftotext is not on PATH. Install poppler-utils before a full-text scan."
        )
    return found


def pdf_to_text(pdf_path: Path) -> str:
    """Extract the whole PDF, references included. Empty text is a failure."""
    binary = pdftotext_bin()
    try:
        completed = subprocess.run(
            [binary, "-q", "-enc", "UTF-8", "-layout", str(pdf_path), "-"],
            check=False,
            capture_output=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise PdfTextError(f"pdftotext timed out on {pdf_path.name}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise PdfTextError(f"pdftotext failed on {pdf_path.name}: {detail}")
    text = completed.stdout.decode("utf-8", "replace")
    if len(text.strip()) < MIN_CHARS:
        raise PdfTextError(
            f"{pdf_path.name} extracted {len(text.strip())} characters, below {MIN_CHARS}"
        )
    return text
