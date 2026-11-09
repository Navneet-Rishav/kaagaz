import pytest

from app.domain.pii import mask_pii, normalize_digits

# Synthetic test numbers only. 2345 6789 0126 passes Verhoeff; 2345 6789 0124 does not.
VALID_AADHAAR = "2345 6789 0126"
INVALID_AADHAAR = "2345 6789 0124"


def test_normalize_devanagari_digits() -> None:
    assert normalize_digits("किराया ₹१२,५०० प्रति माह") == "किराया ₹12,500 प्रति माह"


@pytest.mark.parametrize("aadhaar", [VALID_AADHAAR, "234567890126", "2345-6789-0126"])
def test_aadhaar_masked_in_common_formats(aadhaar: str) -> None:
    r = mask_pii(f"Aadhaar No. {aadhaar} of the tenant")
    assert r.text == "Aadhaar No. <AADHAAR> of the tenant"
    assert r.counts == {"AADHAAR": 1}


def test_aadhaar_in_devanagari_digits_is_masked() -> None:
    r = mask_pii("आधार संख्या २३४५ ६७८९ ०१२६")
    assert r.text == "आधार संख्या <AADHAAR>"


def test_twelve_digits_failing_verhoeff_are_not_aadhaar() -> None:
    r = mask_pii(f"Invoice {INVALID_AADHAAR}")
    assert "<AADHAAR>" not in r.text
    assert INVALID_AADHAAR in r.text


def test_aadhaar_never_starts_with_0_or_1() -> None:
    assert "<AADHAAR>" not in mask_pii("Ref 1234 5678 9012").text


def test_pan_masked_but_not_inside_longer_tokens() -> None:
    assert mask_pii("PAN: ABCDE1234F.").text == "PAN: <PAN>."
    assert mask_pii("code XABCDE1234FX").counts == {}


@pytest.mark.parametrize("phone", ["9876543210", "+91 9876543210", "+91-98765-43210", "98765 43210", "+919876543210"])
def test_indian_mobile_numbers_masked(phone: str) -> None:
    r = mask_pii(f"Call {phone} today")
    assert r.text == "Call <PHONE> today"


def test_mobile_in_devanagari_digits() -> None:
    assert mask_pii("मोबाइल: ९८७६५४३२१०").text == "मोबाइल: <PHONE>"


@pytest.mark.parametrize("not_phone", ["1234567890", "5876543210", "198765432101"])
def test_non_mobile_numbers_not_masked_as_phone(not_phone: str) -> None:
    assert "<PHONE>" not in mask_pii(f"No. {not_phone}").text


def test_ifsc_masked_only_with_zero_in_fifth_place() -> None:
    assert mask_pii("IFSC SBIN0001234").text == "IFSC <IFSC>"
    assert mask_pii("IFSC SBIN1001234").counts == {}


def test_email_masked() -> None:
    assert mask_pii("Write to ravi.kumar+rent@example.co.in please").text == "Write to <EMAIL> please"


@pytest.mark.parametrize(
    "text",
    ["A/c No: 123456789012", "a/c 00112233445566", "Account number 501004567890", "खाता संख्या 00112233445566"],
)
def test_bank_account_masked_only_near_context_words(text: str) -> None:
    r = mask_pii(text)
    assert "<BANK_ACCOUNT>" in r.text
    assert r.counts == {"BANK_ACCOUNT": 1}


def test_long_number_without_context_is_left_alone() -> None:
    assert mask_pii("Consumer number 123456789012 for meter").counts == {}


@pytest.mark.parametrize(
    "text",
    ["Dated 12/05/2024", "Rent ₹12,000 per month", "PIN 110001", "Year 2025", "Meter reading 004512 kWh", "Bill no. 8800123"],
)
def test_common_false_positives_are_not_masked(text: str) -> None:
    r = mask_pii(text)
    assert r.counts == {}
    assert r.text == text


def test_mixed_document_counts_and_no_values_leak() -> None:
    text = (
        f"Landlord: Ravi Kumar, Aadhaar {VALID_AADHAAR}, PAN ABCDE1234F, mobile +91 98765 43210, "
        "email ravi@example.com. Pay to A/c No. 501004567890, IFSC HDFC0001234. "
        "किरायेदार का मोबाइल ९१२३४५६७८९"
    )
    r = mask_pii(text)
    assert r.counts == {"AADHAAR": 1, "PAN": 1, "PHONE": 2, "EMAIL": 1, "BANK_ACCOUNT": 1, "IFSC": 1}
    for value in ["2345", "ABCDE1234F", "98765", "ravi@example.com", "501004567890", "HDFC0001234", "9123456789"]:
        assert value not in r.text
    assert "Ravi Kumar" in r.text  # names are not masked (no NER model; see DECISIONS.md)


def test_empty_text() -> None:
    r = mask_pii("")
    assert r.text == "" and r.counts == {}
