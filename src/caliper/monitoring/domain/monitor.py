"""``Monitor`` -- records Phase II observations against a fitted artefact.

See ``docs/domain-model.md`` (Object Map -- Monitor, the domain's second
mutable object) and
``docs/architecture/adr/009-phase-ii-monitor-and-observation-store.md`` for
the full design reasoning. Mirrors ``caliper.baseline.domain.baseline``'s
``Baseline`` -- the only other mutable object in the domain -- for house
shape: private backing state, a narrow public surface, and the same
"validate first, mutate only after every check passes" recording discipline.

``Monitor`` holds a reference to exactly one immutable fitted artefact
(never mutating or reading back from it -- ADR-004/BIN-108) plus private,
chart-specific accumulator state: nothing meaningful for Shewhart
(memoryless by design), the smoothed statistic for EWMA, and the two
one-sided running sums for CUSUM. Two ``Monitor``s constructed from the same
artefact hold entirely independent accumulators (ADR-009 section 1).
"""

from __future__ import annotations

from caliper.baseline.domain.compare_provenance import compare_provenance
from caliper.baseline.domain.fitted_control_limits import FittedControlLimits
from caliper.baseline.domain.fitted_cusum import FittedCUSUM
from caliper.baseline.domain.fitted_ewma import FittedEWMA
from caliper.baseline.domain.fitted_shewhart import FittedShewhart
from caliper.errors import InvalidObservationError, InvalidParameterError
from caliper.measurement import ScoringResult
from caliper.monitoring.domain.monitoring_result import MonitoringResult

# Fields a candidate observation must expose to be treated as a complete
# ScoringResult. Mirrors caliper.baseline.domain.baseline's identically-named
# private helper -- duplicated here, not imported, since it is private to
# that module and this is the Phase II instance of the same check reusing
# InvalidObservationError, not a shared collaborator (ADR-009 section 3).
_REQUIRED_OBSERVATION_FIELDS = ("score", "reasoning", "provenance")

# Two-sided CUSUM's upper arm detects an increasing shift (improvement /
# baseline staleness under ADR-001's higher-is-better mapping); the lower
# arm detects a decreasing shift (degradation). "two_sided" checks both.
_DIRECTIONS_WITH_UPPER_ARM = frozenset({"two_sided", "upper"})
_DIRECTIONS_WITH_LOWER_ARM = frozenset({"two_sided", "lower"})


def _missing_observation_fields(candidate: object) -> list[str]:
    """Report which ``ScoringResult`` fields ``candidate`` does not expose.

    Used only after ``isinstance(candidate, ScoringResult)`` has already
    failed, to build ``InvalidObservationError.context["missing_fields"]``.
    """
    return [
        field for field in _REQUIRED_OBSERVATION_FIELDS if not hasattr(candidate, field)
    ]


class Monitor:
    """Records Phase II observations against one fitted control-limit artefact.

    Constructed from exactly one ``FittedControlLimits``-satisfying artefact
    (``FittedEWMA``, ``FittedCUSUM``, or ``FittedShewhart``). ``record()``
    checks the observation's provenance against the artefact's (reusing
    ``compare_provenance()``, BIN-68, unmodified) before any chart-specific
    comparison runs, then returns a ``MonitoringResult`` -- never raising for
    a genuine out-of-control determination, which is a normal, successful
    return value (ADR-009 section 4; BR-7).
    """

    def __init__(
        self, artefact: FittedControlLimits, *, retain_history: bool = True
    ) -> None:
        """Construct a ``Monitor`` from a fitted control-limit artefact.

        Parameters
        ----------
        artefact
            The fitted control-limit artefact -- the result of
            ``fit_ewma()``, ``fit_cusum()``, or ``fit_shewhart()`` -- this
            monitor records Phase II observations against. Referenced,
            never copied or mutated; remains immutable for this monitor's
            entire lifetime.
        retain_history
            Whether successfully recorded ``MonitoringResult``s are
            retained on ``.history``. Defaults to ``True``. **Risk:** a
            ``Monitor`` that retains history across an indefinitely
            running production process accumulates entries without bound
            -- there is no automatic eviction or sizing policy in R1
            (ADR-009 section 7). Pass ``False`` to opt out entirely, or
            call ``clear_history()`` periodically to bound growth
            manually.

        Raises
        ------
        InvalidParameterError
            ``artefact`` does not satisfy the ``FittedControlLimits``
            protocol.
        """
        if not isinstance(artefact, FittedControlLimits):
            raise InvalidParameterError(
                "artefact must satisfy the FittedControlLimits protocol",
                context={
                    "parameter": "artefact",
                    "constraint": (
                        "must be a fitted control-limit artefact -- the return "
                        "value of fit_ewma(), fit_cusum(), or fit_shewhart()"
                    ),
                    "kind": "invalid",
                    "provided": artefact,
                },
                recovery_hint=(
                    "Construct Monitor from the return value of fit_ewma(), "
                    "fit_cusum(), or fit_shewhart() -- not a bare value."
                ),
            )

        self._artefact = artefact
        self._retain_history = retain_history
        self._history: list[MonitoringResult] = []

        # Chart-specific accumulator state -- private, per-instance, never
        # read from or written to the fitted artefact (ADR-009 section 1;
        # docs/domain-model.md Object Map -- Monitor, invariant 3). Left
        # unused for Shewhart, which is memoryless by design (BR-4).
        self._ewma_statistic: float = artefact.baseline_mean
        self._cusum_s_hi: float = 0.0
        self._cusum_s_lo: float = 0.0

    @property
    def history(self) -> tuple[MonitoringResult, ...]:
        """Every successfully recorded ``MonitoringResult``, in recording order.

        A fresh ``tuple`` view -- never the private backing list itself, so
        no caller can reach in and mutate ``Monitor``'s internal state
        through it (mirrors ``Baseline.observations``).
        """
        return tuple(self._history)

    def clear_history(self) -> None:
        """Discard all retained history immediately.

        The manual escape hatch for the unbounded-growth risk documented on
        ``retain_history`` above (ADR-009 section 7) -- there is no
        automatic eviction policy in R1. Does not affect this monitor's
        chart-specific accumulator state; only ``.history`` is cleared.
        """
        self._history.clear()

    def record(self, observation: ScoringResult) -> MonitoringResult:
        """Record a Phase II observation and check it for a signal.

        Enforces, in order: that ``observation`` is a complete
        ``ScoringResult``; that its provenance matches this monitor's
        fitted artefact (``compare_provenance()``, BIN-68). Only once both
        checks pass does the chart-specific comparison run and the
        accumulator (if any) update. A refused attempt never appears in
        ``.history``.

        Parameters
        ----------
        observation
            The Phase II scoring result to check, typically the return
            value of ``Judge.score()``.

        Returns
        -------
        MonitoringResult
            Describes whether the process remains in control. Never
            raised for a genuine out-of-control determination -- that is
            a normal, successful return value (BR-7).

        Raises
        ------
        InvalidObservationError
            ``observation`` is not a complete ``ScoringResult``.
        ProvenanceMismatchError
            ``observation.provenance`` differs from the fitted artefact's
            baseline provenance on either dimension.
        """
        if not isinstance(observation, ScoringResult):
            raise InvalidObservationError(
                "recorded observation is not a complete scoring result",
                context={
                    "reason": (
                        "input is missing one or more required ScoringResult "
                        "fields (score, reasoning, provenance)"
                    ),
                    "missing_fields": _missing_observation_fields(observation),
                },
                recovery_hint=(
                    "Pass a complete ScoringResult (score, reasoning, "
                    "provenance) -- typically the return value of "
                    "Judge.score()."
                ),
            )

        compare_provenance(observation, self._artefact)

        is_in_control = self._check(observation.score)
        outcome = MonitoringResult(
            is_in_control=is_in_control,
            observation=observation,
            chart_type=self._artefact.chart_type,
        )
        if self._retain_history:
            self._history.append(outcome)
        return outcome

    def _check(self, score: float) -> bool:
        """Dispatch to the chart-specific comparison for this monitor's artefact.

        Narrows ``self._artefact`` to its concrete chart type via
        ``isinstance`` -- the shared ``FittedControlLimits`` protocol
        deliberately excludes detection boundaries (ADR-004 section 3), so
        the chart-specific fields (``ucl``/``lcl``, ``decision_interval``,
        etc.) are only reachable on the concrete type.
        """
        artefact = self._artefact
        if isinstance(artefact, FittedShewhart):
            return self._check_shewhart(artefact, score)
        if isinstance(artefact, FittedEWMA):
            return self._check_ewma(artefact, score)
        if isinstance(artefact, FittedCUSUM):
            return self._check_cusum(artefact, score)
        raise AssertionError(  # pragma: no cover
            f"unrecognised fitted artefact type: {type(artefact).__name__!r}"
        )

    def _check_shewhart(self, artefact: FittedShewhart, score: float) -> bool:
        """Memoryless: compares ``score`` directly against ``ucl``/``lcl``.

        Strict inequality throughout (ADR-009 section 5, verified against
        Montgomery 7th ed.): a point exactly at a control limit is in
        control, not out.
        """
        return not (score > artefact.ucl or score < artefact.lcl)

    def _check_ewma(self, artefact: FittedEWMA, score: float) -> bool:
        """Recursive: update the smoothed statistic, then compare to ``ucl``/``lcl``.

        Notes
        -----
        ``Z_i = lambda * X_i + (1 - lambda) * Z_(i-1)``, initialised at
        construction to the baseline mean (``cl``) so the very first
        recorded observation is checkable without any prior history
        (BIN-69 SC5). Strict inequality throughout (ADR-009 section 5).

        [OQ-12, open -- BIN-113] What the accumulator should become
        immediately after a signal (reset to zero, FIR head-start, or
        continue unchanged) is explicitly undecided (ADR-009 section 1;
        docs/domain-model.md Open Question 12). This always updates and
        never resets -- the minimal, no-mechanism default, not a
        considered choice among the three options. Do not read this as
        having settled OQ-12.
        """
        self._ewma_statistic = (
            artefact.smoothing_param * score
            + (1.0 - artefact.smoothing_param) * self._ewma_statistic
        )
        return not (
            self._ewma_statistic > artefact.ucl or self._ewma_statistic < artefact.lcl
        )

    def _check_cusum(self, artefact: FittedCUSUM, score: float) -> bool:
        """Recursive: update both one-sided sums, then compare the relevant one(s).

        Notes
        -----
        Standardised-CUSUM convention (``src/caliper/baseline/domain/cusum_fitting.py``
        module docstring, citing Siegmund 1985 via Montgomery):
        ``Z_t = (X_t - target_value) / sigma_estimate``,
        ``S_hi_t = max(0, S_hi_(t-1) + Z_t - k)`` (upper arm -- increasing
        shift), ``S_lo_t = max(0, S_lo_(t-1) - Z_t - k)`` (lower arm --
        decreasing shift). Both sums are initialised to zero at
        construction, so the first recorded observation needs no prior
        history (BIN-69 SC5). A signal is ``S_hi > h`` or ``S_lo > h`` --
        strict inequality (ADR-009 section 5) -- gated by ``direction``:
        ``"two_sided"`` checks both arms, ``"upper"``/``"lower"`` checks
        only its own.

        Both sums are always updated regardless of ``direction``, so
        switching which arm(s) are *checked* never depends on which
        arm(s) have historically been *updated*.

        [OQ-12, open -- BIN-113] See ``_check_ewma``'s identical note --
        the same provisional, no-reset treatment applies to both sums here.
        """
        standardised = (score - artefact.target_value) / artefact.sigma_estimate
        k = artefact.reference_value
        h = artefact.decision_interval

        self._cusum_s_hi = max(0.0, self._cusum_s_hi + standardised - k)
        self._cusum_s_lo = max(0.0, self._cusum_s_lo - standardised - k)

        signalled = False
        if artefact.direction in _DIRECTIONS_WITH_UPPER_ARM:
            signalled = signalled or self._cusum_s_hi > h
        if artefact.direction in _DIRECTIONS_WITH_LOWER_ARM:
            signalled = signalled or self._cusum_s_lo > h
        return not signalled
