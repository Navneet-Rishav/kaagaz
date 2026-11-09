import pytest

from app.domain.verhoeff import verhoeff_check_digit, verhoeff_valid


@pytest.mark.parametrize("number", ["2363", "123451", "2345 6789 0126"])
def test_valid_numbers(number: str) -> None:
    assert verhoeff_valid(number)


@pytest.mark.parametrize("number", ["2364", "123456", "2345 6789 0124", "", "12a4", "abcd"])
def test_invalid_numbers(number: str) -> None:
    assert not verhoeff_valid(number)


def test_check_digit_roundtrip() -> None:
    for base in ["236", "12345", "23456789012", "99999999999"]:
        assert verhoeff_valid(base + str(verhoeff_check_digit(base)))


def test_single_digit_error_is_always_caught() -> None:
    good = "23456789012" + str(verhoeff_check_digit("23456789012"))
    for i, ch in enumerate(good):
        for d in "0123456789":
            if d != ch:
                assert not verhoeff_valid(good[:i] + d + good[i + 1 :])


def test_adjacent_transposition_is_caught() -> None:
    good = "23456789012" + str(verhoeff_check_digit("23456789012"))
    for i in range(len(good) - 1):
        if good[i] != good[i + 1]:
            swapped = good[:i] + good[i + 1] + good[i] + good[i + 2 :]
            assert not verhoeff_valid(swapped)
