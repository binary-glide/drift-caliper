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

from caliper.errors import InvalidParameterError

SCORING_CRITERIA_CONSTRAINT = (
    "must be a non-empty string that is not entirely whitespace"
)


class ScoringCriteria(BaseModel):
    """A non-empty text rubric that anchors a judge's scoring assessment.

    Preserved exactly as provided, including any surrounding whitespace.
    Equality follows the wrapped ``value`` (dataclass value equality).

    Validation lives here, in ``__post_init__``, following the same
    placement ``ModelVersion`` (BIN-57) established, so the invariant holds
    for every construction path -- there is no way to build a
    ``ScoringCriteria`` that wraps an empty or whitespace-only string.

    Unlike ``ModelVersion``, there is no "missing" case for this value
    object: every scenario in
    ``tests/bdd/features/measurement/scoring-criteria-text-rubric.feature``
    supplies a value (including the empty string and whitespace-only
    cases), so ``context["kind"]`` is always ``"invalid"`` here.

    Raises:
        InvalidParameterError: ``value`` is empty or contains only
            whitespace. ``context["kind"]`` is always ``"invalid"``.
    """

    model_config = ConfigDict(frozen=True)

    value: str

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
