"""Labelled eval set for Kaagaz: the three synthetic demo documents, the fields we expect to be extracted (with
their page), and questions with the page an answer must cite, or that must be refused.

Small on purpose (3 documents, 12 questions): numbers from it are indicative only.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldLabel:
    name: str
    value: str
    page: int


@dataclass(frozen=True)
class Question:
    doc: str
    question: str
    # None = the document does not contain the answer, so Kaagaz must refuse.
    page: int | None
    # Text the answer must contain (case-insensitive); empty for refusals.
    contains: str = ""


DOCS: dict[str, dict] = {
    "rent-agreement-bilingual.pdf": {
        "language": "hi-IN",
        "doc_type": "rent_agreement",
        "fields": [
            FieldLabel("landlord_name", "Sunita Verma", 1),
            FieldLabel("tenant_name", "Arjun Mehta", 1),
            FieldLabel("monthly_rent_inr", "18500", 1),
            FieldLabel("security_deposit_inr", "37000", 1),
            FieldLabel("start_date", "01/04/2026", 1),
            FieldLabel("end_date", "28/02/2027", 1),
            FieldLabel("notice_period", "two months", 2),
            FieldLabel("lock_in_period", "six months", 2),
        ],
    },
    "electricity-bill.pdf": {
        "language": "en-IN",
        "doc_type": "electricity_bill",
        "fields": [
            FieldLabel("consumer_name", "Arjun Mehta", 1),
            FieldLabel("consumer_number", "DEMO-4471-0098", 1),
            FieldLabel("units_consumed_kwh", "312", 1),
            FieldLabel("amount_due_inr", "2846", 1),
            FieldLabel("due_date", "20/10/2026", 1),
        ],
    },
    "khasra-khatauni-hindi.pdf": {
        "language": "hi-IN",
        "doc_type": "property_record",
        "fields": [
            FieldLabel("khasra_number", "512/3", 1),
            FieldLabel("owner_name", "रामप्रसाद", 1),
            FieldLabel("village", "डेमोपुर", 1),
            FieldLabel("tehsil", "सदर", 1),
            FieldLabel("district", "गौतम बुद्ध नगर", 1),
            FieldLabel("area", "0.253", 1),
        ],
    },
}

QUESTIONS: list[Question] = [
    # answerable, English question on a bilingual document
    Question("rent-agreement-bilingual.pdf", "What is the notice period?", 2, "two months"),
    Question("rent-agreement-bilingual.pdf", "How much is the security deposit?", 1, "37,000"),
    Question("rent-agreement-bilingual.pdf", "Are pets allowed?", 2, "consent"),
    # answerable, Hindi question (cross-language retrieval)
    Question("rent-agreement-bilingual.pdf", "लॉक-इन अवधि कितनी है?", 2, "छह"),
    Question("electricity-bill.pdf", "What is the amount due?", 1, "2,846"),
    Question("electricity-bill.pdf", "When is the due date for payment?", 1, "20/10/2026"),
    Question("electricity-bill.pdf", "How many units were consumed?", 1, "312"),
    Question("khasra-khatauni-hindi.pdf", "खसरा संख्या क्या है?", 1, "512/3"),
    Question("khasra-khatauni-hindi.pdf", "What is the area of the land?", 1, "0.253"),
    # must be refused: not in the document
    Question("rent-agreement-bilingual.pdf", "Who won the cricket world cup?", None),
    Question("electricity-bill.pdf", "What is the customer's date of birth?", None),
    Question("khasra-khatauni-hindi.pdf", "What is the market price of this land?", None),
]
