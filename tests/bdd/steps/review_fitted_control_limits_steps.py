"""Step definitions for BIN-66: review fitted control limits and their parameters.

Binds to ``tests/bdd/features/baseline/review-fitted-control-limits.feature``
via ``tests/bdd/test_review_fitted_control_limits.py``. This story is
read-only review of an already-fitted, already-validated artefact -- there
are no error paths (PRD, "Regarding error paths"), so every step below is a
happy-path assertion. ADR-002/ADR-008's "never assert on message text" rule
therefore does not apply in its literal form (no ``CaliperError`` is ever
raised here), but its spirit -- assert on structure, not on prose -- still
governs the two human-readable-summary scenarios: the ``Then`` steps below
check label *presence*, *order*, and *section structure*, never exact
sentence wording.

Steps are kept thin, mirroring
``tests/bdd/steps/shewhart_control_limit_fitting_steps.py``: the rigorous,
mutation-resistant assertions for ``audit_summary()``'s exact label set,
order, and cross-chart-type consistency live in
``tests/unit/baseline/test_audit_summary.py`` instead, per test-patterns'
BDD guidance.

No numeric literal in this file is a claim about statistical correctness --
every concrete value below (``_VALID_TARGET_ARL``) is an arbitrary valid
input chosen only to exercise a scenario, matching every sibling fitting
step file's convention.

**Design decision this file pins** (see the backend-test-writer session
summary posted to BIN-66 for the full reasoning): the "textual
representation ... suitable for an audit log" the last two scenarios
require is a **dedicated ``audit_summary() -> str`` method** on each
concrete ``Fitted*`` type -- not ``__repr__`` or ``__str__``. BIN-110
already gave every public type a useful, *compact* ``__repr__``/``__str__``
for the debugger/REPL/log-line case (``Baseline.__repr__``,
``Provenance.__str__``/``__repr__``); an audit summary is a different,
longer-lived artefact an engineer deliberately writes to a log for a human
or an auditor to read, with a full label per field and a clearly identified
chart-specific section. Conflating the two would force ``__repr__`` to
choose between "useful in a debugger" (short) and "complete audit record"
(long, multi-line) -- the wrong trade-off, and a regression risk for every
existing test that already pins the current compact reprs. See the feature
file's Data Model note ("Whether this is ``__repr__``, ``__str__``, a
dedicated method, or another mechanism is unknown -- for system-architect")
-- this file settles it for ``domain-implementer``. ``audit_summary()`` is
NOT added to the ``FittedControlLimits`` protocol here: no scenario
requires calling it without first knowing which concrete artefact was
fitted (SC3, the chart-type-agnostic scenario, is scoped to the shared
*fields*, not the summary -- see its Then steps below), so the protocol is
left exactly as ADR-004 defined it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from pytest_bdd import given, then, when

from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedCUSUM,
    FittedEWMA,
    FittedShewhart,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from tests.factories import ProvenanceFactory, ScoringResultFactory

# Arbitrary valid input used whenever a scenario's own Given/When text does
# not itself parametrise the value under test -- matches every sibling
# fitting step file's ``_VALID_TARGET_ARL``.
_VALID_TARGET_ARL = 370.0

# The shared-core label prefixes ``audit_summary()`` must emit, in this
# exact order, identically across all three chart types (SC5). Pinned here
# because SC5 asserts "the same position and ... the same labelling" -- a
# structural property that only holds if every concrete type agrees on both
# the label text and the order. Order matches
# ``FittedControlLimits``'s own property order (ADR-004 section 2).
SHARED_AUDIT_LABELS: tuple[str, ...] = (
    "Chart type:",
    "Baseline mean:",
    "Baseline spread:",
    "Sigma estimate:",
    "Sigma estimation method:",
    "Observation count:",
    "Provenance model version:",
    "Provenance criteria:",
    "Requested ARL:",
    "Achieved ARL:",
    "Calibration method:",
)

# Deliberately hand-typed, not imported from
# `caliper.baseline.domain.audit_summary`. Importing the constant would make
# `assert CHART_SPECIFIC_HEADING in summary` read
# `assert src.CONST in render_using(src.CONST)` -- true for any value, so
# renaming the heading would still pass. The duplication IS the assertion:
# this is an independent pin of a published output contract, and the same
# reasoning applies to SHARED_AUDIT_LABELS above.
#
# Declining `code-reviewer`'s BIN-66 recommendation to import it, on the
# grounds that doing so reproduces the self-cancelling-helper defect this
# project has hit four times (see CLAUDE.md). Do not "tidy" this.
CHART_SPECIFIC_HEADING = "Chart-specific parameters:"


def _baseline_with_observations(count: int) -> Baseline:
    """Build a ``Baseline`` with ``count`` observations under shared provenance.

    Mirrors ``tests/bdd/steps/cusum_control_limit_fitting_steps.py``'s
    helper -- random per-observation scores give non-zero variance with
    overwhelming probability, which every ``fit_*`` call here requires.
    """
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for _ in range(count):
        baseline.record(ScoringResultFactory(provenance=shared_provenance))
    return baseline


@dataclass
class FittedArtefact:
    """One fitted artefact together with the baseline it was fitted from."""

    chart_type: str
    baseline: Baseline
    result: FittedEWMA | FittedCUSUM | FittedShewhart


@dataclass
class ThreeFittedArtefacts:
    """One fitted artefact per supported chart type (SC3, SC5)."""

    ewma: FittedArtefact
    cusum: FittedArtefact
    shewhart: FittedArtefact

    def __iter__(self) -> Iterator[FittedArtefact]:
        yield self.ewma
        yield self.cusum
        yield self.shewhart


def _fit_one_of_each() -> ThreeFittedArtefacts:
    ewma_baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + 5)
    cusum_baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + 5)
    shewhart_baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + 5)
    return ThreeFittedArtefacts(
        ewma=FittedArtefact(
            "ewma",
            ewma_baseline,
            fit_ewma(ewma_baseline, target_arl=_VALID_TARGET_ARL),
        ),
        cusum=FittedArtefact(
            "cusum",
            cusum_baseline,
            fit_cusum(cusum_baseline, target_arl=_VALID_TARGET_ARL),
        ),
        shewhart=FittedArtefact(
            "shewhart",
            shewhart_baseline,
            fit_shewhart(shewhart_baseline, target_arl=_VALID_TARGET_ARL),
        ),
    )


def _review_shared_fields(artefact: FittedControlLimits) -> dict[str, object]:
    """Read the shared core through the ``FittedControlLimits`` protocol only.

    Takes a ``FittedControlLimits``, not a concrete chart type -- the
    signature itself is the "chart-type-agnostic" claim SC3 makes. No
    branch anywhere in this function keys off which concrete type was
    passed; it is the single review mechanism SC3 requires.
    """
    return {
        "chart_type": artefact.chart_type,
        "baseline_mean": artefact.baseline_mean,
        "baseline_spread": artefact.baseline_spread,
        "sigma_estimate": artefact.sigma_estimate,
        "sigma_estimation_method": artefact.sigma_estimation_method,
        "observation_count": artefact.observation_count,
        "provenance_model_version": artefact.provenance_model_version,
        "provenance_criteria": artefact.provenance_criteria,
        "requested_arl": artefact.requested_arl,
        "achieved_arl": artefact.achieved_arl,
        "calibration_method": artefact.calibration_method,
    }


def _label_line_index(text: str, prefix: str) -> int:
    """The 0-based line index of the first line starting with ``prefix``."""
    for index, line in enumerate(text.splitlines()):
        if line.strip().startswith(prefix):
            return index
    raise AssertionError(f"no line starting with {prefix!r} in:\n{text}")


# --- Given: a single fitted artefact (SC1, SC4) --------------------------------------


@given(
    "the engineer has fitted control limits from a Phase I baseline",
    target_fixture="artefact",
)
def a_fitted_artefact() -> FittedArtefact:
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + 5)
    result = fit_ewma(baseline, target_arl=_VALID_TARGET_ARL)
    return FittedArtefact("ewma", baseline, result)


# --- Given: a fitted artefact from a specific (named) chart type (SC2) ---------------


@given(
    "the engineer has fitted control limits using a specific chart type",
    target_fixture="artefact",
)
def a_fitted_artefact_of_a_specific_chart_type() -> FittedArtefact:
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + 5)
    result = fit_cusum(baseline, target_arl=_VALID_TARGET_ARL)
    return FittedArtefact("cusum", baseline, result)


# --- Given: one fitted artefact per chart type (SC3, SC5) ----------------------------


@given(
    "the engineer has fitted artefacts from each of the three supported chart types",
    target_fixture="three_artefacts",
)
def three_fitted_artefacts() -> ThreeFittedArtefacts:
    return _fit_one_of_each()


# --- When: review a single artefact (SC1, SC2) ----------------------------------------


@when("they review the fitted artefact", target_fixture="artefact")
def review_the_fitted_artefact(artefact: FittedArtefact) -> FittedArtefact:
    return artefact


# --- When: review each of the three artefacts (SC3) -----------------------------------


@when("they review each artefact", target_fixture="reviews")
def review_each_artefact(
    three_artefacts: ThreeFittedArtefacts,
) -> dict[str, dict[str, object]]:
    return {
        item.chart_type: _review_shared_fields(item.result) for item in three_artefacts
    }


# --- When: obtain a textual representation of one artefact (SC4) ----------------------


@when(
    "they obtain a textual representation of the fitted artefact",
    target_fixture="summary",
)
def obtain_a_textual_representation(artefact: FittedArtefact) -> str:
    return artefact.result.audit_summary()


# --- When: obtain a textual representation of each artefact (SC5) ---------------------


@when(
    "they obtain a textual representation of each",
    target_fixture="summaries",
)
def obtain_a_textual_representation_of_each(
    three_artefacts: ThreeFittedArtefacts,
) -> dict[str, str]:
    return {item.chart_type: item.result.audit_summary() for item in three_artefacts}


# --- Then: SC1 -- complete audit-relevant information ---------------------------------


@then("the review presents the detection boundaries that define the in-control region")
def review_presents_detection_boundaries(artefact: FittedArtefact) -> None:
    result = artefact.result
    assert isinstance(result, FittedEWMA)  # SC1's Given always fits EWMA
    assert isinstance(result.ucl, float)
    assert isinstance(result.lcl, float)
    assert isinstance(result.cl, float)


@then(
    "the review presents the baseline statistics including the mean, the spread "
    "measure, and the observation count"
)
def review_presents_baseline_statistics(artefact: FittedArtefact) -> None:
    result = artefact.result
    assert isinstance(result.baseline_mean, float)
    assert isinstance(result.baseline_spread, float)
    assert result.observation_count == artefact.baseline.observation_count


@then(
    "the review presents the provenance including the judge model version and the "
    "scoring criteria"
)
def review_presents_provenance(artefact: FittedArtefact) -> None:
    signature = artefact.baseline.provenance_signature
    assert signature is not None
    result = artefact.result
    assert result.provenance_model_version == signature.model_version.value
    assert result.provenance_criteria == signature.scoring_criteria.value


@then(
    "the review presents the requested and achieved false alarm tolerance and the "
    "calibration method"
)
def review_presents_tolerance_and_calibration_method(artefact: FittedArtefact) -> None:
    result = artefact.result
    assert isinstance(result.requested_arl, float)
    assert isinstance(result.achieved_arl, float)
    assert isinstance(result.calibration_method, str)
    assert result.calibration_method != ""


@then("the review identifies which chart type the artefact represents")
def review_identifies_chart_type(artefact: FittedArtefact) -> None:
    assert artefact.result.chart_type == artefact.chart_type


# --- Then: SC2 -- chart-specific parameters alongside shared core ---------------------


@then(
    "the review presents the chart-type-specific parameters that were used or "
    "derived during fitting"
)
def review_presents_chart_specific_parameters(artefact: FittedArtefact) -> None:
    result = artefact.result
    assert isinstance(result, FittedCUSUM)  # SC2's Given fits CUSUM
    assert isinstance(result.reference_value, float)
    assert isinstance(result.decision_interval, float)
    assert isinstance(result.target_value, float)
    assert isinstance(result.direction, str)


@then(
    "the chart-specific parameters are presented alongside the shared audit information"
)
def chart_specific_parameters_alongside_shared_core(artefact: FittedArtefact) -> None:
    result = artefact.result
    assert isinstance(result, FittedCUSUM)
    # "Alongside" -- both a chart-specific field and a shared-core field
    # are reachable on the same object, through the same access pattern.
    assert isinstance(result.reference_value, float)
    assert isinstance(result.baseline_mean, float)


# --- Then: SC3 -- shared core reachable without narrowing to a chart type -------------


@then(
    "the baseline statistics, provenance, false alarm tolerance, and calibration "
    "method are presented through the same review mechanism for all three"
)
def shared_fields_via_same_mechanism(reviews: dict[str, dict[str, object]]) -> None:
    assert set(reviews.keys()) == {"ewma", "cusum", "shewhart"}
    for chart_type, fields in reviews.items():
        assert fields["chart_type"] == chart_type
        assert isinstance(fields["baseline_mean"], float)
        assert isinstance(fields["baseline_spread"], float)
        assert isinstance(fields["observation_count"], int)
        assert isinstance(fields["provenance_model_version"], str)
        assert isinstance(fields["provenance_criteria"], str)
        assert isinstance(fields["requested_arl"], float)
        assert isinstance(fields["achieved_arl"], float)
        assert isinstance(fields["calibration_method"], str)
        assert fields["calibration_method"] != ""


@then(
    "the engineer does not need to determine the chart type before reviewing the "
    "shared information"
)
def no_chart_type_narrowing_required(reviews: dict[str, dict[str, object]]) -> None:
    # ``_review_shared_fields`` -- the single function that produced every
    # entry in ``reviews`` -- is typed to accept only
    # ``FittedControlLimits`` and contains no branch keyed on concrete
    # type. That single code path IS the chart-type-agnostic mechanism.
    # What this assertion checks is its observable consequence: every
    # chart type produced the identical field *set*, which a
    # per-type-branching implementation could not guarantee without
    # duplicating a branch for each type.
    field_sets = {frozenset(fields.keys()) for fields in reviews.values()}
    assert len(field_sets) == 1


# --- Then: SC4 -- human-readable summary contains everything --------------------------


@then(
    "the text includes the chart type, detection boundaries, chart-specific "
    "parameters, baseline statistics, provenance, and both the requested and "
    "achieved false alarm tolerance"
)
def summary_includes_every_audit_field(summary: str, artefact: FittedArtefact) -> None:
    result = artefact.result
    assert isinstance(result, FittedEWMA)  # SC4's Given fits EWMA
    for prefix in SHARED_AUDIT_LABELS:
        assert prefix in summary
    assert CHART_SPECIFIC_HEADING in summary
    # Detection boundaries and the chart-specific tuning parameter -- both
    # live in FittedEWMA's own fields, beyond the shared core.
    assert str(result.ucl) in summary
    assert str(result.lcl) in summary
    assert str(result.cl) in summary
    assert str(result.smoothing_param) in summary


@then("the text is formatted for human reading")
def summary_is_formatted_for_human_reading(summary: str) -> None:
    # Multiple labelled lines, not a single-line repr -- every shared
    # label starts its own line, which ``_label_line_index`` would raise
    # on if it did not.
    assert summary.count("\n") >= len(SHARED_AUDIT_LABELS)
    for prefix in SHARED_AUDIT_LABELS:
        _label_line_index(summary, prefix)  # raises AssertionError if absent


# --- Then: SC5 -- consistent structure across chart types -----------------------------


@then(
    "the shared audit fields appear in the same position and with the same "
    "labelling in all three summaries"
)
def shared_fields_same_position_and_labelling(summaries: dict[str, str]) -> None:
    assert set(summaries.keys()) == {"ewma", "cusum", "shewhart"}
    per_chart_indices = {
        chart_type: [_label_line_index(text, label) for label in SHARED_AUDIT_LABELS]
        for chart_type, text in summaries.items()
    }
    reference = per_chart_indices["ewma"]
    for chart_type, indices in per_chart_indices.items():
        assert indices == reference, (
            f"{chart_type} summary orders shared labels differently: "
            f"{indices} != {reference}"
        )


@then("the chart-specific parameters appear in a clearly identified section")
def chart_specific_section_is_identified(summaries: dict[str, str]) -> None:
    for chart_type, text in summaries.items():
        heading_index = _label_line_index(text, CHART_SPECIFIC_HEADING)
        last_shared_index = max(
            _label_line_index(text, label) for label in SHARED_AUDIT_LABELS
        )
        assert heading_index > last_shared_index, (
            f"{chart_type} summary's chart-specific heading is not after the "
            "shared audit fields"
        )
