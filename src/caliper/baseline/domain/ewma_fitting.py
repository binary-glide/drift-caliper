"""``fit_ewma`` -- fit EWMA control limits from a Phase I baseline (BIN-65).

See ``docs/domain-model.md`` (Library Operations -- Fit EWMA) and
``docs/architecture/adr/004-fitted-artefact-protocol-and-fitting-api-surface.md``
section 5 for the fitting signature shape and parameter semantics, and
ADR-001/ADR-003 for the calibration method (Markov-chain approximation,
Lucas & Saccucci 1990).

Scaffold only: ``fit_ewma`` always raises ``NotImplementedError`` below, so
every test that calls it is red because behaviour is absent, not because a
name is missing -- mirroring the ``Baseline.check_sufficiency()`` scaffold
pattern from BIN-64 (``src/caliper/baseline/domain/baseline.py``). See the
function's own docstring for what ``domain-implementer`` must build,
including the primary-source verification obligation for every numerical
constant it pins (``CLAUDE.md``, "Fitting stories carry their own numerical
proof" -- ratified 2026-09-10).
"""

from __future__ import annotations

from caliper.baseline.domain.baseline import Baseline
from caliper.baseline.domain.fitted_ewma import FittedEWMA

# --- Smoothing parameter (lambda) valid range -------------------------------
#
# The EWMA statistic itself is defined for 0 < lambda <= 1 (Roberts 1959;
# Hunter 1986; Lucas & Saccucci 1990 Sec. 2): lambda=1 degenerates to a
# Shewhart individuals chart (only the most recent observation matters),
# lambda=0 is undefined (no weight ever falls on a new observation).
# MAX_SMOOTHING_PARAM = 1.0 follows directly from that closed upper bound.
#
# MIN_SMOOTHING_PARAM has no smallest element to inherit -- (0, 1] is open
# at zero -- so a library implementation must choose a concrete floor for
# its valid range. Placeholder value below; not verified from a primary
# source, unlike the (lambda, L, ARL0) triples in
# tests/unit/baseline/test_ewma_arl_published_values.py, which ARE.
#
# TODO (domain-implementer): confirm or replace both bounds when building
# the real validation, with a citation if one is available.
MIN_SMOOTHING_PARAM = 0.0001
MAX_SMOOTHING_PARAM = 1.0

# --- Library default smoothing parameter ------------------------------------
#
# ADR-004 section 5: "smoothing_param (EWMA) ... Optional. None uses library
# default" -- deliberately left unpinned by the ADR (ADR-001's "no numerical
# constants" discipline). Lucas & Saccucci (1990) discuss lambda in the
# interval [0.05, 0.25] as the commonly recommended range, but do not
# prescribe a single default value. Placeholder below.
#
# TODO (domain-implementer): confirm or replace, with citation.
DEFAULT_SMOOTHING_PARAM = 0.2

# --- False alarm tolerance (target ARL0) meaningful range -------------------
#
# ARL0 is an expected count of observations before a false alarm. No ADR
# pins a concrete floor or ceiling for what counts as "meaningful" -- an
# ARL0 at or below 1 has no useful interpretation (an alarm on essentially
# every observation), but the exact boundary is a library design choice,
# not a citable statistical constant. Placeholders below.
#
# TODO (domain-implementer): confirm or replace, with citation if one exists.
MIN_MEANINGFUL_ARL = 1.0
MAX_MEANINGFUL_ARL = 1_000_000.0


def fit_ewma(
    baseline: Baseline,
    *,
    target_arl: float | None = None,
    smoothing_param: float | None = None,
) -> FittedEWMA:
    """Fit EWMA control limits from ``baseline`` (BIN-65).

    Scaffold only -- always raises ``NotImplementedError`` below. See
    ``docs/domain-model.md`` and ADR-004 for what ``domain-implementer``
    must build:

    * ``target_arl`` is optional in the Python signature but required by
      Caliper's validation (ADR-004 section 5, closing ADR-002's open
      dependency): ``None`` raises ``InvalidParameterError`` with
      ``context["kind"] == "missing"`` and ``context["parameter"] ==
      "target_arl"`` -- not Python's ``TypeError``.
    * ``smoothing_param`` is genuinely optional: ``None`` uses
      ``DEFAULT_SMOOTHING_PARAM``.
    * Both parameters, when supplied, must lie within their valid/meaningful
      ranges (``MIN_SMOOTHING_PARAM``..``MAX_SMOOTHING_PARAM``,
      ``MIN_MEANINGFUL_ARL``..``MAX_MEANINGFUL_ARL``) or
      ``InvalidParameterError`` (``context["kind"] == "invalid"``) is
      raised.
    * Fitting enforces baseline sufficiency (BIN-65 A1/BR-1): an
      insufficient baseline raises ``InsufficientBaselineError``
      (``context["have"]``, ``context["need"]``). Whether this calls
      ``Baseline.check_sufficiency()`` internally or guards separately is
      open (OQ-3) -- callers, and tests, must not depend on the mechanism,
      only on the observable failure.
    * Fitting refuses a zero-variance baseline (BIN-65 A2/BR-2):
      ``DegenerateBaselineError`` (``context["reason"]``).
    * The calibration method (Markov-chain approximation, per
      ADR-001/ADR-003, Lucas & Saccucci 1990) must reproduce published
      ARL0 tables -- see
      ``tests/unit/baseline/test_ewma_arl_published_values.py``. Every
      numerical constant the implementation pins (any table lookup, the
      moving-range unbiasing constant d_2 feeding ``sigma_estimate``) must
      be verified against a primary source before being pinned -- see
      ``CLAUDE.md`` "Fitting stories carry their own numerical proof".

    Args:
        baseline: The Phase I baseline to fit from.
        target_arl: The target in-control ARL0 (false alarm tolerance).
            Optional in the signature, required by validation.
        smoothing_param: The EWMA smoothing parameter (lambda). ``None``
            uses the library default.

    Returns:
        A ``FittedEWMA`` artefact.

    Raises:
        NotImplementedError: Always, in this scaffold.
    """
    raise NotImplementedError(
        "fit_ewma is a BIN-65 scaffold -- domain-implementer builds the real "
        "Markov-chain calibration; see this function's docstring and "
        "docs/architecture/adr/004-fitted-artefact-protocol-and-fitting-api-surface.md"
    )
