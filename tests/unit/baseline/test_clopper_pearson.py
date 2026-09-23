"""Numeric proof for the Clopper-Pearson upper confidence bound (ADR-013 section 1).

Verifies ``drift_caliper.baseline.domain.clopper_pearson.clopper_pearson_upper_bound``
-- the ``p_U`` construction Guaranteed In-Control Performance (GICP) designs
every Bernoulli CUSUM chart against, in place of the plain point estimate
``p_hat = f / m`` (ADR-013 section 1).

Citation
--------
ADR-013 section 1 states the formula in exactly the form tested here::

    p_U(f, m, alpha) = quantile function of Beta(f+1, m-f) at 1-alpha  (f < m)
    p_U(0, m, alpha) = 1 - alpha**(1/m)                    (closed form, f=0)

and records an independent check already performed on this ticket: *"the
closed form, 1 - alpha**(1/m), was independently checked against
scipy.stats.beta and matches to five decimal places (p_U(f=0, m=100,
alpha=0.05) = 0.02951)"*. This test file is that same style of check, made
permanent and automated rather than a one-off session verification.

``scipy.stats.beta.ppf`` is the SAME library ADR-013's own check used --
the point of this file is not to invent a third method, but to pin the
*exact* formula ADR-013 ratified against the exact tool it names, so a
future change to the implementation (a different quantile approximation, a
transposed argument order) is caught rather than silently accepted.
"""

from __future__ import annotations

import math

import pytest
from drift_caliper.baseline.domain.clopper_pearson import (  # type: ignore[import-not-found]  # ty: ignore[unresolved-import]
    clopper_pearson_upper_bound,
)
from scipy.stats import beta  # type: ignore[attr-defined]

from drift_caliper.errors import InvalidParameterError

_ALPHA = 0.10  # ADR-013's ratified default -- see module docstring.


class TestClopperPearsonAgainstScipy:
    """Pins the general (f >= 1) formula against ``scipy.stats.beta.ppf`` directly."""

    @pytest.mark.parametrize(
        ("failures", "observations", "alpha"),
        [
            (5, 100, 0.10),
            (1, 100, 0.05),
            (50, 100, 0.10),
            (99, 100, 0.10),
            (10, 500, 0.10),
        ],
    )
    def test_matches_beta_ppf_exactly(
        self, failures: int, observations: int, alpha: float
    ) -> None:
        expected = beta.ppf(1 - alpha, failures + 1, observations - failures)
        actual = clopper_pearson_upper_bound(
            failures=failures, observations=observations, alpha=alpha
        )
        assert actual == pytest.approx(expected, rel=1e-12)


class TestClopperPearsonClosedFormAtZeroFailures:
    """Pins the ``f=0`` closed form ADR-013 states directly, to five decimal places.

    ADR-013 section 1's own worked figure:
    ``p_U(f=0, m=100, alpha=0.05) = 0.02951``.
    """

    def test_reproduces_adr_013s_worked_figure(self) -> None:
        p_u = clopper_pearson_upper_bound(failures=0, observations=100, alpha=0.05)
        assert p_u == pytest.approx(0.02951, abs=1e-5)

    @pytest.mark.parametrize(
        ("observations", "alpha"),
        [(100, 0.10), (100, 0.05), (500, 0.10), (1000, 0.10)],
    )
    def test_closed_form_matches_the_general_beta_formula(
        self, observations: int, alpha: float
    ) -> None:
        """``1 - alpha**(1/m)`` must equal ``Beta(1, m).ppf(1 - alpha)`` -- same
        distribution.

        At ``f=0``, ``Beta(f+1, m-f) == Beta(1, m)``, whose CDF has the
        closed form ``F(x) = 1 - (1-x)**m``, so
        ``ppf(1-alpha) = 1 - alpha**(1/m)`` algebraically. Verified here
        against scipy's own general beta quantile rather than assumed.
        """
        via_closed_form = clopper_pearson_upper_bound(
            failures=0, observations=observations, alpha=alpha
        )
        via_beta_ppf = beta.ppf(1 - alpha, 1, observations)
        assert via_closed_form == pytest.approx(via_beta_ppf, rel=1e-9)


class TestClopperPearsonProperties:
    """Structural properties GICP's design depends on (ADR-013 section 6b)."""

    @pytest.mark.parametrize("failures", [0, 1, 10, 50, 99])
    def test_p_u_always_at_or_above_the_point_estimate(self, failures: int) -> None:
        """``p_U >= p_hat`` always -- ADR-013 section 5's `p_hat=1` reasoning depends on
        this."""
        observations = 100
        p_hat = failures / observations
        p_u = clopper_pearson_upper_bound(
            failures=failures, observations=observations, alpha=_ALPHA
        )
        assert p_u >= p_hat

    def test_p_u_is_strictly_positive_even_at_zero_failures(self) -> None:
        """ADR-013 section 5: `p_U(0, m, alpha)` is well-defined and strictly
        positive."""
        p_u = clopper_pearson_upper_bound(failures=0, observations=100, alpha=_ALPHA)
        assert math.isfinite(p_u)
        assert p_u > 0.0

    def test_p_u_decreases_as_observations_grow_at_a_fixed_rate(self) -> None:
        """More data at the same observed rate should tighten the confidence bound."""
        small = clopper_pearson_upper_bound(failures=5, observations=100, alpha=_ALPHA)
        large = clopper_pearson_upper_bound(
            failures=50, observations=1000, alpha=_ALPHA
        )
        assert large < small

    def test_p_u_decreases_as_alpha_grows(self) -> None:
        """`alpha -> 1` collapses `p_U` onto `p_hat` (ADR-013 section 3)."""
        tight = clopper_pearson_upper_bound(failures=10, observations=100, alpha=0.5)
        loose = clopper_pearson_upper_bound(failures=10, observations=100, alpha=0.01)
        assert tight < loose


class TestClopperPearsonRejectsInvalidInput:
    """Boundary-value coverage (ADR-002/ADR-008: type + context keys, never message
    text)."""

    def test_raises_when_failures_equals_observations(self) -> None:
        """`f == m` (all-failed) has no defined Beta(f+1, m-f) -- m-f would be 0."""
        with pytest.raises(InvalidParameterError) as excinfo:
            clopper_pearson_upper_bound(failures=100, observations=100, alpha=_ALPHA)
        assert excinfo.value.category == "invalid_parameter"

    def test_raises_when_failures_exceeds_observations(self) -> None:
        with pytest.raises(InvalidParameterError) as excinfo:
            clopper_pearson_upper_bound(failures=101, observations=100, alpha=_ALPHA)
        assert excinfo.value.category == "invalid_parameter"

    def test_raises_when_observations_is_zero(self) -> None:
        with pytest.raises(InvalidParameterError) as excinfo:
            clopper_pearson_upper_bound(failures=0, observations=0, alpha=_ALPHA)
        assert excinfo.value.category == "invalid_parameter"
