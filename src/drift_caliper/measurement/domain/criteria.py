"""Scoring criteria -- a text rubric that anchors a judge's assessment.

See ``docs/domain-model.md`` (Value Object Inventory -- ``ScoringCriteria``)
and ADR-002 for the error contract enforced at creation.

.. warning::
    ``docs/domain-model.md`` specifies ``ScoringCriteria.create(raw: str) ->
    Result[ScoringCriteria, InvalidParameterError]``. That is wrong -- logged
    against BIN-100. It contradicts ADR-002 and the ratified "errors raise;
    the caller decides" decision (2026-09-08). ``ScoringCriteria`` raises
    ``InvalidParameterError`` directly; it does not return a ``Result``, and
    no errors-as-values library is a dependency of this project.

OQ-3 (whether criteria attach at judge creation, monitoring setup, per-call,
or some combination) is open. This module defines the ``ScoringCriteria``
value object only -- it deliberately does not wire itself to ``Judge`` or
any other configuration point, so as not to silently settle OQ-3.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from drift_caliper.errors import InvalidParameterError
from drift_caliper.measurement.domain.type_guards import require_str

SCORING_CRITERIA_CONSTRAINT = (
    "must be a non-empty string that is not entirely whitespace"
)


class ScoringCriteria(BaseModel):
    """A non-empty text rubric that anchors a judge's scoring assessment.

    Preserved exactly as provided, including any surrounding whitespace.
    Equality follows the wrapped ``value`` (Pydantic's default field-wise
    value equality).

    Validation lives here, in a ``field_validator``, following the same
    placement ``ModelVersion`` (BIN-57) established, so the invariant holds
    for every construction path -- there is no way to build a
    ``ScoringCriteria`` that wraps an empty or whitespace-only ``str``.

    A wrong-*typed* argument is rejected by ``reject_wrong_type`` below, a
    ``mode="before"`` validator that runs ahead of Pydantic's own core
    coercion (BIN-104) -- so it raises the same ``InvalidParameterError`` a
    blank value does, never a raw ``pydantic_core.ValidationError``.

    Unlike ``ModelVersion``, there is no "missing" case for this value
    object: every scenario in
    ``tests/bdd/features/measurement/scoring-criteria-text-rubric.feature``
    supplies a value (including the empty string and whitespace-only
    cases), so ``context["kind"]`` is always ``"invalid"`` here.

    Raises
    ------
    InvalidParameterError
        ``value`` is not a ``str``, or is empty or contains only
        whitespace. ``context["kind"]`` is always ``"invalid"``.
    """

    model_config = ConfigDict(frozen=True)

    value: str

    @field_validator("value", mode="before")
    @classmethod
    def reject_wrong_type(cls, v: object) -> object:
        """Reject a non-``str`` ``value`` before Pydantic's core coercion runs.

        See ``drift_caliper.measurement.domain.type_guards`` for why this is a
        ``mode="before"`` validator and why it raises ``InvalidParameterError``
        directly rather than ``ValueError`` (BIN-104).
        """
        return require_str(
            v, parameter="scoring_criteria", constraint=SCORING_CRITERIA_CONSTRAINT
        )

    @field_validator("value")
    @classmethod
    def must_not_be_blank(cls, v: str) -> str:
        """Reject empty or whitespace-only scoring criteria.

        Raises ``InvalidParameterError`` directly rather than ``ValueError``:
        Pydantic wraps ``ValueError``/``AssertionError`` in its own
        ``ValidationError``, while any other exception propagates unwrapped,
        which is what preserves ADR-002's contract for the caller.
        """
        if v.strip() == "":
            raise InvalidParameterError(
                "scoring_criteria must be a non-empty, non-whitespace string",
                context={
                    "parameter": "scoring_criteria",
                    "constraint": SCORING_CRITERIA_CONSTRAINT,
                    "kind": "invalid",
                    "provided": v,
                },
                recovery_hint=(
                    "Pass a text rubric describing what the judge should "
                    "evaluate, for example: 'Evaluate the response for "
                    "factual accuracy and helpfulness.' Criteria anchor the "
                    "judge's assessment, so blank text leaves it scoring "
                    "against an opaque default."
                ),
            )
        return v

    def __str__(self) -> str:
        """Return the wrapped rubric text directly (BIN-110 P3).

        Mirrors ``ModelVersion.__str__`` -- the readback fix applies
        uniformly to both value-object wrappers ``Provenance`` holds.
        ``repr()`` is untouched.
        """
        return self.value
