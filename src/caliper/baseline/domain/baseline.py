"""``Baseline`` -- an ordered, provenance-consistent collection of observations.

See ``docs/domain-model.md`` (Object Map -- Baseline, the one mutable
collection) and ``docs/architecture/adr/002-error-contract-exception-taxonomy.md``
for the error contract enforced by ``record()``.

``check_sufficiency()`` (BIN-64) is a read-only, advisory inspection of
whether the baseline has enough observations for reliable fitting -- see
ADR-005 for the default threshold and its rationale.
"""

from __future__ import annotations

from collections.abc import Sequence

from caliper.baseline.domain.data_quality_concern import DataQualityConcern
from caliper.baseline.domain.sufficiency_result import SufficiencyResult
from caliper.errors import (
    InvalidObservationError,
    InvalidParameterError,
    ProvenanceMismatchError,
)
from caliper.measurement import Provenance, ScoringResult

# Fields a candidate observation must expose to be treated as a complete
# ScoringResult. Used only to report *which* fields are missing when an
# isinstance check has already failed -- not to duck-type acceptance itself.
_REQUIRED_OBSERVATION_FIELDS = ("score", "reasoning", "provenance")

# The library's default minimum Phase I baseline size for
# ``check_sufficiency()`` -- 100 individual observations, applied uniformly
# across chart types (ADR-005 "Default minimum: 100 observations (uniform
# across chart types)"). A pragmatic interim default derived from the Phase
# I estimation literature (Quesenberry 1993; Jones, Champ & Rigdon 2001),
# not a theoretically optimal threshold -- see ADR-005 for the full
# rationale and its two documented caveats (the normality assumption and
# estimation error). Configurable per call via ``check_sufficiency(threshold=...)``
# (BIN-64 BR-3); this is only the value used when no override is given.
DEFAULT_SUFFICIENCY_THRESHOLD = 100

# The only DataQualityConcern.kind this story introduces (OQ-1 closes the
# door on additional concern types for BIN-64) -- see docs/domain-model.md
# Value Object Inventory's worked example for DataQualityConcern.kind.
_ZERO_VARIANCE_CONCERN_KIND = "zero_variance"

# Sample variance is undefined for a single point, so a singleton baseline
# is never flagged as zero-variance -- there is nothing yet to compare it
# against. An empty baseline (0 observations) is likewise never flagged.
_MIN_OBSERVATIONS_FOR_VARIANCE_CHECK = 2


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


def _zero_variance_concerns(
    observations: Sequence[ScoringResult],
) -> tuple[DataQualityConcern, ...]:
    """Report a zero-variance concern if every observation shares one score.

    A baseline whose scores are all identical produces a zero variance
    estimate; fitted control limits would collapse to the mean and be
    unable to detect any deviation (BIN-64 SC7/SC12). Returns an empty
    empty tuple when there are too few observations to assess variance, or
    when the scores are not all identical. A tuple, not a list: sequence
    fields on immutable domain types are tuples (BIN-108), so that
    ``SufficiencyResult``'s documented immutability actually holds.
    """
    if len(observations) < _MIN_OBSERVATIONS_FOR_VARIANCE_CHECK:
        return ()
    distinct_scores = {observation.score for observation in observations}
    if len(distinct_scores) > 1:
        return ()
    return (
        DataQualityConcern(
            kind=_ZERO_VARIANCE_CONCERN_KIND,
            description=(
                "every recorded observation has an identical score -- the "
                "baseline has zero variance, so fitted control limits "
                "would collapse to the mean and be unable to detect any "
                "deviation"
            ),
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

    def check_sufficiency(
        self,
        *,
        threshold: int | None = None,
        chart_type: str | None = None,
    ) -> SufficiencyResult:
        """Check whether this baseline has enough observations for fitting.

        A read-only, advisory inspection (BR-6) -- it never modifies the
        baseline. Reports the observation count, the threshold applied
        (``threshold`` if given, else ``DEFAULT_SUFFICIENCY_THRESHOLD``),
        the gap (``max(0, threshold - observation_count)``), and any data
        quality concerns (BIN-64 SC7/SC12: an all-identical baseline is
        flagged with a ``DataQualityConcern(kind="zero_variance", ...)``
        regardless of whether the count threshold is met). A non-positive
        ``threshold`` raises ``InvalidParameterError`` before anything
        else. ``chart_type`` is accepted so the mechanism supports
        per-chart-type thresholds (BR-5) without requiring them -- it is
        purely informational here; an explicit ``threshold`` is what
        governs the determination, per ADR-005 (all chart types currently
        share the one default until BIN-92's simulation study).

        Args:
            threshold: Minimum observation count required to be
                sufficient. ``None`` uses ``DEFAULT_SUFFICIENCY_THRESHOLD``.
                Must be positive.
            chart_type: Optional label for which chart type's threshold
                this check is for. Purely informational in this story --
                see the docstring above.

        Returns:
            A ``SufficiencyResult`` describing the baseline's readiness.

        Raises:
            InvalidParameterError: ``threshold`` is zero or negative.
        """
        del chart_type  # informational only in this story -- see docstring

        effective_threshold = (
            threshold if threshold is not None else DEFAULT_SUFFICIENCY_THRESHOLD
        )
        if effective_threshold <= 0:
            raise InvalidParameterError(
                "sufficiency threshold must be a positive integer",
                context={
                    "parameter": "threshold",
                    "constraint": "must be a positive integer",
                    "kind": "invalid",
                    "provided": threshold,
                },
                recovery_hint=(
                    "Pass a positive threshold, or omit it to use the "
                    "library default (DEFAULT_SUFFICIENCY_THRESHOLD)."
                ),
            )

        observation_count = self.observation_count
        return SufficiencyResult(
            is_sufficient=observation_count >= effective_threshold,
            observation_count=observation_count,
            threshold=effective_threshold,
            gap=max(0, effective_threshold - observation_count),
            data_quality_concerns=_zero_variance_concerns(self._observations),
        )
