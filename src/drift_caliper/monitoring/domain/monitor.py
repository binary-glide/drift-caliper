"""``Monitor`` -- records Phase II observations against a fitted artefact.

See ``docs/domain-model.md`` (Object Map -- Monitor, the domain's second
mutable object) and
``docs/architecture/adr/009-phase-ii-monitor-and-observation-store.md`` for
the full design reasoning. Mirrors ``drift_caliper.baseline.domain.baseline``'s
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

from drift_caliper.baseline.domain.attribute_probe import invalid_observation_error
from drift_caliper.baseline.domain.bernoulli_arm_lattice import (
    BernoulliArmLattice,
    lattice_integer_violation,
)
from drift_caliper.baseline.domain.compare_provenance import compare_provenance
from drift_caliper.baseline.domain.fitted_bernoulli_cusum import FittedBernoulliCUSUM
from drift_caliper.baseline.domain.fitted_control_limits import FittedControlLimits
from drift_caliper.baseline.domain.fitted_cusum import FittedCUSUM
from drift_caliper.baseline.domain.fitted_ewma import FittedEWMA
from drift_caliper.baseline.domain.fitted_shewhart import FittedShewhart
from drift_caliper.baseline.domain.parameter_guards import require_exact_str
from drift_caliper.errors import InvalidObservationError, InvalidParameterError
from drift_caliper.measurement import ScoringResult
from drift_caliper.monitoring.domain.delivery_failure import DeliveryFailure
from drift_caliper.monitoring.domain.monitoring_result import MonitoringResult
from drift_caliper.monitoring.domain.signal_receiver import SignalReceiver

# Two-sided CUSUM's upper arm detects an increasing shift (improvement /
# baseline staleness under ADR-001's higher-is-better mapping); the lower
# arm detects a decreasing shift (degradation). "two_sided" checks both.
_DIRECTIONS_WITH_UPPER_ARM = frozenset({"two_sided", "upper"})
_DIRECTIONS_WITH_LOWER_ARM = frozenset({"two_sided", "lower"})
# The union, for the error message only -- the two sets above are what the
# check actually consults.
_VALID_ARTEFACT_DIRECTIONS = _DIRECTIONS_WITH_UPPER_ARM | _DIRECTIONS_WITH_LOWER_ARM

# BIN-118 fallbacks: used only if an object's own __repr__ (or, in turn,
# type(obj).__name__) raises. Constants, not derived -- there is nothing
# left to safely introspect about an object that fails at every level of
# description. One constant per call site so the fallback string still
# names what could not be described, rather than a single generic label.
_UNREPRESENTABLE_RECEIVER = "<unrepresentable receiver>"
_UNREPRESENTABLE_ARTEFACT = "<unrepresentable artefact>"


_LATTICE_INTEGERS = ("denominator", "reference_units", "decision_interval_units")


def _checked_lattice(
    artefact: FittedBernoulliCUSUM, field: str
) -> tuple[int, int, int]:
    """Re-validate one arm's lattice at use and return its three integers.

    ADR-014 Decision 14.5 (row M2) and corrigendum C4. The artefact is
    caller-supplied, and ``model_copy(update=...)``/``model_construct()``
    skip ``BernoulliArmLattice``'s validators, so each integer is re-checked
    with the same rule before ``Monitor`` steps it. A missing lattice, or
    anything that is not a ``BernoulliArmLattice``, reports only its type
    (``provided_type``), as does a non-exact ``int``; an exact ``int`` out of
    bounds reports its value (``provided``) -- corrigendum C6/C12.2.
    """
    lattice = getattr(artefact, field)
    if not isinstance(lattice, BernoulliArmLattice):
        raise _lattice_refusal(
            field,
            "must be a BernoulliArmLattice when direction checks this arm",
            {"provided_type": type(lattice).__name__},
        )
    values: dict[str, int] = {}
    for attribute in _LATTICE_INTEGERS:
        value = getattr(lattice, attribute)
        violation = lattice_integer_violation(
            attribute, value, denominator=values.get("denominator", 0)
        )
        if violation is not None:
            constraint, detail = violation
            raise _lattice_refusal(f"{field}.{attribute}", constraint, detail)
        values[attribute] = value
    return (
        values["denominator"],
        values["reference_units"],
        values["decision_interval_units"],
    )


def _lattice_refusal(
    field: str, constraint: str, detail: dict[str, object]
) -> InvalidParameterError:
    return InvalidParameterError(
        "the fitted Bernoulli CUSUM's lattice is not a chart Monitor can run",
        context={
            "parameter": "artefact",
            "constraint": constraint,
            "kind": "invalid",
            "field": field,
            **detail,
        },
        recovery_hint=(
            "Construct Monitor from the artefact fit_bernoulli_cusum() "
            "returned, or from FittedBernoulliCUSUM.model_validate() of its "
            "model_dump() -- both carry a validated lattice for every arm the "
            "chart checks. An artefact edited with model_copy(update=...) or "
            "built with model_construct() skips that validation."
        ),
    )


def _safe_repr(obj: object, *, fallback: str) -> str:
    """``repr(obj)``, falling back to ``type(obj).__name__``, then ``fallback``.

    Shared by every place this module needs to describe a caller-supplied
    object for an error or a ``DeliveryFailure`` *after* that object has
    already misbehaved in some way -- a receiver that raised (BIN-118), or
    an artefact ``Monitor.__init__``/``_check`` is rejecting (BIN-120).
    Describing the offender must not itself raise: an object whose
    ``__repr__`` touches a closed file or a detached ORM session is
    reachable by ordinary third-party code, not just malice --
    reproduced by external code review, 2026-09-11 (Linear BIN-118), and
    the identical hazard was found again at a second call site by
    ``code-reviewer`` on BIN-120's review.
    """
    try:
        return repr(obj)
    except Exception:
        try:
            return type(obj).__name__
        except Exception:  # pragma: no cover
            # type()/__name__ read a class attribute and cannot execute
            # user code for an ordinary class -- unreachable in practice,
            # but the fallback the ticket specifies still needs a floor.
            return fallback


def _describe_receiver(receiver: SignalReceiver) -> str:
    """Format a receiver for ``DeliveryFailure.receiver`` (BIN-118).

    ``Monitor._deliver`` builds ``DeliveryFailure`` from this identifier
    *after* the receiver has already raised -- a receiver whose own
    ``__repr__`` also raises must not let that second exception escape
    ``record()`` in turn. See ``_safe_repr``.
    """
    return _safe_repr(receiver, fallback=_UNREPRESENTABLE_RECEIVER)


def _describe_artefact(artefact: object) -> str:
    """Format a rejected artefact for ``context["provided"]`` on an error (BIN-120).

    ``Monitor.__init__``/``_check`` previously stored the live, rejected
    object directly in ``context["provided"]``. Three problems with that,
    found by ``code-reviewer`` on BIN-120's review: describing it is not
    guaranteed safe (an object whose own ``__repr__`` raises turns a caller's
    ``except InvalidParameterError: log(e.context)`` into an unhandled crash
    -- the exact BIN-118 hazard, at a second boundary); every other
    ``"provided"`` value in this codebase already holds a scalar the caller
    passed, never a live object; and keeping a reference to a caller's
    object alive inside an exception's ``context`` is both an unnecessary
    lifetime extension and something a serialiser (e.g. structured logging)
    cannot always handle. A guarded string description fixes all three at
    once. See ``_safe_repr``.
    """
    return _safe_repr(artefact, fallback=_UNREPRESENTABLE_ARTEFACT)


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


class Monitor:
    """Records Phase II observations against one fitted control-limit artefact.

    Constructed from exactly one supported fitted artefact --
    ``FittedEWMA``, ``FittedCUSUM``, ``FittedShewhart`` (each satisfying
    ``FittedControlLimits``), or ``FittedBernoulliCUSUM`` (which satisfies
    only ``HasProvenance`` -- ADR-014 section 6a; BIN-133). ``record()``
    checks the observation's provenance against the artefact's (reusing
    ``compare_provenance()``, BIN-68, unmodified) before any chart-specific
    comparison runs, then returns a ``MonitoringResult`` -- never raising for
    a genuine out-of-control determination, which is a normal, successful
    return value (ADR-009 section 4; BR-7).
    """

    def __init__(
        self,
        artefact: FittedControlLimits | FittedBernoulliCUSUM,
        *,
        retain_history: bool = True,
        receivers: Sequence[SignalReceiver] = (),
    ) -> None:
        """Construct a ``Monitor`` from a fitted control-limit artefact.

        Parameters
        ----------
        artefact
            The fitted artefact -- the result of ``fit_ewma()``,
            ``fit_cusum()``, ``fit_shewhart()``, or ``fit_bernoulli_cusum()``
            -- this monitor records Phase II observations against.
            Referenced, never copied or mutated; remains immutable for this
            monitor's entire lifetime.
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
            ``artefact`` is not one of the four concrete fitted artefact
            types this monitor knows how to check (``FittedEWMA``,
            ``FittedCUSUM``, ``FittedShewhart``, ``FittedBernoulliCUSUM``)
            -- including an object that satisfies the
            ``FittedControlLimits`` protocol structurally but is none of
            them (BIN-120).
        """
        # BIN-120: narrowed to the concrete chart types rather than
        # `isinstance(artefact, FittedControlLimits)`. That protocol check
        # alone let any structurally conforming object through the
        # constructor -- `@runtime_checkable` verifies attribute names, not
        # chart identity -- and `_check()` below only knows how to dispatch
        # on these concrete types. A third-party artefact that merely
        # satisfied the protocol was accepted here and then failed on its
        # first `record()` call with a raw `AssertionError`, which is not a
        # `CaliperError` and is stripped entirely under `python -O`. This is
        # option A from ADR-004 section 3's polymorphism discussion
        # (narrow the boundary, not the deliberately chart-specific
        # protocol) -- do not widen this back to the protocol check without
        # first giving `FittedControlLimits` a genuine polymorphic
        # detection operation, which ADR-004 rejected for R1.
        #
        # Widened to a fourth concrete type, `FittedBernoulliCUSUM`, under
        # BIN-133 (ADR-014 section 6a) -- that type does not itself satisfy
        # `FittedControlLimits` (it satisfies only `HasProvenance`), so this
        # is a genuine widening of the accepted-type tuple, not a narrowing
        # to a stricter protocol.
        if not isinstance(
            artefact, (FittedEWMA, FittedCUSUM, FittedShewhart, FittedBernoulliCUSUM)
        ):
            raise InvalidParameterError(
                "artefact must be one of the fitted artefact types Monitor supports",
                context={
                    "parameter": "artefact",
                    "constraint": (
                        "must be a fitted artefact -- the return value of "
                        "fit_ewma(), fit_cusum(), fit_shewhart(), or "
                        "fit_bernoulli_cusum()"
                    ),
                    "kind": "invalid",
                    "provided": _describe_artefact(artefact),
                },
                recovery_hint=(
                    "Construct Monitor from the return value of fit_ewma(), "
                    "fit_cusum(), fit_shewhart(), or fit_bernoulli_cusum() "
                    "-- not a bare value, and not a custom object that "
                    "merely satisfies the FittedControlLimits protocol "
                    "structurally. Monitor only knows how to check EWMA, "
                    "CUSUM, Shewhart, and Bernoulli CUSUM artefacts."
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
        # `FittedBernoulliCUSUM` has no `baseline_mean` (ADR-014 section
        # 6a), so the EWMA accumulator -- unused for this chart type in any
        # case -- cannot be initialised from it; 0.0 is an inert value never
        # read on that path.
        self._ewma_statistic: float = (
            0.0
            if isinstance(artefact, FittedBernoulliCUSUM)
            else artefact.baseline_mean
        )
        self._cusum_s_hi: float = 0.0
        self._cusum_s_lo: float = 0.0
        # Integer lattice units, never floats (ADR-014 Decision 14.4).
        self._bernoulli_s_lower: int = 0
        self._bernoulli_s_upper: int = 0

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
        fitted artefact (``compare_provenance()``, BIN-68); and, only when
        this monitor was constructed from a ``FittedBernoulliCUSUM``, that
        ``observation.score`` is exactly ``0.0`` or ``1.0`` (ADR-014
        Decision 2; BIN-133) -- a legal, finite, in-range continuous score
        that every other chart type accepts is outside the domain a binary
        chart can interpret. Only once every check passes does the
        chart-specific comparison run and the accumulator (if any) update.

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
            ``observation`` is not a complete ``ScoringResult``; or this
            monitor's fitted artefact is a ``FittedBernoulliCUSUM`` and
            ``observation.score`` is not exactly ``0.0`` or ``1.0``
            (``context["reason"] == "score_not_binary"``, ADR-014
            Decision 2).
        ProvenanceMismatchError
            ``observation.provenance`` differs from the fitted artefact's
            baseline provenance on either dimension.
        """
        if not isinstance(observation, ScoringResult):
            raise invalid_observation_error(observation)

        compare_provenance(observation, self._artefact)

        if isinstance(self._artefact, FittedBernoulliCUSUM):
            score = observation.score
            if score != 0.0 and score != 1.0:
                raise InvalidObservationError(
                    "a Phase II observation checked against a "
                    "FittedBernoulliCUSUM must have a score that is "
                    "exactly 0.0 or 1.0",
                    context={
                        "reason": "score_not_binary",
                        "missing_fields": (),
                    },
                    recovery_hint=(
                        "This monitor was constructed from a "
                        "FittedBernoulliCUSUM, which can only interpret a "
                        "pass (1.0) or fail (0.0) score -- not a continuous "
                        "value. No tolerance band is applied near either "
                        "boundary. Score the observation with a rubric "
                        "that returns exactly 0.0 or 1.0, or record it "
                        "against a continuous chart type instead."
                    ),
                )

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
        if isinstance(artefact, FittedBernoulliCUSUM):
            return self._check_bernoulli_cusum(artefact, score)
        # BIN-120: genuinely unreachable now that the constructor narrows
        # `artefact` to these same concrete types -- kept only as a typed
        # fallback for the type checker's exhaustiveness requirement
        # (`_check` must return a tuple on every path). Previously a raw
        # `AssertionError`: not a `CaliperError` (no `category`, no
        # `context`), and `assert` statements are stripped entirely under
        # `python -O`, so a change that ever did reach this branch would
        # have produced undefined behaviour instead of an exception. A
        # typed `CaliperError` costs nothing here and never leaves a
        # foreign exception type as the only thing standing between a
        # future defect and an unhandled crash.
        raise InvalidParameterError(  # pragma: no cover
            "artefact must be one of the fitted artefact types Monitor supports",
            context={
                "parameter": "artefact",
                "constraint": (
                    "must be a fitted artefact -- the return value of "
                    "fit_ewma(), fit_cusum(), fit_shewhart(), or "
                    "fit_bernoulli_cusum()"
                ),
                "kind": "invalid",
                "provided": _describe_artefact(artefact),
            },
            recovery_hint=(
                "Construct Monitor from the return value of fit_ewma(), "
                "fit_cusum(), fit_shewhart(), or fit_bernoulli_cusum() -- "
                "not a bare value, and not a custom object that merely "
                "satisfies the FittedControlLimits protocol structurally. "
                "Monitor only knows how to check EWMA, CUSUM, Shewhart, "
                "and Bernoulli CUSUM artefacts."
            ),
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
        Standardised-CUSUM convention (``cusum_fitting.py``'s module
        docstring, citing Siegmund 1985 via Montgomery):
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

        # 🚨 Narrow before the membership tests. `in` on a frozenset calls
        # `__hash__`, and `artefact` is caller-supplied -- so a `direction`
        # that is not an exact `str` hands control to the caller from inside
        # `record()` (BIN-143, the same defect `fit_cusum` has at its own
        # membership site).
        #
        # ⚠️ Reachable despite `__init__`'s isinstance narrowing and the
        # `str` field annotation, because Pydantic's *validation* is what
        # coerces a subclass to an exact `str` -- and `model_copy(update=...)`
        # and `model_construct()` both skip validation by design. Verified:
        # both routes put a raising-`__hash__` subclass on the field and
        # leaked a `RuntimeError` out of `record()`.
        #
        # Guarding here rather than at construction is deliberate: it protects
        # the behaviour regardless of how the artefact was built, which is the
        # only version of this check that cannot be walked around.
        direction = require_exact_str(
            artefact.direction,
            parameter="direction",
            constraint=f"must be one of {sorted(_VALID_ARTEFACT_DIRECTIONS)}",
        )

        if direction in _DIRECTIONS_WITH_UPPER_ARM and self._cusum_s_hi > h:
            return False, "upper"
        if direction in _DIRECTIONS_WITH_LOWER_ARM and self._cusum_s_lo > h:
            return False, "lower"
        return True, None

    def _check_bernoulli_cusum(
        self, artefact: FittedBernoulliCUSUM, score: float
    ) -> tuple[bool, str | None]:
        """Step each checked arm's integer lattice, exactly as the fit solved it.

        Notes
        -----
        The artefact's ``lattice_lower``/``lattice_upper`` are the chart
        (ADR-014 Decision 14): each arm's statistic is an ``int`` in units of
        ``1/denominator``, stepped by exactly the transitions whose
        absorption time the fit reports as ``achieved_arl``. The derived float
        fields are never read -- accumulating them in binary floating point
        ran a different chart, which signalled earlier than the reported one
        (Amendment 2 section 0, defect 3). Per Decision 14.4:

        - failure (``score == 0.0``): ``s_lo += N_lo - r_lo``;
          ``s_up = max(0, s_up - r_up)``
        - success (``score == 1.0``): ``s_lo = max(0, s_lo - r_lo)``;
          ``s_up += N_up - r_up``

        Only the arms ``direction`` checks accumulate (corrigendum C3). A
        signal is a statistic strictly exceeding its ``decision_interval_units``
        (ADR-009 section 5 / BIN-112). Everything read from the
        caller-supplied artefact is validated before any state changes
        (Decision 14.5, corrigendum C4, BIN-143).
        """
        # 🚨 Same BIN-143 hazard `_check_cusum` guards against -- `artefact`
        # is caller-supplied, and `in` on a frozenset hashes it before any
        # comparison happens.
        direction = require_exact_str(
            artefact.direction,
            parameter="direction",
            constraint=f"must be one of {sorted(_VALID_ARTEFACT_DIRECTIONS)}",
        )
        lower = (
            _checked_lattice(artefact, "lattice_lower")
            if direction in _DIRECTIONS_WITH_LOWER_ARM
            else None
        )
        upper = (
            _checked_lattice(artefact, "lattice_upper")
            if direction in _DIRECTIONS_WITH_UPPER_ARM
            else None
        )

        failed = score == 0.0
        if lower is not None:
            n, r, _ = lower
            self._bernoulli_s_lower = (
                self._bernoulli_s_lower + (n - r)
                if failed
                else max(0, self._bernoulli_s_lower - r)
            )
        if upper is not None:
            n, r, _ = upper
            self._bernoulli_s_upper = (
                max(0, self._bernoulli_s_upper - r)
                if failed
                else self._bernoulli_s_upper + (n - r)
            )

        if lower is not None and self._bernoulli_s_lower > lower[2]:
            return False, "lower"
        if upper is not None and self._bernoulli_s_upper > upper[2]:
            return False, "upper"
        return True, None
