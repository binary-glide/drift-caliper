"""``sigma_estimate`` is a validated invariant of every ``Fitted*`` type (BIN-119).

`code-reviewer`'s review of the BIN-119/BIN-120 fix (2026-09-11), blocker 1:
the acceptance criterion "No artefact with ``sigma_estimate=inf`` can be
constructed" was not actually met by guarding ``_moving_range_sigma`` alone
(``tests/unit/baseline/test_spc_numerics.py``,
``tests/unit/baseline/test_{ewma,cusum,shewhart}_fitting.py``) -- that guard
is reachable only through the three ``fit_*()`` functions, and every
``Fitted*`` type is exported at the ``caliper`` top level with no field
validator of its own, so direct construction (a third-party adapter, a
future refactor, a test helper) could still build one with
``sigma_estimate=inf``, ``0.0``, or (not named by the original review,
found while implementing this fix) ``nan``.

This file pins the fix: ``FittedEWMA``/``FittedCUSUM``/``FittedShewhart``
each gain a ``@field_validator("sigma_estimate")`` mirroring
``ScoringResult.must_be_finite`` (``tests/unit/measurement/`` -- see that
validator's own test for the identical shape on a different field), raising
``InvalidParameterError`` -- not ``DegenerateBaselineError``, which is a
Phase I *baseline* diagnosis and has no baseline in scope at a bare
constructor call. See each ``Fitted*.must_be_finite_and_positive``
docstring for the full reasoning on why both guards -- this one and
``_moving_range_sigma``'s -- earn their place rather than one replacing the
other.

**Direct construction, deliberately.** Every other test file for these
three types states the opposite convention ("no new factory... every test
obtains its FittedEWMA by calling fit_ewma()") because those files test
*fitting behaviour* -- what a real calibration produces. This file tests
the *type's own invariant*, which by definition cannot be observed through
a fitting function that already guarantees a valid ``sigma_estimate``
reaches the constructor. A real fitted instance's own field values (via
``model_dump()``) supply every field this file does not care about, so the
only value asserted about at each call site is ``sigma_estimate`` itself --
the same "construct directly with the exact literal under test" principle
``tests/factories.py``'s module docstring states for boundary-value tests.
"""

from __future__ import annotations

import math

import pytest

from drift_caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedCUSUM,
    FittedEWMA,
    FittedShewhart,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from drift_caliper.errors import InvalidParameterError
from tests.factories import ProvenanceFactory, ScoringResultFactory

_SHAPE_TEST_TARGET_ARL = 370.0


def _sufficient_baseline() -> Baseline:
    """A baseline that is sufficient and non-degenerate, for fitting.

    Mirrors the identically-named helper each sibling fitting test file
    already has -- duplicated here rather than imported (each is private
    to its own module), for the same reason ``tests/unit/test_truthiness.py``
    gives for its own copy: this file only needs one real, validly-fitted
    artefact per chart type to read field values off, not any of those
    files' fitting-behaviour setup.
    """
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for _ in range(DEFAULT_SUFFICIENCY_THRESHOLD + 5):
        baseline.record(ScoringResultFactory(provenance=shared_provenance))
    return baseline


def _valid_ewma_fields() -> dict[str, object]:
    """Every field a real ``fit_ewma()`` call produces, as a plain dict."""
    artefact = fit_ewma(_sufficient_baseline(), target_arl=_SHAPE_TEST_TARGET_ARL)
    return artefact.model_dump()


def _valid_cusum_fields() -> dict[str, object]:
    """Every field a real ``fit_cusum()`` call produces, as a plain dict."""
    artefact = fit_cusum(_sufficient_baseline(), target_arl=_SHAPE_TEST_TARGET_ARL)
    return artefact.model_dump()


def _valid_shewhart_fields() -> dict[str, object]:
    """Every field a real ``fit_shewhart()`` call produces, as a plain dict."""
    artefact = fit_shewhart(_sufficient_baseline(), target_arl=_SHAPE_TEST_TARGET_ARL)
    return artefact.model_dump()


# --- FittedEWMA ------------------------------------------------------------------


@pytest.mark.parametrize("bad_sigma", [math.inf, -math.inf, math.nan, 0.0, -1.0])
def test_fitted_ewma_rejects_a_non_finite_or_non_positive_sigma_estimate(
    bad_sigma: float,
) -> None:
    """No ``FittedEWMA`` may be constructed with an unusable ``sigma_estimate``.

    Constructed directly -- not via ``fit_ewma()``, which already cannot
    produce any of these values (BIN-119) -- to prove the type itself
    refuses them regardless of caller.
    """
    # Arrange
    fields = _valid_ewma_fields() | {"sigma_estimate": bad_sigma}

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        FittedEWMA(**fields)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "sigma_estimate"
    assert error.context["kind"] == "invalid"


def test_fitted_ewma_accepts_a_genuinely_valid_sigma_estimate() -> None:
    """Regression guard: the new validator must not reject an ordinary value."""
    # Arrange
    fields = _valid_ewma_fields()

    # Act -- must not raise
    artefact = FittedEWMA(**fields)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    assert math.isfinite(artefact.sigma_estimate)
    assert artefact.sigma_estimate > 0.0


# --- FittedCUSUM -----------------------------------------------------------------


@pytest.mark.parametrize("bad_sigma", [math.inf, -math.inf, math.nan, 0.0, -1.0])
def test_fitted_cusum_rejects_a_non_finite_or_non_positive_sigma_estimate(
    bad_sigma: float,
) -> None:
    """No ``FittedCUSUM`` may be constructed with an unusable ``sigma_estimate``."""
    # Arrange
    fields = _valid_cusum_fields() | {"sigma_estimate": bad_sigma}

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        FittedCUSUM(**fields)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "sigma_estimate"
    assert error.context["kind"] == "invalid"


def test_fitted_cusum_accepts_a_genuinely_valid_sigma_estimate() -> None:
    """Regression guard: the new validator must not reject an ordinary value."""
    # Arrange
    fields = _valid_cusum_fields()

    # Act -- must not raise
    artefact = FittedCUSUM(**fields)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    assert math.isfinite(artefact.sigma_estimate)
    assert artefact.sigma_estimate > 0.0


# --- FittedShewhart --------------------------------------------------------------


@pytest.mark.parametrize("bad_sigma", [math.inf, -math.inf, math.nan, 0.0, -1.0])
def test_fitted_shewhart_rejects_a_non_finite_or_non_positive_sigma_estimate(
    bad_sigma: float,
) -> None:
    """No ``FittedShewhart`` may be constructed with an unusable ``sigma_estimate``."""
    # Arrange
    fields = _valid_shewhart_fields() | {"sigma_estimate": bad_sigma}

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        FittedShewhart(**fields)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "sigma_estimate"
    assert error.context["kind"] == "invalid"


def test_fitted_shewhart_accepts_a_genuinely_valid_sigma_estimate() -> None:
    """Regression guard: the new validator must not reject an ordinary value."""
    # Arrange
    fields = _valid_shewhart_fields()

    # Act -- must not raise
    artefact = FittedShewhart(**fields)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    assert math.isfinite(artefact.sigma_estimate)
    assert artefact.sigma_estimate > 0.0
