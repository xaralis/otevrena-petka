"""Hledání usnesení: a resolution's number in the query (petka.usneseni.search.numbers)."""

import pytest

from petka.usneseni.search import numbers


@pytest.mark.parametrize("q, found, rest", [
    ("154/2025", [(154, 2025, None)], ""),
    ("154/2025 Z", [(154, 2025, "Z")], ""),
    ("154/25", [(154, 2025, None)], ""),                       # a two-digit year
    ("č. 154/2025", [(154, 2025, None)], ""),
    ("usnesení č. 154/2025 Z", [(154, 2025, "Z")], ""),
    ("154-2025-z", [(154, 2025, "Z")], ""),                    # the uid of the detail's address
    ("154", [(154, None, None)], ""),                          # a bare number: any year
    ("310/2026 R a 311/2026 R", [(310, 2026, "R"), (311, 2026, "R")], ""),
    ("zrušení usnesení 154/2025 Z", [(154, 2025, "Z")], "zrušení"),   # among other words: first, not alone
    ("2025", [], "2025"),                                      # a year is not a number
    ("parkování", [], "parkování"),
])
def test_numbers(q, found, rest):
    assert numbers(q) == (found, rest)
