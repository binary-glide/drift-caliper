"""Unit tests for ``Baseline.check_sufficiency()`` (BIN-64).

Pins the twelve acceptance scenarios in
``tests/bdd/features/baseline/baseline-sufficiency-check.feature``, plus a
handful of boundary/property cases the feature file's business rules
require but do not name as separate scenarios (BR-8's "threshold=1 is
valid" note; the mathematical relationship between count, threshold, and
gap, via Hypothesis). Error assertions follow ADR-002/ADR-008: type +
required ``context`` keys only -- never message text.

``SufficiencyResult`` and ``DataQualityConcern`` exist only as scaffolded
value objects (``src/caliper/baseline/domain/``), and
``Baseline.check_sufficiency()`` is a scaffold that always raises
``NotImplementedError`` -- every test below that calls it is expected to
fail for that reason until ``domain-implementer`` replaces the scaffold.
``uv run pytest`` therefore fails: that is the correct state for this
ticket (TDD red phase), the same shape as BIN-63's
``Baseline.record()`` scaffold.

**The default threshold is never hardcoded.** ADR-005 sets the library
default at 100 observations, documented as a configurable default, not an
invariant -- no test here asserts a literal ``100``. Every assertion that
depends on the default threshold's value is expressed relative to the
imported ``DEFAULT_SUFFICIENCY_THRESHOLD`` constant, so changing the
default in ``src`` changes zero lines here. The same discipline applies to
SC8's per-chart-type threshold: the test chooses its own value, holds it in
a variable, and asserts the result used *that* value -- never a specific
literal figure compared independently.

**Two decisions this file makes, flagged rather than guessed silently:**

1. **The per-chart-type mechanism (SC8).** ``docs/domain-model.md``'s
   Object Map gives the operation signature as
   ``check_sufficiency(threshold?, chart_type?)`` -- two independent
   optional parameters, no separate "chart-type threshold registry" object
   anywhere in the domain model or PRD. ``requirements-review.md``
   explicitly confirms SC8 "tests the mechanism ... without requiring that
   thresholds differ" -- i.e. it does not commit to *how* per-chart-type
   defaults would be resolved automatically, only that an explicit
   ``(threshold, chart_type)`` pair is honoured over the general default.
   This file tests exactly that: the engineer supplies both an explicit
   threshold *and* a chart type together (mirroring how two different
   chart types would be checked, one call each), and the explicit
   threshold governs. It also separately tests that ``chart_type`` alone
   (no explicit ``threshold``) falls back to the general default, citing
   ADR-005 ("all chart types share the 100-observation default" until the
   simulation study) -- this is a design decision this test file commits
   to, not one dictated by any single scenario, and it is called out here
   for that reason.
2. **``DataQualityConcern.kind`` for the zero-variance case.** Unlike
   ``ProvenanceMismatchError.context["dimension"]`` (BIN-63), which had no
   canonical example anywhere and was deliberately left unpinned,
   ``docs/domain-model.md``'s Value Object Inventory gives a concrete
   worked example for this exact field: ``kind: str -- "E.g.,
   \"zero_variance\""``. Because this is the *only* ``DataQualityConcern``
   kind this story introduces (OQ-1 explicitly closes the door on
   additional concern types for BIN-64), there is no sibling case to
   distinguish it from the way SC5/SC6 distinguished model-version from
   criteria mismatches without pinning either string. Given a concrete,
   documented example and no competing candidate, this file pins
   ``kind == "zero_variance"`` rather than leaving it unconstrained --
   flagged here so a different implementation choice is a deliberate,
   visible decision, not a silently broken test.

Uses ``ScoringResultFactory``/``ProvenanceFactory`` (``tests/factories.py``)
for observations where the specific score does not matter, per
``tests/factories.py``'s own guidance. No new factory was added for
``SufficiencyResult`` or ``DataQualityConcern``: every test obtains its
``SufficiencyResult`` by calling ``check_sufficiency()`` -- never by
constructing one directly -- so a factory for it would have no caller.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    DataQualityConcern,
    SufficiencyResult,
)
from caliper.errors import InvalidParameterError
from tests.factories import ProvenanceFactory, ScoringResultFactory

# The only DataQualityConcern.kind this story introduces -- see the module
# docstring's "decisions" section for why this is pinned rather than left
# generic, unlike ADR-002's context["dimension"].
_ZERO_VARIANCE_CONCERN_KIND = "zero_variance"

# An arbitrary fixed score used only to make every observation identical.
# Its value carries no meaning beyond "not distinct from the others".
_IDENTICAL_SCORE = 0.62


def _baseline_with_observations(count: int, *, score: float | None = None) -> Baseline:
    """Build a ``Baseline`` with ``count`` recorded observations.

    All observations share one ``Provenance`` so recording never raises
    ``ProvenanceMismatchError`` -- that invariant is BIN-63's concern, not
    this story's. When ``score`` is given, every observation carries that
    exact value (the zero-variance scenarios); otherwise each observation
    gets an independently varying score from the factory default, which is
    what every non-zero-variance scenario needs to *not* accidentally
    collide.
    """
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for _ in range(count):
        if score is None:
            baseline.record(ScoringResultFactory(provenance=shared_provenance))
        else:
            baseline.record(
                ScoringResultFactory(provenance=shared_provenance, score=score)
            )
    return baseline


# --- SC1: happy path -- baseline meets or exceeds the minimum ----------------


def test_reports_sufficient_count_and_threshold_when_baseline_exceeds_the_minimum() -> (
    None
):
    """SC1: a baseline above the default threshold is sufficient, with no gap."""
    # Arrange
    margin = 8
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + margin)

    # Act
    result = baseline.check_sufficiency()

    # Assert
    assert isinstance(result, SufficiencyResult)
    assert result.is_sufficient is True
    assert result.observation_count == DEFAULT_SUFFICIENCY_THRESHOLD + margin
    assert result.threshold == DEFAULT_SUFFICIENCY_THRESHOLD
    assert result.gap == 0


# --- SC2: sad path -- baseline has fewer than the minimum --------------------


def test_reports_insufficient_count_threshold_and_gap_when_below_the_minimum() -> None:
    """SC2: a baseline below the default threshold is insufficient, gap reported."""
    # Arrange
    shortfall = 15
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD - shortfall)

    # Act
    result = baseline.check_sufficiency()

    # Assert
    assert result.is_sufficient is False
    assert result.observation_count == DEFAULT_SUFFICIENCY_THRESHOLD - shortfall
    assert result.threshold == DEFAULT_SUFFICIENCY_THRESHOLD
    assert result.gap == shortfall


# --- SC3: boundary -- exactly the minimum -------------------------------------


def test_reports_sufficient_and_zero_gap_when_baseline_has_exactly_the_minimum() -> (
    None
):
    """SC3: a baseline at exactly the default threshold is sufficient, gap zero."""
    # Arrange
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD)

    # Act
    result = baseline.check_sufficiency()

    # Assert
    assert result.is_sufficient is True
    assert result.observation_count == DEFAULT_SUFFICIENCY_THRESHOLD
    assert result.gap == 0


# --- SC4: edge -- empty baseline ----------------------------------------------


def test_reports_insufficient_zero_count_and_full_gap_for_empty_baseline() -> None:
    """SC4: an empty baseline is insufficient; the gap equals the full threshold."""
    # Arrange
    baseline = Baseline()

    # Act
    result = baseline.check_sufficiency()

    # Assert
    assert result.is_sufficient is False
    assert result.observation_count == 0
    assert result.threshold == DEFAULT_SUFFICIENCY_THRESHOLD
    assert result.gap == DEFAULT_SUFFICIENCY_THRESHOLD


# --- SC5: configurable threshold ----------------------------------------------


def test_uses_the_engineers_configured_threshold_instead_of_the_library_default() -> (
    None
):
    """SC5: a custom threshold overrides the default, in effect and in the report."""
    # Arrange
    custom_threshold = DEFAULT_SUFFICIENCY_THRESHOLD // 2
    baseline = _baseline_with_observations(custom_threshold)

    # Act
    result = baseline.check_sufficiency(threshold=custom_threshold)

    # Assert
    assert result.threshold == custom_threshold
    assert result.is_sufficient is True
    assert result.gap == 0
    # Contrast: the identical baseline would NOT meet the library default --
    # proving the custom threshold actually governed the determination
    # rather than merely being echoed back while the default silently applied.
    assert baseline.check_sufficiency().is_sufficient is False


def test_threshold_of_one_is_valid_even_though_too_small_to_be_meaningful() -> None:
    """BR-8 note: validity (positive) and statistical sufficiency differ.

    ``threshold=1`` is valid per BR-8 even though it is almost certainly
    too small for reliable parameter estimation -- see the feature file's
    pending-decision block and PRD BR-8.
    """
    # Arrange
    baseline = _baseline_with_observations(1)

    # Act
    result = baseline.check_sufficiency(threshold=1)

    # Assert
    assert result.is_sufficient is True
    assert result.threshold == 1
    assert result.gap == 0


# --- SC6: temporal -- reflects observations recorded since the last check ----


def test_reflects_additional_observations_recorded_since_the_previous_check() -> None:
    """SC6: a second check after recording more observations shows the updated gap."""
    # Arrange
    additional_observations = 4
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD - 10)
    first = baseline.check_sufficiency()
    assert first.is_sufficient is False  # precondition for this scenario

    # Act
    for _ in range(additional_observations):
        baseline.record(ScoringResultFactory(provenance=baseline.provenance_signature))
    second = baseline.check_sufficiency()

    # Assert
    assert second.observation_count == first.observation_count + additional_observations
    assert second.gap == first.gap - additional_observations
    assert (
        second.is_sufficient is False
    )  # still short -- not the sufficiency boundary itself


# --- SC7: zero variance flagged alongside a sufficient count -----------------


def test_flags_zero_variance_when_count_is_met_but_scores_are_identical() -> None:
    """SC7: an all-identical baseline meeting the count threshold is still flagged."""
    # Arrange
    baseline = _baseline_with_observations(
        DEFAULT_SUFFICIENCY_THRESHOLD, score=_IDENTICAL_SCORE
    )

    # Act
    result = baseline.check_sufficiency()

    # Assert -- count-based determination and the data quality concern co-exist
    assert result.is_sufficient is True
    assert len(result.data_quality_concerns) == 1
    concern = result.data_quality_concerns[0]
    assert isinstance(concern, DataQualityConcern)
    assert concern.kind == _ZERO_VARIANCE_CONCERN_KIND
    assert isinstance(concern.description, str)
    assert concern.description != ""


# --- SC8: per-chart-type threshold --------------------------------------------


def test_uses_the_chart_types_threshold_rather_than_the_general_default() -> None:
    """SC8: an explicit (threshold, chart_type) pair governs over the general default.

    See the module docstring's "decisions" section for why this is the
    mechanism under test rather than an automatic per-chart-type lookup.
    """
    # Arrange -- sufficient under the general default ...
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD)
    stricter_threshold = (
        DEFAULT_SUFFICIENCY_THRESHOLD + 25
    )  # ... but not under this chart type

    # Act
    result = baseline.check_sufficiency(threshold=stricter_threshold, chart_type="ewma")

    # Assert
    assert result.threshold == stricter_threshold
    assert result.is_sufficient is False
    # Contrast: the same baseline IS sufficient under the general default.
    assert baseline.check_sufficiency().is_sufficient is True


def test_chart_type_alone_without_a_threshold_falls_back_to_the_library_default() -> (
    None
):
    """BR-5: ``chart_type`` does not force an explicit threshold.

    Per ADR-005, all chart types currently share the single default -- no
    per-chart-type default mapping exists yet. Passing ``chart_type`` alone
    must not error and must not silently apply some other threshold.
    """
    # Arrange
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD)

    # Act
    result = baseline.check_sufficiency(chart_type="shewhart")

    # Assert
    assert result.threshold == DEFAULT_SUFFICIENCY_THRESHOLD
    assert result.is_sufficient is True


# --- SC9: read-only inspection -------------------------------------------------


def test_check_sufficiency_does_not_modify_the_baseline() -> None:
    """SC9: calling check_sufficiency() leaves the baseline exactly as it was."""
    # Arrange
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD // 3)
    observation_count_before = baseline.observation_count
    # Exact sequence, not just the count -- a count-only assertion would not
    # catch a mutant that left the count unchanged while corrupting the
    # underlying observations (the same pattern BIN-63's review caught).
    observations_before = tuple(baseline.observations)
    signature_before = baseline.provenance_signature

    # Act
    baseline.check_sufficiency()

    # Assert
    assert baseline.observation_count == observation_count_before
    assert tuple(baseline.observations) == observations_before
    assert baseline.provenance_signature == signature_before


# --- Boundary: one fewer than the minimum -------------------------------------


def test_reports_gap_of_one_when_baseline_has_one_fewer_than_the_minimum() -> None:
    """SC10: a baseline one short of the minimum reports a gap of exactly one."""
    # Arrange
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD - 1)

    # Act
    result = baseline.check_sufficiency()

    # Assert
    assert result.is_sufficient is False
    assert result.gap == 1


# --- SC11: invalid threshold configuration ------------------------------------


@pytest.mark.parametrize("invalid_threshold", [0, -1], ids=["zero", "negative"])
def test_raises_invalid_parameter_error_for_non_positive_threshold(
    invalid_threshold: int,
) -> None:
    """SC11: zero and negative thresholds are rejected as invalid parameters."""
    # Arrange
    baseline = Baseline()

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        baseline.check_sufficiency(threshold=invalid_threshold)

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["kind"] == "invalid"
    assert error.context["parameter"] == "threshold"
    assert error.context["provided"] == invalid_threshold
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


# --- SC12: combined -- insufficient count and zero variance ------------------


def test_reports_insufficient_and_zero_variance_concern_together() -> None:
    """SC12: a baseline that is both below threshold and all-identical reports both."""
    # Arrange
    shortfall = 10
    baseline = _baseline_with_observations(
        DEFAULT_SUFFICIENCY_THRESHOLD - shortfall, score=_IDENTICAL_SCORE
    )

    # Act
    result = baseline.check_sufficiency()

    # Assert -- both conditions, independently
    assert result.is_sufficient is False
    assert result.gap == shortfall
    assert len(result.data_quality_concerns) == 1
    assert result.data_quality_concerns[0].kind == _ZERO_VARIANCE_CONCERN_KIND


# --- Property: gap and sufficiency are always arithmetic, not heuristic ------


@settings(max_examples=20, deadline=None)
@given(
    count=st.integers(min_value=0, max_value=30),
    threshold=st.integers(min_value=1, max_value=30),
)
def test_gap_and_sufficiency_follow_the_count_and_threshold_for_any_combination(
    count: int, threshold: int
) -> None:
    """gap == max(0, threshold - count); is_sufficient == (count >= threshold)."""
    # Arrange
    baseline = _baseline_with_observations(count)

    # Act
    result = baseline.check_sufficiency(threshold=threshold)

    # Assert
    assert result.observation_count == count
    assert result.threshold == threshold
    assert result.gap == max(0, threshold - count)
    assert result.is_sufficient == (count >= threshold)


# --- Zero-variance boundary (mutation-testing findings, BIN-64 review) ---
#
# `_zero_variance_concerns` guards on two thresholds, and mutmut showed both
# were unpinned: `len(observations) < 2` survived mutation to `<= 2`, and
# `len(distinct_scores) > 1` survived mutation to `> 2`. Coverage was already
# 100% on the function -- every line ran, but nothing constrained where the
# boundaries sat. These three tests pin them.


def test_flags_zero_variance_when_exactly_two_observations_share_a_score() -> None:
    # Arrange -- two is the smallest count at which variance is defined, and
    # the exact point the `< 2` guard must stop suppressing the concern.
    baseline = _baseline_with_observations(2, score=0.75)

    # Act
    result = baseline.check_sufficiency()

    # Assert
    assert len(result.data_quality_concerns) == 1
    assert result.data_quality_concerns[0].kind == _ZERO_VARIANCE_CONCERN_KIND


def test_reports_no_zero_variance_concern_when_the_baseline_holds_one_observation() -> (
    None
):
    # Arrange -- sample variance is undefined for a singleton, so the concern
    # must not fire however tempting a "all scores identical" reading is.
    baseline = _baseline_with_observations(1, score=0.75)

    # Act
    result = baseline.check_sufficiency()

    # Assert
    assert result.data_quality_concerns == ()


def test_reports_no_zero_variance_concern_when_exactly_two_scores_differ() -> None:
    # Arrange -- two distinct values is the smallest genuine variance there
    # can be, and the exact point the `> 1` guard must start suppressing.
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    baseline.record(ScoringResultFactory(provenance=shared_provenance, score=0.25))
    baseline.record(ScoringResultFactory(provenance=shared_provenance, score=0.75))

    # Act
    result = baseline.check_sufficiency()

    # Assert
    assert result.data_quality_concerns == ()


# --- Documented immutability must actually hold (BIN-108) ---
#
# `ConfigDict(frozen=True)` stops a field being *rebound*; it does not freeze
# what the field points at. While `data_quality_concerns` held a list, this
# type's documented "Immutable after creation" was false — a caller could
# `.append()` to a result the domain model promises cannot change, and no test
# noticed, at 100% line coverage.


def test_rejects_in_place_mutation_of_the_data_quality_concerns() -> None:
    # Arrange -- a baseline that genuinely produces a concern, so there is a
    # populated sequence to attempt to mutate.
    baseline = _baseline_with_observations(2, score=0.75)
    result = baseline.check_sufficiency()
    concerns_before = result.data_quality_concerns

    # Act / Assert -- a tuple has no `append`, so the attempt fails rather
    # than silently succeeding as it did before BIN-108.
    with pytest.raises(AttributeError):
        result.data_quality_concerns.append(  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            DataQualityConcern(kind="injected", description="should not land")
        )

    assert result.data_quality_concerns == concerns_before


def test_rejects_rebinding_the_data_quality_concerns() -> None:
    # Arrange
    baseline = _baseline_with_observations(2, score=0.75)
    result = baseline.check_sufficiency()

    # Act / Assert -- the frozen-model half of the guarantee, which was
    # already true; asserted here so both halves are pinned together.
    with pytest.raises(ValidationError):
        result.data_quality_concerns = ()  # ty: ignore[invalid-assignment]


def test_result_is_hashable_so_it_can_be_used_as_a_key_or_set_member() -> None:
    # Arrange -- a consequence of the same defect: a list-typed field made
    # this "equality by value" type unhashable, so it could not go in a set.
    baseline = _baseline_with_observations(2, score=0.75)

    # Act
    result = baseline.check_sufficiency()

    # Assert
    assert len({result, baseline.check_sufficiency()}) == 1
