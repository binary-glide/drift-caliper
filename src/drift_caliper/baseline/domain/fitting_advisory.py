"""``FittingAdvisory`` -- a non-raising disclosure attached to a fitted artefact.

See ``docs/architecture/adr/011-minimum-meaningful-target-arl0.md``
("Consequences" -- "A shared advisory vehicle is now needed"). ADR-011
needs a way to tell an engineer their fitted chart's ``target_arl`` sits
below Caliper's own published-table verification coverage, without
refusing to fit it -- the maths is correct at that setting; only the
*evidence Caliper can point to* is thinner. ADR-005's own middle tier
(a baseline that clears the hard 100-observation floor but not the
target-dependent ``adequate()`` figure) needs the identical shape: a
disclosure that does not raise, attached to the result the engineer is
about to look at.

**Why this is not ``DataQualityConcern``.** That type already exists
(``drift_caliper.baseline.domain.data_quality_concern``), has the identical two
fields, and is produced by the identical operation
(``Baseline.check_sufficiency()``) one of this type's two callers will
attach to. Reusing it verbatim was considered and rejected: its name and
its one existing use (BIN-64's zero-variance flag) are both about a
property of the *data* -- something about the recorded observations
themselves is suspect. Neither of this type's two callers is that. ADR-011's
disclosure is about a *choice the engineer made* (a ``target_arl`` outside
the range any test oracle in this repository covers) -- the data could be
pristine. ADR-005's middle tier is about *how much* data there is relative
to a target, not about a defect *in* what was collected. Calling either one
a "data quality concern" would mislabel the actual claim being made, which
matters here specifically: ``CLAUDE.md``'s DX rule is that errors (and, by
the same logic, non-raising disclosures) exist to be branched on without
parsing prose -- a caller who filters ``if concern.kind == "zero_variance"``
should not also have to filter out concerns that were never about data
quality at all when they only care about the data-quality ones.

**Why the fields are identical to ``DataQualityConcern`` anyway.** ``kind``
(a short, semi-open discriminator string) plus ``description`` (a
human-readable sentence) is the same shape ADR-002 already uses for every
error's ``context`` -- and both of this type's callers need exactly that:
something a caller can either branch on (``kind``) or print/log
(``description``), nothing more structured. Two callers needing the same
two fields is the DRY case for sharing a *type*; it is not, on its own, a
reason the type should be the *same* type as one already named for a
narrower concept.

**Field shape mirrors ``DataQualityConcern`` deliberately** -- see that
type's own module docstring; frozen, equality by value, no validators
beyond field presence (nothing about "is this target_arl too low" needs
re-validating once the tier decision has already been made by whichever
fitting function constructs one).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FittingAdvisory(BaseModel):
    """A single non-raising disclosure about a fitting or sufficiency operation.

    Distinct from
    :class:`~drift_caliper.baseline.domain.data_quality_concern.DataQualityConcern`
    -- see the module docstring for why a data-quality-named type would
    misdescribe both of this type's intended uses. Immutable; equality by
    value.

    Two current/planned callers (see ADR-011's "Consequences" section):

    - ``fit_ewma``/``fit_cusum``/``fit_shewhart`` attach one when
      ``target_arl`` is inside ADR-011's flagged tier (``100 <= target_arl
      < 370``) -- ``kind == "target_arl_below_verified_range"``.
    - ``Baseline.check_sufficiency()`` is the second intended caller, for
      ADR-005's own middle tier (a baseline above the hard floor but below
      the target-dependent ``adequate()`` figure) -- **not implemented by
      this change**; ``adequate()`` itself remains unratified. Recorded here
      so a future implementation reuses this type rather than inventing a
      parallel one, per ADR-011's "one vehicle, two users" instruction.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    description: str
    boundary: float
