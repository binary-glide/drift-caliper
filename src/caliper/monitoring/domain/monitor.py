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

Extended by ``docs/architecture/adr/010-signal-delivery-and-absorb-but-surface.md``
with a ``receivers`` constructor parameter and a synchronous delivery step
inside ``record()`` -- see that method's docstring.
"""

from __future__ import annotations

from collections.abc import Sequence

from caliper.baseline.domain.compare_provenance import compare_provenance
from caliper.baseline.domain.fitted_control_limits import FittedControlLimits
from caliper.baseline.domain.fitted_cusum import FittedCUSUM
from caliper.baseline.domain.fitted_ewma import FittedEWMA
from caliper.baseline.domain.fitted_shewhart import FittedShewhart
from caliper.errors import InvalidObservationError, InvalidParameterError
from caliper.measurement import ScoringResult
from caliper.monitoring.domain.delivery_failure import DeliveryFailure
from caliper.monitoring.domain.monitoring_result import MonitoringResult
from caliper.monitoring.domain.signal_receiver import SignalReceiver

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

# BIN-118 fallbacks: used only if a receiver's own __repr__ (or, in turn,
# type(receiver).__name__) raises. Constants, not derived -- there is
# nothing left to safely introspect about a receiver that fails at every
# level of description.
_UNREPRESENTABLE_RECEIVER = "<unrepresentable receiver>"


def _describe_receiver(receiver: SignalReceiver) -> str:
    """Format a receiver for ``DeliveryFailure.receiver`` (BIN-118).

    Tries ``repr(receiver)`` first, falling back to
    ``type(receiver).__name__``, then to a fixed constant.
    ``Monitor._deliver`` builds ``DeliveryFailure`` from this identifier
    *after* the receiver has already raised -- a receiver whose own
    ``__repr__`` also raises (e.g. it touches a closed file or a detached
    ORM session) must not let that second exception escape ``record()`` in
    turn. Reachable by ordinary third-party code, not just malice --
    reproduced by external code review, 2026-09-11 (Linear BIN-118).
    """
    try:
        return repr(receiver)
    except Exception:
        try:
            return type(receiver).__name__
        except Exception:  # pragma: no cover
            # type()/__name__ read a class attribute and cannot execute
            # user code for an ordinary class -- unreachable in practice,
            # but the fallback the ticket specifies still needs a floor.
            return _UNREPRESENTABLE_RECEIVER


def _describe_exception(exc: Exception) -> str:
    """``str(exc)``, falling back to ``type(exc).__name__`` (BIN-118).

    The sibling hazard to ``_describe_receiver``: a custom exception with a
    broken ``__str__`` must not let that failure escape ``record()`` either.
    ``type(exc).__name__`` alone (used for ``DeliveryFailure.error_type``)
    is always safe -- it is a class attribute, not a call into user code --
    so only ``str()`` itself needs a guard here.
    """
    try:
        return str(exc)
    except Exception:
        return type(exc).__name__


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
        self,
        artefact: FittedControlLimits,
        *,
        retain_history: bool = True,
        receivers: Sequence[SignalReceiver] = (),
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
        receivers
            Callables invoked, in order, with the ``MonitoringResult``
            whenever ``record()`` produces a genuine signal (ADR-010
            section 3). Defaults to ``()`` -- no receivers configured.
            Fixed for this monitor's entire lifetime -- there is no
            add/remove method in R1.

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
        self._receivers = tuple(receivers)
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
        accumulator (if any) update.

        On a genuine signal (``is_in_control is False``), every configured
        receiver is then invoked, in order, with the result -- each inside
        its own ``try``/``except`` so one receiver's failure never stops
        the next from being attempted (ADR-010 section 4, "absorb, but
        surface"). A receiver's exception is captured into the returned
        result's ``delivery_failures``, never re-raised and never silently
        discarded. A refused attempt (the two precondition violations
        below) never appears in ``.history`` and never reaches delivery.

        Parameters
        ----------
        observation
            The Phase II scoring result to check, typically the return
            value of ``Judge.score()``.

        Returns
        -------
        MonitoringResult
            Describes whether the process remains in control, and, on a
            signal, the direction of departure and any delivery failures.
            Never raised for a genuine out-of-control determination, and
            never raised for a delivery failure -- both are normal,
            successful return values (BR-7; ADR-010 section 1).

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

        is_in_control, direction = self._check(observation.score)
        provisional = MonitoringResult(
            is_in_control=is_in_control,
            observation=observation,
            chart_type=self._artefact.chart_type,
            direction=direction,
            fitted_artefact=self._artefact,
        )

        outcome = provisional
        if not is_in_control:
            outcome = self._deliver(provisional)

        if self._retain_history:
            self._history.append(outcome)
        return outcome

    def _deliver(self, signal: MonitoringResult) -> MonitoringResult:
        """Invoke every configured receiver with ``signal``, in order.

        Mirrors ADR-010 section 4's delivery sequence exactly:

        1. (Step 2, done by the caller) ``signal`` is the provisional
           result -- ``delivery_failures=()`` -- built by ``record()``.
        2. (Step 3) Every receiver is called with that *same* unmodified
           ``signal``, each inside its own ``try``/``except`` so one
           receiver's failure never stops the next from being attempted.
           A failure is recorded as a ``DeliveryFailure`` built entirely
           from the caught exception (``type(exc).__name__``,
           ``_describe_exception(exc)``) -- never by consulting anything
           the receiver itself reports (ADR-010 section 1). No receiver
           ever observes another receiver's failure: each sees the same
           pristine, empty ``delivery_failures`` regardless of position in
           ``receivers``.

           ⚠️ **BIN-118:** describing the failure -- ``repr(receiver)``
           and ``str(exc)`` -- is itself capable of raising (a receiver
           whose own ``__repr__`` touches a closed file or detached
           session; a custom exception with a broken ``__str__``), so
           ``_describe_receiver``/``_describe_exception`` wrap those calls
           with their own fallbacks rather than being called directly
           inside this ``try``. Absorbing the receiver's exception but then
           letting its *description* propagate would still break every
           guarantee this method exists to provide.
        3. (Step 4) If any failures were collected, exactly one
           ``model_copy`` produces the final result after the loop --
           never per-failure. That final result is what ``record()``
           returns and retains in history.
        """
        failures: list[DeliveryFailure] = []
        for receiver in self._receivers:
            try:
                receiver(signal)
            except Exception as exc:
                failures.append(
                    DeliveryFailure(
                        receiver=_describe_receiver(receiver),
                        error_type=type(exc).__name__,
                        error_message=_describe_exception(exc),
                    )
                )
        if not failures:
            return signal
        return signal.model_copy(update={"delivery_failures": tuple(failures)})

    def _check(self, score: float) -> tuple[bool, str | None]:
        """Dispatch to the chart-specific comparison for this monitor's artefact.

        Narrows ``self._artefact`` to its concrete chart type via
        ``isinstance`` -- the shared ``FittedControlLimits`` protocol
        deliberately excludes detection boundaries (ADR-004 section 3), so
        the chart-specific fields (``ucl``/``lcl``, ``decision_interval``,
        etc.) are only reachable on the concrete type.

        Returns
        -------
        tuple[bool, str | None]
            ``(is_in_control, direction)``. ``direction`` is ``"upper"``
            or ``"lower"`` when a signal occurred (never
            ``"two_sided"`` -- see ``MonitoringResult.direction``'s field
            comment), or ``None`` when in control.
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

    def _check_shewhart(
        self, artefact: FittedShewhart, score: float
    ) -> tuple[bool, str | None]:
        """Memoryless: compares ``score`` directly against ``ucl``/``lcl``.

        Strict inequality throughout (ADR-009 section 5, verified against
        Montgomery 7th ed.): a point exactly at a control limit is in
        control, not out.
        """
        if score > artefact.ucl:
            return False, "upper"
        if score < artefact.lcl:
            return False, "lower"
        return True, None

    def _check_ewma(
        self, artefact: FittedEWMA, score: float
    ) -> tuple[bool, str | None]:
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
        if self._ewma_statistic > artefact.ucl:
            return False, "upper"
        if self._ewma_statistic < artefact.lcl:
            return False, "lower"
        return True, None

    def _check_cusum(
        self, artefact: FittedCUSUM, score: float
    ) -> tuple[bool, str | None]:
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
        only its own. The reported direction is always the arm that
        actually crossed ``h`` -- never ``artefact.direction`` itself,
        which would leak the three-valued configuration vocabulary onto
        this two-valued outcome (``MonitoringResult.direction``'s field
        comment; domain-model.md's explicit warning).

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

        if artefact.direction in _DIRECTIONS_WITH_UPPER_ARM and self._cusum_s_hi > h:
            return False, "upper"
        if artefact.direction in _DIRECTIONS_WITH_LOWER_ARM and self._cusum_s_lo > h:
            return False, "lower"
        return True, None
