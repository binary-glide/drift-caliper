"""The Bernoulli CUSUM refusal contract, driven row by row (ADR-014 Decision 17).

Decision 18 items 10, 23 and 27. Every emission site in
``fit_bernoulli_cusum`` and ``Monitor``'s Bernoulli branch is a row of
``tests.support.exception_contract_registry.BERNOULLI_REFUSAL_CONTRACT``
(Decision 17, extended by Decision 19.5's F15, corrigendum C2's F16, C4's
missing-lattice M2 variant, C6/C12.2's ``provided``/``provided_type`` split
and C10's three F14 figures). This file drives each one through the public
API and asserts:

- the error's type (ADR-002/ADR-008: ``isinstance`` plus ``context`` keys,
  never message text);
- the **full** key set -- every required key present, with its contracted
  value where the row names one -- and the keys whose absence is contracted;
- C6/C12.2: an ``invalid``-kind ``InvalidParameterError`` carries exactly one
  of ``provided``/``provided_type`` (``provided_type`` only on the
  ``require_exact_str`` family -- F8's not-a-``str`` path, M2's type failures,
  C4, M3; F1/F4/F6 keep ``provided``);
- BIN-122 / BIN-134: every reported bound round-trips -- passed back, it is
  accepted.

**Why a registry and not inline tests.** The shipped code missed three
required keys (the ceiling and joint-cap refusals had no ``constraint``, the
search-cap refusal had no ``provided``) and the amendment found a fourth
(``score_not_binary`` had no ``provided``), each because a row was
hand-rolled and nobody asserted its whole key set (Amendment 2 section 0,
defect 6). ``test_every_decision_17_row_is_registered`` makes a missing row a
failure rather than an omission.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from drift_caliper.errors import CaliperError, InvalidParameterError
from tests.support.exception_contract_registry import (
    BERNOULLI_CONTRACT_ROWS,
    BERNOULLI_REFUSAL_CONTRACT,
    PRESENT,
    RefusalContractRow,
)

_IDS = [row.row for row in BERNOULLI_REFUSAL_CONTRACT]


def _raised(row: RefusalContractRow) -> Mapping[str, Any]:
    with pytest.raises(row.error_type) as excinfo:
        row.invoke()
    error = excinfo.value
    assert isinstance(error, CaliperError)
    context: Mapping[str, Any] = error.context
    return context


def test_every_decision_17_row_is_registered() -> None:
    """Decision 17: "Every row above is registered in
    ``tests/support/exception_contract_registry.py``" -- F1-F16 and M1-M3."""
    registered = {row.row.split("_")[0] for row in BERNOULLI_REFUSAL_CONTRACT}

    assert registered == BERNOULLI_CONTRACT_ROWS


def test_all_three_f14_figures_are_enumerated() -> None:
    """Corrigendum C10: F14's ``figure`` is one of three values, all enumerated."""
    figures = {
        row.expected["figure"]
        for row in BERNOULLI_REFUSAL_CONTRACT
        if row.row.startswith("F14")
    }

    assert figures == {
        "achieved_arl",
        "expected_detection_arl",
        "expected_improvement_detection_arl",
    }


@pytest.mark.parametrize("row", BERNOULLI_REFUSAL_CONTRACT, ids=_IDS)
# Budget: every row is a single small fit (m <= 1,000, caps patched where a
# cap is the subject) -- the slowest, F14's two-sided poison at m=300 f=3, is
# 0.53 s in the reference implementation; x3 = 1.6 s. 20 s bounds a hang
# (the shipped linear scan hangs on F16's below-resolution row).
@pytest.mark.timeout(20)
def test_the_row_carries_its_complete_context(row: RefusalContractRow) -> None:
    context = _raised(row)

    missing = sorted(key for key in row.expected if key not in context)
    assert missing == [], f"{row.row}: missing required keys {missing}"
    for key, value in row.expected.items():
        if value is not PRESENT:
            assert context[key] == value, f"{row.row}: context[{key!r}]"
    forbidden = sorted(key for key in row.absent if key in context)
    assert forbidden == [], f"{row.row}: keys that must be absent {forbidden}"


@pytest.mark.parametrize(
    "row",
    [
        row
        for row in BERNOULLI_REFUSAL_CONTRACT
        if row.error_type is InvalidParameterError
        and row.expected.get("kind") == "invalid"
    ],
    ids=lambda row: row.row,
)
@pytest.mark.timeout(20)
def test_exactly_one_of_provided_and_provided_type(row: RefusalContractRow) -> None:
    """Corrigendum C6 as corrected by C12.2 / Decision 18 items 23 and 27."""
    context = _raised(row)

    assert ("provided" in context) != ("provided_type" in context), row.row


@pytest.mark.parametrize(
    "row",
    [row for row in BERNOULLI_REFUSAL_CONTRACT if row.round_trip is not None],
    ids=lambda row: row.row,
)
# Budget: the refusal plus one or two accepting fits at the reported bound --
# the slowest is F5's ``max_value`` round-trip, a one-sided lower fit at
# 10^6 on m=105 f=10 (reference < 0.05 s). 20 s bounds a hang.
@pytest.mark.timeout(20)
def test_every_reported_bound_round_trips(row: RefusalContractRow) -> None:
    """BIN-122: a bound Caliper reports must be accepted when passed back
    (Decision 17; F5's bounds, F11, F12, F13 and F16's ``min_value``)."""
    context = _raised(row)
    assert row.round_trip is not None

    row.round_trip(context)
