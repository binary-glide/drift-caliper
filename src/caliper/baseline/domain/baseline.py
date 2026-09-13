"""``Baseline`` -- an ordered, provenance-consistent collection of observations.

See ``docs/domain-model.md`` (Object Map -- Baseline, the one mutable
collection) and ``docs/architecture/adr/002-error-contract-exception-taxonomy.md``
for the error contract enforced by ``record()``.

``check_sufficiency()`` (BIN-64) is a read-only, advisory inspection of
whether the baseline has enough observations for reliable fitting -- see
ADR-005 for the default threshold and its rationale.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence

from caliper.baseline.domain.attribute_probe import invalid_observation_error
from caliper.baseline.domain.data_quality_concern import DataQualityConcern
from caliper.baseline.domain.parameter_guards import require_real_number
from caliper.baseline.domain.provenance_comparison import build_mismatches
from caliper.baseline.domain.sufficiency_result import SufficiencyResult
from caliper.errors import InvalidParameterError, ProvenanceMismatchError
from caliper.measurement import Provenance, ScoringResult

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


def _reject_if_provenance_differs(observed: Provenance, signature: Provenance) -> None:
    """Raise ``ProvenanceMismatchError`` if ``observed`` differs from ``signature``.

    Checks both the model version and scoring criteria dimensions before
    raising -- not a short-circuit on the first difference found, so a
    dual mismatch is reported in one raise covering both dimensions
    (ADR-002 Amendment, 2026-09-10, "provenance_mismatch context becomes a
    mismatches mapping"). Equality is Pydantic's exact, field-wise
    equality on ``ModelVersion``/``ScoringCriteria`` -- no stripping, no
    case folding (settled 2026-09-10, see ``docs/domain-model.md``
    "Criteria equality is exact").
    """
    mismatches = build_mismatches(
        expected_model_version=signature.model_version.value,
        received_model_version=observed.model_version.value,
        expected_criteria=signature.scoring_criteria.value,
        received_criteria=observed.scoring_criteria.value,
    )
    if not mismatches:
        return

    raise ProvenanceMismatchError(
        "observation's provenance differs from the baseline's established provenance",
        context={"mismatches": mismatches},
        recovery_hint=(
            "Record observations scored by a single, consistently pinned "
            "judge model version and a single, consistent set of scoring "
            "criteria. If either has genuinely changed, start a new "
            "baseline rather than mixing measurements from two "
            "instruments."
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

    def __len__(self) -> int:
        """Report the number of recorded observations (BIN-110 P1).

        Agrees with ``observation_count``, which is kept alongside this --
        it reads better in ``SufficiencyResult``'s context and in log
        lines. This is the collection-protocol form.
        """
        return self.observation_count

    def __iter__(self) -> Iterator[ScoringResult]:
        """Iterate recorded observations in recording order (BIN-110 P1).

        Iterates a snapshot tuple, not the internal mutable list -- a
        caller holding this iterator cannot reach in and mutate
        ``Baseline``'s private state through it.
        """
        return iter(self.observations)

    def __repr__(self) -> str:
        """Produce a useful REPL/log/debugger representation (BIN-110 P1).

        Before this, ``Baseline`` had no ``__repr__`` and fell back to
        ``object.__repr__`` (``<...Baseline object at 0x...>``) -- useless
        anywhere an engineer actually looks at one. Reports the class name
        and observation count; deliberately not every field (provenance may
        be ``None`` and is verbose to render usefully here).
        """
        return f"Baseline(observation_count={self.observation_count})"

    def record(self, result: ScoringResult) -> None:
        """Record a scoring result as a new observation.

        Enforces, in order: that ``result`` is a complete ``ScoringResult``
        (score, reasoning, provenance); and, once the baseline already has
        a provenance signature, that ``result.provenance`` matches it
        exactly. The first observation ever recorded establishes the
        signature rather than being checked against it. On any rejection
        the baseline is left completely unchanged -- the observation is
        appended only after every check passes.

        Parameters
        ----------
        result
            The scoring result to record. Only a complete ``ScoringResult``
            is accepted; anything else is rejected with
            ``InvalidObservationError`` before the baseline is modified.

        Raises
        ------
        InvalidObservationError
            ``result`` is not a complete ``ScoringResult``.
        ProvenanceMismatchError
            ``result.provenance`` differs from the baseline's established
            provenance signature.
        """
        if not isinstance(result, ScoringResult):
            raise invalid_observation_error(result)

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

        Parameters
        ----------
        threshold
            Minimum observation count required to be sufficient. ``None``
            uses ``DEFAULT_SUFFICIENCY_THRESHOLD``. Must be positive.
        chart_type
            Optional label for which chart type's threshold this check is
            for. Purely informational in this story -- see the docstring
            above.

        Returns
        -------
        SufficiencyResult
            Describes the baseline's readiness.

        Raises
        ------
        InvalidParameterError
            ``threshold`` is zero, negative, not a real number (BIN-126),
            or a real number with a non-zero fractional part -- ``threshold``
            is a count of observations, and ``50.7`` is not one; accepting
            it and silently truncating to ``50`` would report back a
            threshold the caller never passed (BIN-126 review).

        Notes
        -----
        ``DEFAULT_SUFFICIENCY_THRESHOLD``'s rationale draws on Quesenberry
        (1993) and Jones, Champ & Rigdon (2001) -- see ADR-005 for the full
        citations and reasoning. Neither is reproduced as a ``References``
        entry here: Quesenberry (1993) was verified only through secondary
        citations, and Jones, Champ & Rigdon (2001) only its abstract was
        read -- neither was read directly enough to cite as a primary
        source in published API documentation.
        """
        del chart_type  # informational only in this story -- see docstring

        constraint = "must be a positive integer"
        if threshold is None:
            effective_threshold: int = DEFAULT_SUFFICIENCY_THRESHOLD
        else:
            # BIN-126: reject a bool or a non-numeric value (e.g. a string)
            # before the arithmetic comparison below is attempted against
            # it -- see parameter_guards.require_real_number's docstring
            # for why this is a behavioural, not nominal, check.
            numeric_threshold = require_real_number(
                threshold, parameter="threshold", constraint=constraint
            )
            # BIN-126 review: `threshold` is a count of observations, so a
            # value with a non-zero fractional part (e.g. 50.7) is rejected
            # rather than silently truncated. Truncating would both report
            # back a threshold the caller never passed (CLAUDE.md's "what
            # goes in should come out") and quietly change what "sufficient"
            # means at the boundary (50.7 -> accepting at 50 observations
            # instead of 51) -- a confident wrong answer, not a rounding
            # nicety. The comparison against `int(numeric_threshold)` (not
            # `float.is_integer()` -- `ty` treats a `float`-typed value as
            # implicitly including `int` per the PEP 484 numeric tower and
            # does not resolve `.is_integer()` against that `int` member)
            # accepts 50.0/np.float64(50.0)/np.int64(50) (all
            # integral-valued) and rejects 50.7, without narrowing to
            # `isinstance(x, int)` -- which would break the numpy interop
            # `require_real_number` exists to preserve. The `isfinite`
            # check short-circuits first so a non-finite `threshold` (e.g.
            # NaN) is rejected here rather than raising `ValueError` from
            # `int(nan)`.
            if not math.isfinite(numeric_threshold) or numeric_threshold != int(
                numeric_threshold
            ):
                raise InvalidParameterError(
                    "sufficiency threshold must be a whole number",
                    context={
                        "parameter": "threshold",
                        "constraint": constraint,
                        "kind": "invalid",
                        "provided": threshold,
                        "min_value": 1,
                        "min_inclusive": True,
                    },
                    recovery_hint=(
                        "threshold is a count of observations -- pass a "
                        "whole-number value (e.g. 50, 50.0, or "
                        "np.int64(50)), not a fractional one."
                    ),
                )
            effective_threshold = int(numeric_threshold)
        if effective_threshold <= 0:
            raise InvalidParameterError(
                "sufficiency threshold must be a positive integer",
                context={
                    "parameter": "threshold",
                    "constraint": constraint,
                    "kind": "invalid",
                    "provided": threshold,
                    "min_value": 1,
                    "min_inclusive": True,
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
