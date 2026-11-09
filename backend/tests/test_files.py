import pytest

from app.errors import ApiError
from app.services.files import devanagari_garbled, has_usable_text_layer, sniff_type, validate_upload

# Real output of pypdf on a Chrome/Edge-printed Hindi PDF: vowel signs reordered, conjuncts dropped.
GARBLED = "मािसक िकराया ₹18,500 होगा। िस ो रटी िडपॉिज़ट: ₹37,000। खसरा सं ा: 512/3,  ाम: डेमोपुर"
CLEAN = "मासिक किराया ₹18,500 होगा। सिक्योरिटी डिपॉज़िट: ₹37,000। खसरा संख्या: 512/3, ग्राम: डेमोपुर"


def test_garbled_devanagari_is_detected() -> None:
    assert devanagari_garbled(GARBLED)
    assert not devanagari_garbled(CLEAN)
    assert not devanagari_garbled("Monthly rent is ₹18,500 and the deposit is ₹37,000.")


def test_garbled_text_layer_is_not_usable() -> None:
    long_clean = CLEAN * 3
    assert has_usable_text_layer([(1, long_clean)], min_chars_per_page=80)
    assert not has_usable_text_layer([(1, GARBLED * 3)], min_chars_per_page=80)


def test_text_layer_needs_enough_text_on_every_page() -> None:
    good = "x" * 100
    assert has_usable_text_layer([(1, good), (2, good)], 80)
    assert not has_usable_text_layer([(1, good), (2, "  short ")], 80)
    assert not has_usable_text_layer([], 80)


def test_sniff_type_uses_magic_bytes_not_names() -> None:
    assert sniff_type(b"%PDF-1.7 ...") == "application/pdf"
    assert sniff_type(b"\x89PNG\r\n\x1a\n....") == "image/png"
    assert sniff_type(b"\xff\xd8\xff\xe0....") == "image/jpeg"
    assert sniff_type(b"MZ\x90\x00 an exe") is None


@pytest.mark.parametrize(
    ("data", "code"),
    [(b"", "empty_file"), (b"GIF89a....", "unsupported_type"), (b"%PDF-1.4 not really a pdf", "corrupt_pdf")],
)
def test_validate_upload_rejects_bad_files(data: bytes, code: str) -> None:
    with pytest.raises(ApiError) as e:
        validate_upload(data, max_mb=10, max_pages=30)
    assert e.value.code == code


def test_validate_upload_size_limit() -> None:
    with pytest.raises(ApiError) as e:
        validate_upload(b"%PDF-" + b"0" * (1024 * 1024 + 10), max_mb=1, max_pages=30)
    assert e.value.status == 413
