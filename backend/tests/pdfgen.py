"""Builds small, valid PDFs with a real (Helvetica, ASCII) text layer for upload tests."""


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[str]) -> bytes:
    objs: list[bytes] = []
    n = len(pages)
    # 1: catalog, 2: pages, 3: font, then (page, content) pairs
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(pages):
        lines = text.split("\n")
        ops = ["BT", "/F1 11 Tf", "14 TL", "50 780 Td"] + [f"({_esc(line)}) Tj T*" for line in lines] + ["ET"]
        stream = "\n".join(ops).encode("latin-1", "replace")
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


RENT_EN = [
    "RENT AGREEMENT (TEST)\nLandlord: Test Landlord\nTenant: Test Tenant, mobile 9876543210\n"
    "Property address: 12 Test Lane, Pune\nThe tenancy starts on 01/04/2026 and ends on 28/02/2027.\n"
    "The monthly rent is Rs. 18,500 payable by the 5th. Pay to A/c No. 501004567890, IFSC HDFC0001234.",
    "Security deposit of Rs. 37,000 is refundable.\nThere is a lock-in period of six months.\n"
    "After that either party may give a notice period of two months in writing.\nPets are allowed with consent.",
]
