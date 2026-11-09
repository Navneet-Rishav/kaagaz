"""Document types, the typed fields extracted for each, and validation of what the model returns.

Every field carries the page it came from and a confidence. A value the model could not find is stored as
"missing" rather than guessed, and a page number outside the document is dropped (confidence lowered).
"""

from typing import Literal

from pydantic import BaseModel, Field, create_model

from app.models import DocType

Confidence = Literal["high", "medium", "low", "missing"]


class ExtractedField(BaseModel):
    value: str | float | int | None = None
    page: int | None = None
    confidence: Confidence = "missing"


class Classification(BaseModel):
    doc_type: DocType
    confidence: Literal["high", "medium", "low"]
    language: Literal["hi", "en", "mixed"]
    summary: str = Field(max_length=400)


# field name -> (English label, Hindi label)
FIELDS: dict[DocType, dict[str, tuple[str, str]]] = {
    DocType.rent_agreement: {
        "landlord_name": ("Landlord", "मकान मालिक"),
        "tenant_name": ("Tenant", "किरायेदार"),
        "property_address": ("Property address", "संपत्ति का पता"),
        "monthly_rent_inr": ("Monthly rent (₹)", "मासिक किराया (₹)"),
        "security_deposit_inr": ("Security deposit (₹)", "सिक्योरिटी डिपॉज़िट (₹)"),
        "start_date": ("Start date", "आरंभ तिथि"),
        "end_date": ("End date", "समाप्ति तिथि"),
        "notice_period": ("Notice period", "नोटिस अवधि"),
        "lock_in_period": ("Lock-in period", "लॉक-इन अवधि"),
    },
    DocType.electricity_bill: {
        "consumer_name": ("Consumer name", "उपभोक्ता का नाम"),
        "consumer_number": ("Consumer number", "उपभोक्ता संख्या"),
        "billing_period": ("Billing period", "बिलिंग अवधि"),
        "units_consumed_kwh": ("Units consumed (kWh)", "खपत यूनिट (kWh)"),
        "amount_due_inr": ("Amount due (₹)", "देय राशि (₹)"),
        "due_date": ("Due date", "अंतिम तिथि"),
    },
    DocType.bank_statement: {
        "account_holder": ("Account holder", "खाताधारक"),
        "bank_name": ("Bank", "बैंक"),
        "statement_period": ("Statement period", "विवरण अवधि"),
        "opening_balance_inr": ("Opening balance (₹)", "प्रारंभिक शेष (₹)"),
        "closing_balance_inr": ("Closing balance (₹)", "अंतिम शेष (₹)"),
    },
    DocType.property_record: {
        "owner_name": ("Owner", "स्वामी"),
        "khasra_number": ("Khasra number", "खसरा संख्या"),
        "village": ("Village", "ग्राम"),
        "tehsil": ("Tehsil", "तहसील"),
        "district": ("District", "ज़िला"),
        "area": ("Area", "क्षेत्रफल"),
        "land_type": ("Land type", "भूमि का प्रकार"),
    },
    DocType.other: {
        "title": ("Title", "शीर्षक"),
        "parties": ("Parties", "पक्षकार"),
        "key_date": ("Key date", "मुख्य तिथि"),
        "key_amount_inr": ("Key amount (₹)", "मुख्य राशि (₹)"),
    },
}

_models: dict[DocType, type[BaseModel]] = {}


def extraction_model(doc_type: DocType) -> type[BaseModel]:
    """A Pydantic model with one ExtractedField per field of this document type (used as the JSON schema)."""
    if doc_type not in _models:
        fields = {name: (ExtractedField, ExtractedField()) for name in FIELDS[doc_type]}
        _models[doc_type] = create_model(f"Extract_{doc_type.value}", **fields)  # type: ignore[call-overload]
    return _models[doc_type]


def clean_fields(raw: BaseModel, page_count: int) -> dict[str, dict]:
    """Normalises the model output: unknown pages are dropped, empty values become "missing"."""
    out: dict[str, dict] = {}
    for name, f in raw:
        assert isinstance(f, ExtractedField)
        value = f.value.strip() if isinstance(f.value, str) else f.value
        if value in ("", None):
            out[name] = {"value": None, "page": None, "confidence": "missing"}
            continue
        page, conf = f.page, f.confidence
        if page is None or not (1 <= page <= page_count):
            page = None
            conf = "low"
        if conf == "missing":
            conf = "low"
        out[name] = {"value": value, "page": page, "confidence": conf}
    return out
