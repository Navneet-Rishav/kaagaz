"""Upload validation and PDF text-layer reading."""

import hashlib
import io
import re
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.errors import ApiError

# Detect the real type from the first bytes; never trust the filename or the browser's Content-Type.
_MAGIC = {b"%PDF-": "application/pdf", b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}


@dataclass
class UploadInfo:
    content_type: str
    sha256: str
    page_count: int


def sniff_type(data: bytes) -> str | None:
    for magic, ctype in _MAGIC.items():
        if data.startswith(magic):
            return ctype
    return None


def validate_upload(data: bytes, max_mb: int, max_pages: int) -> UploadInfo:
    if not data:
        raise ApiError(400, "empty_file", "The file is empty")
    if len(data) > max_mb * 1024 * 1024:
        raise ApiError(413, "file_too_large", f"Files can be at most {max_mb} MB")
    ctype = sniff_type(data)
    if ctype is None:
        raise ApiError(415, "unsupported_type", "Only PDF, PNG and JPG files are supported")
    pages = 1
    if ctype == "application/pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ApiError(400, "encrypted_pdf", "This PDF is password-protected. Please upload an unlocked copy.")
            pages = len(reader.pages)
        except PdfReadError as e:
            raise ApiError(400, "corrupt_pdf", "This PDF could not be read") from e
        if pages == 0:
            raise ApiError(400, "empty_pdf", "This PDF has no pages")
        if pages > max_pages:
            raise ApiError(400, "too_many_pages", f"Documents can have at most {max_pages} pages (this one has {pages})")
    return UploadInfo(content_type=ctype, sha256=hashlib.sha256(data).hexdigest(), page_count=pages)


def pdf_text_pages(data: bytes) -> list[tuple[int, str]]:
    reader = PdfReader(io.BytesIO(data))
    return [(i + 1, (page.extract_text() or "").strip()) for i, page in enumerate(reader.pages)]


# Signs of a broken Devanagari text layer (common in PDFs printed from browsers or Word): a dependent vowel
# sign or virama at the start of a word, or the short-i sign written after another vowel sign. Correct
# Unicode text never has these, because every vowel sign follows a consonant.
_BROKEN_DEVANAGARI = re.compile(r"(?:^|[\s(\"'])[ा-्ंः]|[ा-ौ]ि", re.MULTILINE)
_DEVANAGARI_LETTER = re.compile(r"[ऀ-ॿ]")


def devanagari_garbled(text: str) -> bool:
    letters = len(_DEVANAGARI_LETTER.findall(text))
    if letters < 20:
        return False
    return len(_BROKEN_DEVANAGARI.findall(text)) / letters > 0.01


def has_usable_text_layer(pages: list[tuple[int, str]], min_chars_per_page: int) -> bool:
    """True if every page has enough real, correctly encoded text. One scanned or garbled page sends the whole
    file to OCR, so page numbers stay consistent (OCR returns all pages)."""
    return bool(pages) and all(len("".join(t.split())) >= min_chars_per_page and not devanagari_garbled(t) for _, t in pages)
