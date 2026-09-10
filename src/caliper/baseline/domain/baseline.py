"""``Baseline`` -- an ordered, provenance-consistent collection of observations.

See ``docs/domain-model.md`` (Object Map -- Baseline, the one mutable
collection) and ``docs/architecture/adr/002-error-contract-exception-taxonomy.md``
for the error contract enforced by ``record()``.
"""

from __future__ import annotations

from collections.abc import Sequence

from caliper.errors import InvalidObservationError, ProvenanceMismatchError
from caliper.measurement import Provenance, ScoringResult

# Fields a candidate observation must expose to be treated as a complete
# ScoringResult. Used only to report *which* fields are missing when an
# isinstance check has already failed -- not to duck-type acceptance itself.
_REQUIRED_OBSERVATION_FIELDS = ("score", "reasoning", "provenance")


def _missing_observation_fields(candidate: object) -> list[str]:
    """Report which ``ScoringResult`` fields ``candidate`` does not expose.

    Used only after ``isinstance(candidate, ScoringResult)`` has already
    failed, to build ``InvalidObservationError.context["missing_fields"]``.
    ``candidate`` may be ``None`` or any other object -- ``hasattr`` is safe
    against both.
    """
    return [
        field for field in _REQUIRED_OBSERVATION_FIELDS if not hasattr(candidate, field)
    ]


def _reject_if_provenance_differs(observed: Provenance, signature: Provenance) -> None:
    """Raise ``ProvenanceMismatchError`` if ``observed`` differs from ``signature``.

    Checks the model version dimension before the scoring criteria
    dimension. Equality is Pydantic's exact, field-wise equality on
    ``ModelVersion``/``ScoringCriteria`` -- no stripping, no case folding
    (settled 2026-09-10, see ``docs/domain-model.md`` "Criteria equality is
    exact").
    """
    if observed.model_version != signature.model_version:
        raise ProvenanceMismatchError(
            "observation's judge model version differs from the baseline's "
            "established provenance",
            context={
                "dimension": "model_version",
                "expected": signature.model_version.value,
                "received": observed.model_version.value,
            },
            recovery_hint=(
                "Record observations scored by a single, consistently "
                "pinned judge model version. If the model version has "
                "genuinely changed, start a new baseline rather than "
                "mixing measurements from two instruments."
            ),
        )
    if observed.scoring_criteria != signature.scoring_criteria:
        raise ProvenanceMismatchError(
            "observation's scoring criteria differs from the baseline's "
            "established provenance",
            context={
                "dimension": "scoring_criteria",
                "expected": signature.scoring_criteria.value,
                "received": observed.scoring_criteria.value,
            },
            recovery_hint=(
                "Record observations scored against a single, consistent "
                "set of criteria. If the rubric has genuinely changed, "
                "start a new baseline rather than mixing measurements "
                "taken against two different criteria."
            ),
        )


class Baseline:
    """An ordered, provenance-consistent collection of scored observations.

    The one mutable object in Caliper's domain model. A new ``Baseline`` is
    empty and accepts observations via ``record()``, which enforces the
    four invariants described in ``docs/domain-model.md`` (Object Map --
    Baseline): provenance homogeneity, insertion order, observation
    immutability, and rejection of incomplete input.
    """

    def __init__(self) -> None:
        self._observations: list[ScoringResult] = []
        self._provenance_signature: Provenance | None = None

    @property
    def observations(self) -> Sequence[ScoringResult]:
        """The recorded observations, in the order they were recorded."""
        return tuple(self._observations)

    @property
    def observation_count(self) -> int:
        """The number of observations currently in the baseline."""
        return len(self._observations)

    @property
    def provenance_signature(self) -> Provenance | None:
        """The provenance every observation must match, or ``None`` if empty."""
        return self._provenance_signature

    def record(self, result: ScoringResult) -> None:
        """Record a scoring result as a new observation.

        Enforces, in order: that ``result`` is a complete ``ScoringResult``
        (score, reasoning, provenance); and, once the baseline already has
        a provenance signature, that ``result.provenance`` matches it
        exactly. The first observation ever recorded establishes the
        signature rather than being checked against it. On any rejection
        the baseline is left completely unchanged -- the observation is
        appended only after every check passes.

        Args:
            result: The scoring result to record. Only a complete
                ``ScoringResult`` is accepted; anything else is rejected
                with ``InvalidObservationError`` before the baseline is
                modified.

        Raises:
            InvalidObservationError: ``result`` is not a complete
                ``ScoringResult``.
            ProvenanceMismatchError: ``result.provenance`` differs from the
                baseline's established provenance signature.
        """
        if not isinstance(result, ScoringResult):
            raise InvalidObservationError(
                "recorded observation is not a complete scoring result",
                context={
                    "reason": (
                        "input is missing one or more required ScoringResult "
                        "fields (score, reasoning, provenance)"
                    ),
                    "missing_fields": _missing_observation_fields(result),
                },
                recovery_hint=(
                    "Pass a complete ScoringResult (score, reasoning, "
                    "provenance) -- typically the return value of "
                    "Judge.score()."
                ),
            )

        if self._provenance_signature is None:
            self._provenance_signature = result.provenance
        else:
            _reject_if_provenance_differs(result.provenance, self._provenance_signature)

        self._observations.append(result)
