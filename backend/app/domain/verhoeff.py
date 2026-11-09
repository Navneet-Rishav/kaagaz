"""Verhoeff checksum, used by UIDAI for the last digit of every Aadhaar number.

It catches every single-digit error and every swap of two adjacent digits, which is why a random
12-digit number (an invoice number, a phone number with a prefix) almost never passes. We use it to
avoid masking 12-digit numbers that are not Aadhaar numbers.
"""

# Multiplication table of the dihedral group D5.
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
# Permutation applied by position.
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 2, 4, 1),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 8, 0, 6, 7),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def _digits(number: str) -> list[int] | None:
    s = number.replace(" ", "").replace("-", "")
    if not s or not s.isascii() or not s.isdigit():
        return None
    return [int(c) for c in s]


def verhoeff_valid(number: str) -> bool:
    """True if the number (spaces and hyphens ignored) ends in a correct Verhoeff check digit."""
    digits = _digits(number)
    if digits is None:
        return False
    c = 0
    for i, d in enumerate(reversed(digits)):
        c = _D[c][_P[i % 8][d]]
    return c == 0


def verhoeff_check_digit(number: str) -> int:
    """The digit to append to `number` so that the result is Verhoeff-valid."""
    digits = _digits(number)
    if digits is None:
        raise ValueError("number must contain only digits")
    c = 0
    for i, d in enumerate(reversed(digits)):
        c = _D[c][_P[(i + 1) % 8][d]]
    return _INV[c]
