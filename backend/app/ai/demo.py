"""Offline, rule-based stand-in for the AI provider. NOT a model.

Used by tests, CI and the public demo so nothing calls a paid API. It classifies by keywords, extracts fields
with regular expressions, and answers by picking the best-matching sentence from the retrieved excerpts.
Everything it produces is labelled "demo mode (rule-based)" in the UI, and no eval numbers are reported from it.
OCR and voice need the real Sarvam APIs, so here they raise AiUnavailable with a clear message.
"""

import json
import re

from app.ai.base import AiUnavailable, ChatResult, PageText, Transcript
from app.domain.extraction import FIELDS
from app.models import DocType

_TYPE_KEYWORDS: dict[DocType, list[str]] = {
    DocType.rent_agreement: [
        "rent agreement",
        "किरायानामा",
        "किराया अनुबंध",
        "tenant",
        "किरायेदार",
        "landlord",
        "मकान मालिक",
        "lessor",
    ],
    DocType.electricity_bill: ["electricity", "बिजली", "kwh", "units consumed", "consumer number", "उपभोक्ता संख्या", "meter"],
    DocType.bank_statement: ["statement of account", "opening balance", "closing balance", "खाता विवरण", "ifsc"],
    DocType.property_record: ["khasra", "खसरा", "खतौनी", "jamabandi", "जमाबंदी", "tehsil", "तहसील", "भू-अभिलेख", "land record"],
}

_AMOUNT = r"₹?\s*(?:rs\.?|inr|रु\.?|रुपये)?\s*([\d,]+(?:\.\d+)?)"
_DATE = r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})"

# field -> label regexes. The value is captured right after the label.
_FIELD_PATTERNS: dict[str, list[str]] = {
    "landlord_name": [r"(?:landlord|lessor|मकान मालिक)\s*[:\-–]\s*([^\n,(]+)"],
    "tenant_name": [r"(?:tenant|lessee|किरायेदार)\s*[:\-–]\s*([^\n,(]+)"],
    "property_address": [r"(?:property address|premises|संपत्ति का पता|पता)\s*[:\-–]\s*([^\n]+)"],
    "monthly_rent_inr": [r"(?:monthly rent|rent per month|मासिक किराया)[^\d₹\n]{0,30}" + _AMOUNT],
    "security_deposit_inr": [r"(?:security deposit|सिक्योरिटी डिपॉज़िट|जमानत राशि)[^\d₹\n]{0,30}" + _AMOUNT],
    # In Hindi the date comes BEFORE the postposition: "01/04/2026 से 28/02/2027 तक".
    "start_date": [
        r"(?:start date|starts on|commencing on|commences on|w\.e\.f\.?|आरंभ तिथि)\s*[:\-–]?\s*" + _DATE,
        _DATE + r"\s*से",
    ],
    "end_date": [
        r"(?:end date|ends on|ending on|expires on|till|until|समाप्ति तिथि)\s*[:\-–]?\s*" + _DATE,
        r"से\s*" + _DATE + r"\s*तक",
    ],
    "notice_period": [r"(?:notice period|नोटिस अवधि)\s*[:\-–]?\s*(?:of\s+)?([^\n.]+)"],
    "lock_in_period": [r"(?:lock-in period|lock in period|लॉक-इन अवधि)\s*[:\-–]?\s*(?:of\s+)?([^\n.]+)"],
    "consumer_name": [r"(?:consumer name|उपभोक्ता का नाम)\s*[:\-–]\s*([^\n]+)"],
    "consumer_number": [r"(?:consumer (?:no\.?|number)|उपभोक्ता संख्या)\s*[:\-–]\s*([A-Z0-9\-]+)"],
    "billing_period": [r"(?:billing period|बिलिंग अवधि)\s*[:\-–]\s*([^\n]+)"],
    "units_consumed_kwh": [r"(?:units consumed|खपत यूनिट|consumption)[^\d\n]{0,20}([\d,]+(?:\.\d+)?)"],
    "amount_due_inr": [r"(?:amount due|amount payable|net payable|देय राशि)[^\d₹\n]{0,30}" + _AMOUNT],
    "due_date": [r"(?:due date|pay by|अंतिम तिथि)\s*[:\-–]?\s*" + _DATE],
    "account_holder": [r"(?:account holder|name|खाताधारक)\s*[:\-–]\s*([^\n]+)"],
    "bank_name": [r"(?:bank)\s*[:\-–]\s*([^\n]+)"],
    "statement_period": [r"(?:statement period|period|अवधि)\s*[:\-–]\s*([^\n]+)"],
    "opening_balance_inr": [r"(?:opening balance|प्रारंभिक शेष)[^\d₹\n]{0,20}" + _AMOUNT],
    "closing_balance_inr": [r"(?:closing balance|अंतिम शेष)[^\d₹\n]{0,20}" + _AMOUNT],
    "owner_name": [r"(?:owner|खातेदार|भूमिस्वामी|स्वामी)(?:\s*का नाम)?\s*[:\-–]\s*([^\n]+)"],
    "khasra_number": [r"(?:khasra (?:no\.?|number)|खसरा (?:संख्या|नंबर|सं\.))\s*[:\-–]?\s*([\d/]+)"],
    "village": [r"(?:village|ग्राम|गाँव)\s*[:\-–]\s*([^\n,]+)"],
    "tehsil": [r"(?:tehsil|तहसील)\s*[:\-–]\s*([^\n,]+)"],
    "district": [r"(?:district|ज़िला|जिला)\s*[:\-–]\s*([^\n,]+)"],
    "area": [r"(?:area|क्षेत्रफल|रकबा)\s*[:\-–]\s*([^\n]+)"],
    "land_type": [r"(?:land type|भूमि का प्रकार|भूमि की किस्म)\s*[:\-–]\s*([^\n]+)"],
    "title": [r"^\s*([^\n]{5,80})"],
}

# English <-> Hindi glossary for the cross-language keyword rewrite.
_GLOSSARY: dict[str, list[str]] = {
    "rent": ["किराया", "किराए"],
    "deposit": ["सिक्योरिटी", "डिपॉज़िट", "जमानत"],
    "notice": ["नोटिस"],
    "lock-in": ["लॉक-इन"],
    "landlord": ["मकान", "मालिक"],
    "tenant": ["किरायेदार"],
    "date": ["तिथि", "तारीख"],
    "amount": ["राशि"],
    "due": ["देय", "अंतिम"],
    "units": ["यूनिट"],
    "bill": ["बिल"],
    "electricity": ["बिजली"],
    "owner": ["स्वामी", "खातेदार"],
    "khasra": ["खसरा"],
    "area": ["क्षेत्रफल", "रकबा"],
    "village": ["ग्राम"],
    "district": ["ज़िला", "जिला"],
    "maintenance": ["रखरखाव"],
    "pet": ["पालतू"],
    "period": ["अवधि"],
}
_REVERSE = {hi: en for en, his in _GLOSSARY.items() for hi in his}
_STOP = set(
    [
        "what",
        "is",
        "the",
        "of",
        "a",
        "an",
        "and",
        "or",
        "to",
        "in",
        "on",
        "for",
        "my",
        "me",
        "how",
        "much",
        "when",
        "who",
        "which",
        "does",
        "do",
        "please",
        "tell",
        "about",
        "kya",
        "hai",
        "ka",
        "ki",
        "ke",
        "है",
        "क्या",
        "का",
        "की",
        "के",
        "में",
        "से",
        "को",
        "कितना",
        "कितनी",
        "कब",
        "कौन",
        "मेरा",
        "मेरी",
        "बताइए",
        "बताओ",
        "यह",
        "वह",
        "और",
    ]
)
_WORD = re.compile(r"[\wऀ-ॣ०-ॿ\-]+", re.UNICODE)  # excludes the danda
_SENT = re.compile(r"(?<=[.!?।])\s+|\n+")


def _payload(user: str) -> dict:
    try:
        return json.loads(user.split("\n\nYour previous reply was invalid")[0])
    except ValueError:
        return {}


def _keywords(text: str) -> list[str]:
    return [w for w in (m.group(0).lower() for m in _WORD.finditer(text)) if w not in _STOP and len(w) > 1]


class DemoProvider:
    name = "demo"
    model = "rule-based (no AI)"
    is_demo = True

    def chat(self, task: str, system: str, user: str, schema: dict | None = None) -> ChatResult:
        p = _payload(user)
        handler = {"classify": self._classify, "rewrite": self._rewrite, "answer": self._answer}.get(task)
        if task.startswith("extract"):
            handler = self._extract
        if handler is None:
            raise ValueError(f"demo provider has no handler for task {task}")
        return ChatResult(text=json.dumps(handler(p), ensure_ascii=False), latency_ms=1, tokens=0)

    def _classify(self, p: dict) -> dict:
        text = " ".join(pg["text"] for pg in p.get("pages", [])).lower()
        scores = {t: sum(text.count(k) for k in kws) for t, kws in _TYPE_KEYWORDS.items()}
        best = max(scores, key=lambda t: scores[t])
        dev = len(re.findall(r"[ऀ-ॿ]", text))
        lat = len(re.findall(r"[a-z]", text))
        language = "hi" if dev > 3 * max(lat, 1) else "en" if lat > 3 * max(dev, 1) else "mixed"
        if scores[best] == 0:
            return {
                "doc_type": "other",
                "confidence": "low",
                "language": language,
                "summary": "Demo mode: document type not recognised.",
            }
        conf = "high" if scores[best] >= 3 else "medium"
        return {
            "doc_type": best.value,
            "confidence": conf,
            "language": language,
            "summary": f"Demo mode: looks like a {best.value.replace('_', ' ')}.",
        }

    def _extract(self, p: dict) -> dict:
        doc_type = DocType(p.get("doc_type", "other"))
        out: dict[str, dict] = {}
        for name in FIELDS[doc_type]:
            out[name] = {"value": None, "page": None, "confidence": "missing"}
            for pattern in _FIELD_PATTERNS.get(name, []):
                for pg in p.get("pages", []):
                    m = re.search(pattern, pg["text"], re.IGNORECASE | re.MULTILINE)
                    if m:
                        value = m.group(1).strip().rstrip(".,;")
                        if name.endswith("_inr") or name.endswith("_kwh"):
                            value = value.replace(",", "")
                        out[name] = {"value": value, "page": pg["page"], "confidence": "medium"}
                        break
                if out[name]["value"] is not None:
                    break
        return out

    def _rewrite(self, p: dict) -> dict:
        words = _keywords(p.get("question", ""))
        en = [w for w in words if not re.search(r"[ऀ-ॿ]", w)]
        hi = [w for w in words if re.search(r"[ऀ-ॿ]", w)]
        en_out = list(dict.fromkeys(en + [_REVERSE[w] for w in hi if w in _REVERSE]))
        hi_out = list(dict.fromkeys(hi + [h for w in en for h in _GLOSSARY.get(w, [])]))
        return {"keywords_en": en_out[:6], "keywords_hi": hi_out[:6]}

    def _answer(self, p: dict) -> dict:
        q = set(_keywords(p.get("question", "")))
        q |= {_REVERSE[w] for w in q if w in _REVERSE} | {h for w in list(q) for h in _GLOSSARY.get(w, [])}
        best: tuple[int, int, str] | None = None
        for ex in p.get("excerpts", []):
            for sentence in _SENT.split(ex["text"]):
                score = len(q & set(_keywords(sentence)))
                if score and (best is None or score > best[0]):
                    best = (score, ex["page"], sentence.strip())
        if best is None or best[0] < 1:
            return {"found": False, "answer": "", "citations": []}
        prefix = "दस्तावेज़ के अनुसार: " if p.get("language") == "hi" else "According to the document: "
        return {"found": True, "answer": f"{prefix}{best[2]} [p.{best[1]}]", "citations": [best[1]]}

    def parse_document(self, data: bytes, filename: str, language: str) -> list[PageText]:
        raise AiUnavailable("This file has no text layer and needs OCR, which uses the Sarvam API and is turned off in the demo.")

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> Transcript:
        raise AiUnavailable("Voice input uses the Sarvam speech API and is turned off in the demo.")

    def speak(self, text: str, language: str) -> bytes:
        raise AiUnavailable("Read-aloud uses the Sarvam speech API and is turned off in the demo.")
