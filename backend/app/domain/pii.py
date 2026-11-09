"""PII masking for Indian documents with Microsoft Presidio pattern recognizers.

Pattern recognizers only: no spaCy/NER model is loaded, which keeps the API inside Render's free-tier
RAM. The trade-off is that names and addresses are not masked; see docs/DECISIONS.md.

Masked: Aadhaar (Verhoeff-validated), PAN, Indian mobile numbers, IFSC codes, email addresses, and bank
account numbers (only when a context word like "A/c" or "खाता" comes just before them).
Devanagari digits (०-९) are converted to ASCII first so the same patterns work on Hindi text.
Only the masked text and per-type counts leave this module, never the values.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from presidio_analyzer import Pattern, PatternRecognizer, RecognizerResult
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from app.domain.verhoeff import verhoeff_valid

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def normalize_digits(text: str) -> str:
    return text.translate(_DEVANAGARI_DIGITS)


class AadhaarRecognizer(PatternRecognizer):
    """12 digits, optionally grouped 4-4-4, never starting with 0 or 1, with a valid Verhoeff check digit."""

    def __init__(self) -> None:
        super().__init__(
            supported_entity="AADHAAR",
            patterns=[Pattern("aadhaar", r"(?<![\d-])[2-9]\d{3}([ -]?)\d{4}\1\d{4}(?![\d-])", 0.9)],
        )

    def validate_result(self, pattern_text: str) -> bool:
        return verhoeff_valid(pattern_text)


class _ContextRecognizer(PatternRecognizer):
    """A pattern that only counts when one of `context_words` appears just before the match.

    Presidio's built-in context enhancement needs NLP artifacts (lemmas) from a spaCy model, which we do
    not load, so the check is done here on the raw text instead.
    """

    def __init__(self, entity: str, pattern: str, context: str, window: int = 30) -> None:
        super().__init__(supported_entity=entity, patterns=[Pattern(entity.lower(), pattern, 0.6)])
        self._context = re.compile(context, re.IGNORECASE)
        self._window = window

    def analyze(self, text, entities, nlp_artifacts=None, regex_flags=None):  # type: ignore[override]
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        return [r for r in results if self._context.search(text[max(0, r.start - self._window) : r.start])]


def _recognizers() -> list[PatternRecognizer]:
    return [
        AadhaarRecognizer(),
        PatternRecognizer(supported_entity="PAN", patterns=[Pattern("pan", r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", 0.85)]),
        PatternRecognizer(
            supported_entity="PHONE",
            # Optional +91 / 91 / 0 prefix, then a 10-digit mobile starting 6-9, optionally split 5+5.
            patterns=[Pattern("in_mobile", r"(?<![\d+])(?:\+?91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)", 0.7)],
        ),
        PatternRecognizer(supported_entity="IFSC", patterns=[Pattern("ifsc", r"\b[A-Z]{4}0[A-Z0-9]{6}\b", 0.85)]),
        PatternRecognizer(
            supported_entity="EMAIL",
            patterns=[Pattern("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", 0.9)],
        ),
        _ContextRecognizer(
            "BANK_ACCOUNT",
            r"(?<!\d)\d{9,18}(?!\d)",
            # A context word, then at most ~20 characters ("No.:", "number", "संख्या") up to the digits.
            r"(a/c|acct|account|खाता)[^\n]{0,20}$",
        ),
    ]


_RECOGNIZERS = _recognizers()
_ENTITIES = [r.supported_entities[0] for r in _RECOGNIZERS]
_ANONYMIZER = AnonymizerEngine()
_OPERATORS = {e: OperatorConfig("replace", {"new_value": f"<{e}>"}) for e in _ENTITIES}


@dataclass
class MaskResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)


def _drop_overlaps(results: list[RecognizerResult]) -> list[RecognizerResult]:
    """Keep the higher-scoring (then longer) match when two overlap, e.g. a valid Aadhaar near "A/c"."""
    kept: list[RecognizerResult] = []
    for r in sorted(results, key=lambda r: (-r.score, -(r.end - r.start), r.start)):
        if all(r.end <= k.start or r.start >= k.end for k in kept):
            kept.append(r)
    return sorted(kept, key=lambda r: r.start)


def mask_pii(text: str) -> MaskResult:
    if not text:
        return MaskResult(text="")
    norm = normalize_digits(text)
    results: list[RecognizerResult] = []
    for rec in _RECOGNIZERS:
        results.extend(rec.analyze(norm, rec.supported_entities, None))
    results = _drop_overlaps(results)
    if not results:
        return MaskResult(text=norm)
    masked = _ANONYMIZER.anonymize(text=norm, analyzer_results=results, operators=_OPERATORS).text
    return MaskResult(text=masked, counts=dict(Counter(r.entity_type for r in results)))
