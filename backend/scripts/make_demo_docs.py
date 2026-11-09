"""Builds the three synthetic demo documents: a PDF for viewing plus a `.pages.json` with the page text.

All names, numbers and places are fake ("DEMO"/"डेमो"). Identity numbers are well-known dummies; the Aadhaar
one passes the Verhoeff check only so the masking can be shown.

Why a sidecar: browser-printed PDFs store Devanagari with a broken text layer (vowel signs reordered, conjuncts
lost), so their text cannot be read back reliably. The pipeline sends such files to OCR. The demo has no OCR
credits, so the page text is prepared in advance, as a cached OCR result would be, and the UI says so.

Usage (Windows, needs Microsoft Edge):  python scripts/make_demo_docs.py
"""

import html
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "demo_docs"
EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

RENT = [
    """RENT AGREEMENT / किरायानामा (DEMO DOCUMENT - FICTIONAL)

This Rent Agreement is made at Noida on 15/03/2026.

Landlord: Sunita Verma (DEMO), Aadhaar 2345 6789 0126, PAN ABCDE1234F, mobile +91 98765 43210, email sunita.demo@example.com
Tenant: Arjun Mehta (DEMO), mobile 91234 56789

Property address: Flat 204, Demo Residency, Sector 62, Noida, Uttar Pradesh

1. Term. The tenancy starts on 01/04/2026 and ends on 28/02/2027 (eleven months).

2. Rent. The monthly rent is ₹18,500 (Rupees Eighteen Thousand Five Hundred only), payable on or before the 5th of every month by bank transfer to A/c No. 501004567890, IFSC HDFC0001234.

3. Security deposit. The tenant has paid a security deposit of ₹37,000, refundable at the end of the tenancy after deducting unpaid dues and damages, if any.

4. Maintenance. Society maintenance of ₹1,500 per month is included in the rent. Electricity and water bills are paid by the tenant.""",
    """5. Lock-in and notice. There is a lock-in period of six months. After the lock-in, either party may end this agreement by giving a notice period of two months in writing.

6. Use. The premises will be used only for residence. Pets are allowed with the landlord's written consent.

हिंदी सारांश

मकान मालिक: सुनीता वर्मा (डेमो)
किरायेदार: अर्जुन मेहता (डेमो)
मासिक किराया ₹18,500 है, जो हर महीने की 5 तारीख तक देय है।
सिक्योरिटी डिपॉज़िट ₹37,000 है, जो किरायानामा समाप्त होने पर लौटाया जाएगा।
किरायानामा 01/04/2026 से 28/02/2027 तक मान्य है।
लॉक-इन अवधि छह महीने है। इसके बाद दो महीने का लिखित नोटिस देकर अनुबंध समाप्त किया जा सकता है।
पालतू जानवर मकान मालिक की लिखित सहमति से रखे जा सकते हैं।

Signed: Landlord (DEMO)    Tenant (DEMO)    Witnesses: 1. Demo Witness  2. Demo Witness""",
]

BILL = [
    """DEMO POWER DISTRIBUTION LTD. - ELECTRICITY BILL (FICTIONAL)
बिजली बिल

Consumer name: Arjun Mehta (DEMO)
Consumer number: DEMO-4471-0098
Address: Flat 204, Demo Residency, Sector 62, Noida
Registered mobile: 98765 43210

Billing period: 01 Sep 2026 to 30 Sep 2026
Bill date: 05/10/2026
Tariff: Domestic (LMV-1), sanctioned load 3 kW

Meter reading: previous 18,402, current 18,714
Units consumed: 312 kWh (खपत यूनिट)

Energy charges: ₹2,184.00
Fixed charges: ₹330.00
Electricity duty: ₹332.00

Amount due: ₹2,846 (देय राशि)
Due date: 20/10/2026 (अंतिम तिथि)
Late payment surcharge of 1.25% per month applies after the due date.

Pay online with your consumer number, or at any Demo Power cash counter."""
]

KHASRA = [
    """उत्तर प्रदेश भू-अभिलेख (डेमो - काल्पनिक दस्तावेज़)
खतौनी / खसरा उद्धरण

ज़िला: गौतम बुद्ध नगर
तहसील: सदर
ग्राम: डेमोपुर

खसरा संख्या: 512/3
खातेदार का नाम: रामप्रसाद (डेमो), पुत्र श्री हरिप्रसाद (डेमो)
आधार: २३४५ ६७८९ ०१२६
मोबाइल: ९८७६५४३२१०

क्षेत्रफल: 0.253 हेक्टेयर
भूमि का प्रकार: कृषि (सिंचित)
फसल: गेहूँ (रबी 2025-26)

भार / ऋण: कोई ऋण दर्ज नहीं है।
यह उद्धरण केवल सूचना के लिए है। (DEMO: not a real record)"""
]

DOCS = {
    "rent-agreement-bilingual": RENT,
    "electricity-bill": BILL,
    "khasra-khatauni-hindi": KHASRA,
}

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: "Nirmala UI", "Noto Sans Devanagari", "Segoe UI", sans-serif; font-size: 12.5px; line-height: 1.6; color: #111; }
.page { page-break-after: always; white-space: pre-wrap; }
.page:last-child { page-break-after: auto; }
.stamp { position: fixed; top: 6mm; right: 0; color: #b91c1c; border: 2px solid #b91c1c; padding: 2px 8px; font-weight: 700; transform: rotate(4deg); }
"""


def render(name: str, pages: list[str], edge: str) -> None:
    body = "".join(f'<div class="page">{html.escape(p)}</div>' for p in pages)
    doc = f'<!doctype html><html lang="hi"><meta charset="utf-8"><style>{CSS}</style><div class="stamp">DEMO · डेमो</div>{body}</html>'
    target = OUT / f"{name}.pdf"
    target.unlink(missing_ok=True)
    # Not deleted automatically: Edge keeps files in its profile open for a while after it exits.
    tmp = tempfile.mkdtemp(prefix="kaagaz-demo-")
    src = Path(tmp) / f"{name}.html"
    src.write_text(doc, encoding="utf-8")
    subprocess.run(
        [
            edge,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            f"--user-data-dir={tmp}\\profile",
            "--no-pdf-header-footer",
            f"--print-to-pdf={target}",
            src.as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    # The Edge launcher can return before the PDF is fully written: wait until it exists and stops growing.
    last = -1
    for _ in range(60):
        size = target.stat().st_size if target.exists() else -1
        if size > 0 and size == last:
            break
        last = size
        time.sleep(0.5)
    else:
        raise SystemExit(f"Edge did not write {target.name}")
    shutil.rmtree(tmp, ignore_errors=True)
    (OUT / f"{name}.pages.json").write_text(
        json.dumps(
            {
                "source": "prepared text (stands in for an OCR result)",
                "pages": [{"page": i + 1, "text": p} for i, p in enumerate(pages)],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )


def main() -> None:
    edge = next((p for p in EDGE_PATHS if Path(p).exists()), shutil.which("msedge"))
    if not edge:
        raise SystemExit("Microsoft Edge not found")
    OUT.mkdir(exist_ok=True)
    for name, pages in DOCS.items():
        render(name, pages, edge)
        print("wrote", name)


if __name__ == "__main__":
    main()
