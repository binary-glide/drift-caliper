"""Unit tests for ``Provenance``'s repr ergonomics (BIN-110 P3).

Before BIN-110::

    >>> provenance
    Provenance(model_version=ModelVersion(value='claude-sonnet-4-5'),
               scoring_criteria=ScoringCriteria(value='Rate accuracy.'))

Three levels of wrapper to read two strings, in a log line an engineer did
not choose the format of. ``__str__``/``__repr__`` on ``Provenance`` itself
report the wrapped values directly rather than nesting the value objects'
own reprs.

⚠️ **Does not remove or restructure the value objects.** ``Provenance``
still holds a real ``ModelVersion``/``ScoringCriteria`` -- ADR-006 section 7
is load-bearing for provenance comparison (``Baseline.record()``'s exact
provenance-equality check, ``tests/unit/baseline/test_baseline.py``). Only
the *readout* changes; ``.model_version``/``.scoring_criteria`` still
return the value-object instances, unchanged -- this file pins that
directly so nothing "helpfully" flattens them to bare strings later.
"""

from __future__ import annotations

from caliper.measurement import ModelVersion, Provenance, ScoringCriteria


def _provenance() -> Provenance:
    return Provenance(
        model_version=ModelVersion(value="claude-sonnet-4-5-20250929"),
        scoring_criteria=ScoringCriteria(value="Rate accuracy and helpfulness."),
    )


def test_repr_reports_the_wrapped_values_not_nested_wrapper_reprs() -> None:
    """``repr(provenance)`` must not nest the value objects' own reprs."""
    # Arrange
    provenance = _provenance()

    # Act
    text = repr(provenance)

    # Assert -- the two strings an engineer actually wants are present ...
    assert "claude-sonnet-4-5-20250929" in text
    assert "Rate accuracy and helpfulness." in text
    # ... and neither nested wrapper repr survives to a third level.
    assert "ModelVersion(" not in text
    assert "ScoringCriteria(" not in text


def test_str_also_avoids_nested_wrapper_reprs() -> None:
    """``str(provenance)`` -- the form an f-string/log line actually uses."""
    # Arrange / Act
    text = str(_provenance())

    # Assert
    assert "ModelVersion(" not in text
    assert "ScoringCriteria(" not in text


def test_accessors_still_return_the_real_value_objects_unchanged() -> None:
    """The readout changes; the type does not (ADR-006 section 7)."""
    # Arrange
    provenance = _provenance()

    # Act / Assert -- structural equality still holds for provenance
    # comparison (Baseline.record()'s invariant), which requires these to
    # remain real ModelVersion/ScoringCriteria instances, not bare strings.
    assert isinstance(provenance.model_version, ModelVersion)
    assert isinstance(provenance.scoring_criteria, ScoringCriteria)
    assert provenance.model_version.value == "claude-sonnet-4-5-20250929"
    assert provenance.scoring_criteria.value == "Rate accuracy and helpfulness."
