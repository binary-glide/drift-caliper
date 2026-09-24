"""Clopper-Pearson confidence bounds -- the ``p_U`` and ``p_L`` GICP designs against.

See ``docs/architecture/adr/013-gicp-supersedes-the-provisional-baseline-floor.md``
section 1. Guaranteed In-Control Performance (Heidema et al. 2026) designs a
chart against an upper confidence bound on the in-control parameter rather
than its plain point estimate, so a small or unlucky Phase I baseline cannot
silently under-deliver its promised false-alarm rate. Bernoulli's exact
analogue of the paper's Poisson construction (Garwood's exact limit) is the
classical Clopper-Pearson interval:

    p_U(f, m, alpha) = quantile function of Beta(f+1, m-f) at 1-alpha  (f < m)
    p_U(0, m, alpha) = 1 - alpha**(1/m)                    (closed form, f=0)
    p_L(f, m, alpha) = quantile function of Beta(f, m-f+1) at alpha    (f > 0)
    p_L(0, m, alpha) = 0

The lower bound is ADR-014 Decision 19.1's addition: the Bernoulli CUSUM's
improvement-detecting arm alarms *more* as the failure rate falls, so its
conservative design rate is the lower bound, by the mirror of the same
coupling argument.

``alpha`` is not exposed here as a validated, engineer-facing range -- it is
supplied by ``bernoulli_cusum_fitting.py`` as a fixed internal constant
(ADR-013 section 3, ADR-014 Decision 5). This module only implements the
formula itself.

**Why the closed form at f=0 is not just a shortcut.** At ``f=0``,
``Beta(f+1, m-f) == Beta(1, m)``, whose CDF has the closed form
``F(x) = 1 - (1-x)**m``, so ``ppf(1-alpha) = 1 - alpha**(1/m)`` algebraically
-- ``tests/unit/baseline/test_clopper_pearson.py`` verifies this equivalence
directly against ``scipy.stats.beta.ppf`` rather than assuming it. Using the
closed form avoids a beta-quantile evaluation at a degenerate shape parameter
purely as a numerical-stability nicety; both forms agree to floating
precision where the general formula is even defined (``f=0`` still needs
``m-f=m > 0``, which the general branch's own guard already requires).

References
----------
.. [1] Heidema, ... (2026). "The Poisson CUSUM Chart for Monitoring Small
       Counts: Addressing the Estimation Uncertainty." Biometrical Journal,
       open access, PMC13051258 -- states the GICP construction generalises to
       "any distribution where an ordering of parameters implies stochastic
       dominance" and demonstrates a binomial application in its supplementary
       material.
.. [2] Clopper, C. J. and Pearson, E. S. (1934). "The use of confidence or
       fiducial limits illustrated in the case of the binomial." Biometrika,
       26(4), 404-413 -- the exact interval this module implements the upper
       arm of.
"""

from __future__ import annotations

import math

from scipy.stats import beta  # type: ignore[attr-defined]

from drift_caliper.errors import InvalidParameterError


def _require_valid_counts(*, failures: int, observations: int) -> None:
    """Reject counts outside both bounds' shared domain, ``0 <= f < m``.

    Shared by :func:`clopper_pearson_upper_bound` and
    :func:`clopper_pearson_lower_bound` so the two bounds can never disagree
    about which baselines are legal.
    """
    if observations <= 0:
        raise InvalidParameterError(
            "observations must be a positive integer",
            context={
                "parameter": "observations",
                "constraint": "must be a positive integer",
                "kind": "invalid",
                "provided": observations,
            },
            recovery_hint=(
                "Pass a positive observation count -- the number of Phase I "
                "judgements the failure rate was estimated from."
            ),
        )
    if failures < 0 or failures >= observations:
        raise InvalidParameterError(
            "failures must be between 0 and observations (exclusive of "
            "observations itself)",
            context={
                "parameter": "failures",
                "constraint": f"must satisfy 0 <= failures < {observations}",
                "kind": "invalid",
                "provided": failures,
            },
            recovery_hint=(
                "Clopper-Pearson's upper bound is undefined when every "
                "observation failed (failures == observations) -- "
                "Beta(failures + 1, observations - failures) has no defined "
                "second shape parameter at that point. A caller with an "
                "all-failed baseline must handle that case before calling "
                "this function."
            ),
        )


def clopper_pearson_upper_bound(
    *, failures: int, observations: int, alpha: float
) -> float:
    """Compute the one-sided Clopper-Pearson upper confidence bound ``p_U``.

    Parameters
    ----------
    failures
        The observed failure count ``f``. Must satisfy ``0 <= failures <
        observations``.
    observations
        The total observation count ``m``. Must be strictly positive.
    alpha
        The guarantee's own risk appetite -- ``P[true ARL0 >= target] >= 1 -
        alpha`` (ADR-013 section 3). Caliper always calls this with its
        fixed, ratified ``0.10``; this function does not itself validate
        ``alpha``'s range, since it is never engineer-supplied
        (``bernoulli_cusum_fitting.py`` owns that constant).

    Returns
    -------
    float
        ``p_U``, always strictly greater than ``0.0`` and at least
        ``failures / observations``.

    Raises
    ------
    InvalidParameterError
        ``observations <= 0``, or ``failures`` is outside
        ``[0, observations)`` -- ``failures == observations`` (the
        all-failed case) has no defined ``Beta(f+1, m-f)``, since
        ``m - f`` would be ``0``. Callers with an all-failed baseline must
        handle that case themselves before reaching this function
        (ADR-013 section 5) -- it is a different, more specific failure
        than an ordinary out-of-range ``failures``/``observations`` pair.
    """
    _require_valid_counts(failures=failures, observations=observations)
    if failures == 0:
        # math.pow, not `alpha ** (1.0 / observations)` -- typeshed's
        # `float.__pow__` stub returns a union including `complex` (a
        # negative base with a fractional exponent is complex at runtime),
        # so mypy cannot narrow the plain `**` operator's result to `float`
        # even though `alpha` is always in `(0, 1)` here. `math.pow` is
        # typed as `(float, float) -> float` unconditionally.
        return 1.0 - math.pow(alpha, 1.0 / observations)
    # scipy.stats.beta.ppf has no type stub mypy can see (same scipy
    # stub-coverage gap the `beta` import above works around).
    return float(beta.ppf(1.0 - alpha, failures + 1, observations - failures))


def clopper_pearson_lower_bound(
    *, failures: int, observations: int, alpha: float
) -> float:
    """Compute the one-sided Clopper-Pearson lower confidence bound ``p_L``.

    The ``alpha`` quantile of ``Beta(f, m - f + 1)`` -- the mirror of
    :func:`clopper_pearson_upper_bound`, and the design rate of the Bernoulli
    CUSUM's upper (improvement-detecting) arm (ADR-014 Decision 19.1). That
    arm signals on *successes*, so its in-control ARL falls as the true
    failure rate falls; designing it at a lower bound is what makes its
    guarantee conservative, by the coupling argument in Decision 19.1.

    Parameters
    ----------
    failures
        The observed failure count ``f``. Must satisfy ``0 <= failures <
        observations``, the same domain as the upper bound's.
    observations
        The total observation count ``m``. Must be strictly positive.
    alpha
        The guarantee's own risk appetite -- ADR-013's ratified ``0.10``,
        shared with ``p_U`` (Decision 19.1 does not re-derive it).

    Returns
    -------
    float
        ``p_L``: exactly ``0.0`` when ``failures == 0`` (Decision 19.2 -- no
        improvement from zero exists to detect), otherwise strictly inside
        ``(0, failures / observations]``.

    Raises
    ------
    InvalidParameterError
        ``observations <= 0``, or ``failures`` is outside
        ``[0, observations)`` -- validated exactly as the upper bound does,
        so the two bounds accept the same inputs.
    """
    _require_valid_counts(failures=failures, observations=observations)
    if failures == 0:
        return 0.0
    # scipy.stats.beta.ppf has no type stub mypy can see (see above).
    return float(beta.ppf(alpha, failures, observations - failures + 1))


__all__ = ["clopper_pearson_lower_bound", "clopper_pearson_upper_bound"]
