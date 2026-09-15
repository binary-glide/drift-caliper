"""Unit tests for ``audit_summary()`` (BIN-66) -- the human-readable audit record.

Pins the last two scenarios in
``tests/bdd/features/baseline/review-fitted-control-limits.feature`` --
"Engineer obtains a human-readable summary suitable for an audit log" and
"The human-readable summary is consistent in structure across chart
types" -- at the unit layer, with the exact, mutation-resistant assertions
``tests/bdd/steps/review_fitted_control_limits_steps.py`` deliberately keeps
thin. See that module's docstring for the full reasoning behind the design
decision this file also pins:

**``audit_summary() -> str`` is a dedicated method on each concrete
``Fitted*`` type -- not ``__repr__`` or ``__str__``.** BIN-110 already gave
every public type a useful, compact ``__repr__``/``__str__`` for the
debugger/REPL/log-line case; an audit summary is a longer-lived, fully
labelled, multi-line artefact an engineer deliberately writes to a log for
a human or an auditor -- a different job with a different shape. This file
asserts ``audit_summary()`` is genuinely distinct from both dunder methods,
not an alias.

The first three review scenarios (chart-agnostic field access) require no
new production code -- ``FittedControlLimits`` (ADR-004) already carries
every field they need. Only ``audit_summary()`` is new behaviour, so it is
the only thing pinned here.

No numeric literal below is a claim about statistical correctness -- every
concrete ``target_arl`` is an arbitrary valid input chosen only to exercise
the audit summary's formatting, exactly as every sibling fitting test file's
own convention.

``FittedEWMA``/``FittedCUSUM``/``FittedShewhart`` instances are obtained
here only by calling ``fit_ewma``/``fit_cusum``/``fit_shewhart`` -- never
constructed directly -- mirroring the convention
``tests/unit/baseline/test_shewhart_fitting.py`` and its siblings
established.
"""

from __future__ import annotations

from collections.abc import Callable

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
from tests.factories import ProvenanceFactory, ScoringResultFactory

# Arbitrary, sufficiently-large target ARL0 used across every fixture below.
# Its value carries no statistical meaning here -- this file asserts the
# summary's shape and structure only, never a specific achieved-ARL figure.
_TARGET_ARL = 370.0

# The shared-core label prefixes ``audit_summary()`` must emit, in this
# exact order, identically across all three chart types -- matches
# ``tests/bdd/steps/review_fitted_control_limits_steps.py``'s
# ``SHARED_AUDIT_LABELS``, pinned independently here rather than imported,
# since a unit test and its BDD counterpart should each fail on their own
# if the contract regresses (mirrors the project's general two-layer
# convention of not cross-importing test constants between layers).
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
# `drift_caliper.baseline.domain.audit_summary`. Importing the constant would make
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


def _sufficient_baseline() -> Baseline:
    """A baseline that passes every chart type's sufficiency check, with variance."""
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for _ in range(DEFAULT_SUFFICIENCY_THRESHOLD + 5):
        baseline.record(ScoringResultFactory(provenance=shared_provenance))
    return baseline


def _fitted_ewma() -> FittedEWMA:
    return fit_ewma(_sufficient_baseline(), target_arl=_TARGET_ARL)


def _fitted_cusum() -> FittedCUSUM:
    return fit_cusum(_sufficient_baseline(), target_arl=_TARGET_ARL)


def _fitted_shewhart() -> FittedShewhart:
    return fit_shewhart(_sufficient_baseline(), target_arl=_TARGET_ARL)


FittedArtefact = FittedEWMA | FittedCUSUM | FittedShewhart

_ALL_CHART_TYPES = pytest.mark.parametrize(
    "fit_one",
    [_fitted_ewma, _fitted_cusum, _fitted_shewhart],
    ids=["ewma", "cusum", "shewhart"],
)


def _label_line_index(text: str, prefix: str) -> int:
    for index, line in enumerate(text.splitlines()):
        if line.strip().startswith(prefix):
            return index
    raise AssertionError(f"no line starting with {prefix!r} in:\n{text}")


# --- audit_summary() exists, returns str, and is distinct from repr/str -------------


@_ALL_CHART_TYPES
def test_audit_summary_returns_a_non_empty_string(
    fit_one: Callable[[], FittedArtefact],
) -> None:
    result = fit_one()
    summary = result.audit_summary()
    assert isinstance(summary, str)
    assert summary != ""


@_ALL_CHART_TYPES
def test_audit_summary_is_distinct_from_repr_and_str(
    fit_one: Callable[[], FittedArtefact],
) -> None:
    result = fit_one()
    summary = result.audit_summary()
    # An audit summary is a different, longer-lived artefact from the
    # compact debugger repr -- see module docstring. If a future change
    # aliases audit_summary() to __repr__/__str__, this test catches the
    # regression back to the compact form BIN-110 established for the
    # debugger/log-line case.
    assert summary != repr(result)
    assert summary != str(result)


@_ALL_CHART_TYPES
def test_audit_summary_is_deterministic(fit_one: Callable[[], FittedArtefact]) -> None:
    result = fit_one()
    assert result.audit_summary() == result.audit_summary()


# --- shared-core labels: presence, exact text, fixed order --------------------------


@_ALL_CHART_TYPES
def test_audit_summary_contains_every_shared_label(
    fit_one: Callable[[], FittedArtefact],
) -> None:
    summary = fit_one().audit_summary()
    for label in SHARED_AUDIT_LABELS:
        assert label in summary


@_ALL_CHART_TYPES
def test_audit_summary_shared_labels_appear_in_fixed_order(
    fit_one: Callable[[], FittedArtefact],
) -> None:
    summary = fit_one().audit_summary()
    indices = [_label_line_index(summary, label) for label in SHARED_AUDIT_LABELS]
    assert indices == sorted(indices)


def test_audit_summary_shared_label_positions_identical_across_chart_types() -> None:
    """SC5: 'the same position ... in all three summaries.'

    Not just internally ordered (the test above) -- the *same* label sits
    at the *same* line index regardless of chart type, which is the
    property a per-chart-type-formatted implementation could violate even
    while each individual summary looks internally consistent.
    """
    summaries = {
        "ewma": _fitted_ewma().audit_summary(),
        "cusum": _fitted_cusum().audit_summary(),
        "shewhart": _fitted_shewhart().audit_summary(),
    }
    per_chart_indices = {
        chart_type: [_label_line_index(text, label) for label in SHARED_AUDIT_LABELS]
        for chart_type, text in summaries.items()
    }
    reference = per_chart_indices["ewma"]
    for chart_type, indices in per_chart_indices.items():
        assert indices == reference, (
            f"{chart_type} disagrees with ewma on shared label line positions: "
            f"{indices} != {reference}"
        )


# --- shared-core values: the labelled text reflects the actual field values ---------


def test_audit_summary_reports_the_actual_shared_field_values() -> None:
    result = _fitted_ewma()
    summary = result.audit_summary()
    assert str(result.chart_type) in summary
    assert str(result.baseline_mean) in summary
    assert str(result.baseline_spread) in summary
    assert str(result.sigma_estimate) in summary
    assert str(result.sigma_estimation_method) in summary
    assert str(result.observation_count) in summary
    assert str(result.provenance_model_version) in summary
    assert str(result.provenance_criteria) in summary
    assert str(result.requested_arl) in summary
    assert str(result.achieved_arl) in summary
    assert str(result.calibration_method) in summary


# --- chart-specific section: heading present, positioned after shared core ----------


@_ALL_CHART_TYPES
def test_audit_summary_contains_chart_specific_heading(
    fit_one: Callable[[], FittedArtefact],
) -> None:
    summary = fit_one().audit_summary()
    assert CHART_SPECIFIC_HEADING in summary


@_ALL_CHART_TYPES
def test_chart_specific_heading_appears_after_every_shared_label(
    fit_one: Callable[[], FittedArtefact],
) -> None:
    summary = fit_one().audit_summary()
    heading_index = _label_line_index(summary, CHART_SPECIFIC_HEADING)
    last_shared_index = max(
        _label_line_index(summary, label) for label in SHARED_AUDIT_LABELS
    )
    assert heading_index > last_shared_index


# --- chart-specific values: each type's own fields (incl. detection boundaries) -----


def test_ewma_summary_reports_smoothing_parameter_and_control_limits() -> None:
    result = _fitted_ewma()
    summary = result.audit_summary()
    assert str(result.smoothing_param) in summary
    assert str(result.ucl) in summary
    assert str(result.lcl) in summary
    assert str(result.cl) in summary


def test_cusum_summary_reports_reference_value_and_decision_interval() -> None:
    result = _fitted_cusum()
    summary = result.audit_summary()
    assert str(result.reference_value) in summary
    assert str(result.decision_interval) in summary
    assert str(result.target_value) in summary
    assert str(result.direction) in summary


def test_shewhart_summary_reports_sigma_multiplier_and_control_limits() -> None:
    result = _fitted_shewhart()
    summary = result.audit_summary()
    assert str(result.sigma_multiplier) in summary
    assert str(result.ucl) in summary
    assert str(result.lcl) in summary
    assert str(result.cl) in summary


# --- formatted for human reading (SC4) -----------------------------------------------


@_ALL_CHART_TYPES
def test_audit_summary_is_multi_line(fit_one: Callable[[], FittedArtefact]) -> None:
    summary = fit_one().audit_summary()
    # One label per line at minimum -- a single-line dump would fail this,
    # distinguishing "formatted for human reading" from a compact repr.
    assert summary.count("\n") >= len(SHARED_AUDIT_LABELS)
