"""Unit tests for the shared guarded attribute probe (BIN-127).

``caliper.baseline.domain.attribute_probe`` is the one implementation
``Baseline.record()``, ``Monitor.record()``, and ``compare_provenance()``
now share, replacing what used to be a duplicated ``_missing_observation_fields``
in ``baseline.py``/``monitor.py`` and no guard at all in
``compare_provenance()``. Tested directly here -- independent of any call
site -- for the same reason ``test_spc_numerics.py`` tests
``_moving_range_sigma`` directly: a helper reused by more than one caller is
exactly the shape where only a test against the helper itself, not merely
against callers' output, catches a regression in the shared implementation.
"""

from __future__ import annotations

import pytest

from caliper.baseline.domain.attribute_probe import (
    REQUIRED_OBSERVATION_FIELDS,
    AttributeProbe,
    invalid_observation_error,
    probe_attribute,
    probe_fields,
)
from caliper.errors import InvalidObservationError


class _RaisingAttribute:
    """An object whose ``.hazard`` attribute raises rather than being absent."""

    @property
    def hazard(self) -> float:
        raise RuntimeError("boom")


class _OutOfMemoryAttribute:
    """An object whose attribute access raises ``MemoryError``.

    ``MemoryError`` is a resource-exhaustion condition, not a duck-typing
    contract violation -- ``tests/unit/test_exception_contract_audit.py``'s
    ``_NOT_CONTRACT_VIOLATIONS`` already excludes it from the "must be a
    ``CaliperError``" rule for exactly this reason. This probe must not
    paper over it as an ordinary "attribute raised" outcome.
    """

    @property
    def hazard(self) -> float:
        raise MemoryError("simulated out-of-memory")


class _PlainObject:
    """An object exposing exactly one attribute, ``present``."""

    present = "value"


class _MixedObservation:
    """One field absent, a different field raises -- both on the same object.

    Used to pin that ``invalid_observation_error()`` classifies each field
    independently rather than short-circuiting on the first problem found:
    ``score`` raises, ``reasoning`` is absent, ``provenance`` is present.
    Mirrors the mixed fixtures ``test_baseline.py``/``test_monitor.py`` use
    at the entry-point level.
    """

    provenance = "not really a Provenance, but present is all that matters here"

    @property
    def score(self) -> float:
        raise RuntimeError("boom-on-score-access")


# --- probe_attribute ----------------------------------------------------------


def test_probe_attribute_reports_present_value() -> None:
    outcome = probe_attribute(_PlainObject(), "present")

    assert outcome == AttributeProbe(value="value", is_absent=False, raised_type=None)


def test_probe_attribute_reports_absent_for_a_missing_attribute() -> None:
    outcome = probe_attribute(_PlainObject(), "missing")

    assert outcome.is_absent is True
    assert outcome.raised_type is None
    assert outcome.value is None


def test_probe_attribute_reports_absent_for_none_candidate() -> None:
    """``None`` has no attributes at all -- every probe reports absent, never raises."""
    outcome = probe_attribute(None, "anything")

    assert outcome.is_absent is True
    assert outcome.raised_type is None


def test_probe_attribute_reports_raised_type_without_raising() -> None:
    """The defining case: access raises something other than ``AttributeError``.

    ``probe_attribute`` itself never raises -- it reports the outcome.
    """
    outcome = probe_attribute(_RaisingAttribute(), "hazard")

    assert outcome.is_absent is False
    assert outcome.raised_type == "RuntimeError"
    assert outcome.value is None


def test_probe_attribute_reraises_memory_error_unwrapped() -> None:
    """``MemoryError`` is resource exhaustion, not a duck-typing question.

    It must propagate unwrapped -- never reported as
    ``AttributeProbe(raised_type="MemoryError")``, which would make an
    out-of-memory condition indistinguishable from an ordinary hostile
    attribute and let it be silently absorbed into
    ``unreadable_fields`` by a caller upstream.
    """
    with pytest.raises(MemoryError):
        probe_attribute(_OutOfMemoryAttribute(), "hazard")


def test_probe_fields_reraises_memory_error_unwrapped() -> None:
    """The bulk probe propagates the same way -- it must not catch it either."""
    with pytest.raises(MemoryError):
        probe_fields(_OutOfMemoryAttribute(), ("hazard", "missing"))


# --- probe_fields ---------------------------------------------------------------


def test_probe_fields_partitions_absent_from_unreadable() -> None:
    """Absent and unreadable fields are reported separately, never conflated."""
    candidate = _RaisingAttribute()

    probe = probe_fields(candidate, ("hazard", "missing"))

    assert probe.absent == ("missing",)
    assert probe.unreadable == {"hazard": "RuntimeError"}


def test_probe_fields_reports_nothing_for_present_and_readable_fields() -> None:
    probe = probe_fields(_PlainObject(), ("present",))

    assert probe.absent == ()
    assert probe.unreadable == {}


def test_probe_fields_matches_hasattr_for_ordinary_absence() -> None:
    """A field that is merely absent (the case ``hasattr`` already handles

    correctly) is still reported as absent through this shared probe --
    the fix does not change behaviour for the well-behaved case, only for
    the hostile one.
    """
    probe = probe_fields(None, ("score", "reasoning", "provenance"))

    assert set(probe.absent) == {"score", "reasoning", "provenance"}
    assert probe.unreadable == {}


# --- invalid_observation_error ---------------------------------------------------


def test_invalid_observation_error_reports_all_fields_absent_for_none() -> None:
    error = invalid_observation_error(None)

    assert isinstance(error, InvalidObservationError)
    assert error.category == "invalid_observation"
    assert set(error.context["missing_fields"]) == set(REQUIRED_OBSERVATION_FIELDS)
    assert error.context["unreadable_fields"] == {}


def test_invalid_observation_error_distinguishes_mixed_absent_and_raised() -> None:
    """One field absent, a different field raises, on the same object.

    Both ``Baseline``/``Monitor`` share this one builder, so this pins the
    mixed case once here rather than only through each entry point's own
    single-field fixtures.
    """
    error = invalid_observation_error(_MixedObservation())

    assert error.context["missing_fields"] == ["reasoning"]
    assert error.context["unreadable_fields"] == {"score": "RuntimeError"}
