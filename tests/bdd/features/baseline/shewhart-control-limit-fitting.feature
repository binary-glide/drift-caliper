Feature: Fit Shewhart I-chart control limits from the baseline
  As a Python engineer who has collected and validated a Phase I baseline
  for my LLM agent
  I want to fit Shewhart I-chart control limits with a stated false alarm
  tolerance
  So that my production monitoring can detect acute quality failures -- on
  the observation that produces them -- with a quantifiable, auditable
  statistical basis

  # -- Pending decisions --
  # The following assumptions and open questions are not yet settled.
  # These scenarios are written to survive any resolution.
  #
  # [ASSUMPTION] A1 -- HIGH: Fitting should ENFORCE baseline sufficiency
  #   rather than allowing fitting from an insufficient baseline with a
  #   warning. This resolves BIN-64's OQ-2: the sufficiency check
  #   (BIN-64) is advisory; fitting (this story) is where enforcement
  #   occurs. Reasoning: the check is an information query that harms
  #   nothing if ignored; fitting from insufficient data is where harm
  #   actually occurs -- confident-looking limits that are statistically
  #   unreliable.
  #   SC5 asserts enforcement. If the assumption is wrong and fitting
  #   should warn rather than refuse, SC5 would need rewriting.
  #   Owner: system-architect
  #
  # [ASSUMPTION] A2 -- HIGH: Fitting should REFUSE a zero-variance
  #   baseline rather than producing degenerate limits. Zero variance
  #   causes all consecutive-observation differences to be zero, the
  #   moving-range average to be zero, the sigma estimate to be zero,
  #   and control limits to collapse to the centre line. Every
  #   non-identical Phase II observation would signal. The degenerate
  #   case is starker than for EWMA or CUSUM because there is no
  #   smoothing or accumulation -- the very first non-identical
  #   observation trips the collapsed limits.
  #   SC6 asserts refusal. If the assumption is wrong, SC6 would be
  #   removed or rewritten.
  #   Owner: system-architect
  #
  # [ASSUMPTION] A3 -- HIGH: False alarm tolerance should be REQUIRED
  #   with no silent default. Unlike EWMA (which has an independent
  #   smoothing parameter) or CUSUM (which has an independent reference
  #   value), the I-chart has no separate tuning parameter -- the sigma
  #   multiplier is entirely determined by the false alarm tolerance
  #   (A5). The engineer controls one quantity; the library computes
  #   everything else. This is a genuine API simplification, not a gap.
  #   SC8 covers the omitted false alarm tolerance case. If the
  #   assumption is wrong (a default is acceptable), SC8 would be
  #   removed.
  #   Owner: system-architect
  #
  # [ASSUMPTION] A4 -- HIGH for consistency, MEDIUM in isolation: The
  #   fitted artefact should report the ACHIEVED false alarm properties
  #   alongside the REQUESTED ones. Under the normality assumption the
  #   I-chart's mapping is exact (no Markov-chain discretisation, no
  #   diffusion approximation), so achieved and requested may be
  #   identical. The field should still exist for consistency with
  #   siblings and to support future refinement if sigma estimation
  #   uncertainty is accounted for.
  #   SC1 asserts both are reported. If the assumption is wrong, the
  #   "achieved" assertions would be removed.
  #   Owner: system-architect
  #
  # [ASSUMPTION] A5 -- HIGH: The sigma multiplier should be DERIVED
  #   from the false alarm tolerance, not specified independently by
  #   the engineer. For a given distributional assumption, the false
  #   alarm tolerance uniquely determines the sigma multiplier. Allowing
  #   independent specification invites contradictory configurations --
  #   an artefact whose claimed false alarm rate does not match its
  #   actual properties.
  #   SC1 asserts the sigma multiplier is present on the artefact as
  #   a derived, reported value. No scenario allows the engineer to
  #   specify the sigma multiplier directly. If the assumption is
  #   wrong, a new scenario for engineer-specified sigma multiplier
  #   would be needed.
  #   Owner: system-architect
  #
  # OQ-1: API shape for specifying false alarm tolerance -- ARL0,
  #   false alarm rate (alpha), or both? Scenarios use the neutral
  #   term "false alarm tolerance" throughout, without committing to
  #   a specific parameterisation.
  #   Owner: system-architect
  #
  # OQ-2: Whether the fitted I-chart artefact shares a common base
  #   type or protocol with EWMA (BIN-65) and CUSUM (BIN-94)
  #   artefacts. The I-chart is the simplest case -- fewest
  #   chart-specific fields (sigma estimate and sigma multiplier
  #   only) -- making it a natural anchor for the common subset.
  #   Scenarios specify only the I-chart-specific contract.
  #   Owner: system-architect
  #
  # OQ-3: Whether fitting calls the sufficiency check (BIN-64)
  #   internally or the engineer calls it separately before fitting.
  #   Both designs satisfy BR-1. Scenarios assert that fitting from
  #   an insufficient baseline fails; they do not prescribe whether
  #   the failure comes from an internal call or a separate guard.
  #   Owner: system-architect
  #
  # OQ-4: Whether the engineer can override sufficiency enforcement
  #   for testing or exploratory fitting. If A1 is accepted, an
  #   explicit override mechanism would preserve the guard rail for
  #   production use while allowing exploratory work. Scenarios do
  #   not assert or assume any override mechanism.
  #   Owner: system-architect
  #
  # OQ-5 (I-chart specific): Whether the moving-range span should
  #   be configurable or fixed at the conventional value. PRD
  #   recommends fixed for R1. The unbiasing constant is coupled to
  #   the span -- changing one without the other silently invalidates
  #   the limits. No scenario configures the span. If OQ-5 resolves
  #   to configurable, new scenarios would be needed for span
  #   validation and the span reported on the artefact.
  #   Owner: system-architect
  #
  # BIN-92 (SP-2): The minimum viable baseline size for LLM judge
  #   scores is unknown. No scenario names a specific observation
  #   count or sufficiency threshold. All scenarios reference "the
  #   sufficiency check" or "the sufficiency threshold" abstractly.
  #
  # BIN-93 (SP-3): The bootstrapped MEWMA approach may replace or
  #   supplement the Markov-chain calibration method. Scenarios assert
  #   that the calibration method is reported on the artefact but do
  #   not name a specific method. The I-chart's calibration is
  #   algebraically exact under normality, so BIN-93 affects it less
  #   than EWMA or CUSUM.

  # --- Happy path: core fitting (BR-1 happy, BR-3 happy, BR-5 happy,
  #     BR-9 happy, BR-10 happy) ---

  Scenario: Engineer fits I-chart control limits from a sufficient baseline with a specified false alarm tolerance
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they fit Shewhart I-chart control limits with a specified false alarm tolerance
    Then the result contains upper and lower control limits and a centre line
    And the result reports the sigma estimate derived from the baseline
    And the result reports the sigma multiplier used to derive the control limits
    And the result reports the false alarm tolerance that was requested
    And the result reports the false alarm tolerance that was achieved by the calibration
    And the result reports the calibration method that was used

  # --- Happy path: auditability (BR-9 happy, BR-10 happy, BR-11 happy) ---

  # The fitted artefact is the audit record. An auditor must be able
  # to determine: what was fitted, from what data, using what method,
  # and what false alarm properties were achieved versus what was
  # requested. This scenario asserts the baseline statistics and
  # provenance half of that record.

  Scenario: Fitted I-chart artefact carries baseline statistics and provenance for auditability
    Given the engineer has fitted Shewhart I-chart control limits from a Phase I baseline
    When they inspect the fitted artefact
    Then the artefact reports the baseline mean and the sigma estimate used to compute the limits
    And the artefact reports the number of baseline observations the limits were fitted from
    And the artefact reports the judge model version from the baseline provenance
    And the artefact reports the scoring criteria from the baseline provenance

  # --- Happy path: sigma estimation method (BR-6 happy) ---

  # Sigma is estimated from the average moving range of consecutive
  # observations, not from the sample standard deviation. This is
  # load-bearing: the moving range is robust to slow drift within the
  # baseline, producing different (and more appropriate) limits when
  # the baseline is not perfectly stationary. The artefact must report
  # the estimation method so an auditor can verify the limits against
  # the correct reference.

  Scenario: The sigma estimate is derived from the moving range of consecutive observations
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they fit Shewhart I-chart control limits with a specified false alarm tolerance
    Then the fitted artefact reports that sigma was estimated using the moving-range method

  # --- Happy path: observation order dependency (BR-7 happy) ---

  # BIN-63 BR-2 guarantees insertion order is preserved. This is the
  # first story where that guarantee matters for the arithmetic, not
  # just for chart sequencing. Reordering the same observations
  # produces different consecutive differences, a different moving
  # range, a different sigma estimate, and therefore different limits.

  Scenario: Observation order in the baseline affects the fitted control limits
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they fit Shewhart I-chart control limits from the baseline in its original observation order
    Then the control limits reflect the consecutive-observation differences in that order
    And fitting the same scores in a different order would produce different limits

  # --- Sad path: insufficient baseline (BR-1 sad) ---

  # Fitting ENFORCES sufficiency (A1). The sufficiency check (BIN-64)
  # is advisory; fitting is where the damage from insufficient data
  # actually occurs -- confident-looking limits from too little data.

  Scenario: Fitting fails when the baseline does not meet the sufficiency threshold
    Given the engineer has a Phase I baseline that does not pass the sufficiency check
    When they attempt to fit Shewhart I-chart control limits
    Then the fitting fails with an error classifiable as an insufficient baseline
    And the error reports how many observations the baseline has and how many are needed
    And the error carries recovery guidance to collect more observations before fitting

  # --- Sad path: zero-variance baseline (BR-2 sad) ---

  # Zero variance causes all consecutive differences to be zero, the
  # moving-range average to be zero, the sigma estimate to be zero,
  # and control limits to collapse to the centre line. The degenerate
  # case is starker than for EWMA or CUSUM because there is no
  # smoothing or accumulation -- the very first non-identical
  # observation trips the collapsed limits.

  Scenario: Fitting fails when the baseline has zero score variance
    Given the engineer has a Phase I baseline that passes the sufficiency count threshold
    But every observation in the baseline has an identical numeric score
    When they attempt to fit Shewhart I-chart control limits
    Then the fitting fails with an error classifiable as a degenerate baseline
    And the error explains that I-chart control limits require score variation in the baseline
    And the error carries recovery guidance for addressing the zero-variance condition

  # --- Sad path: invalid false alarm tolerance (BR-4 sad) ---

  # Every configurable parameter needs its invalid-input path covered
  # (BIN-64 M1 lesson). The I-chart has fewer parameters than its
  # siblings (no smoothing parameter, no reference value, no direction),
  # which makes complete coverage easier, not less necessary.

  Scenario Outline: Fitting fails when the false alarm tolerance is <invalid case>
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they attempt to fit Shewhart I-chart control limits with a false alarm tolerance that is <invalid case>
    Then the fitting fails with an error classifiable as an invalid parameter
    And the error identifies what was invalid about the false alarm tolerance and what values are acceptable

    Examples:
      | invalid case                 |
      | zero                         |
      | negative                     |
      | outside the meaningful range |

  # --- Sad path: missing false alarm tolerance (BR-3 sad) ---

  # The false alarm tolerance is the I-chart's only engineer-specified
  # parameter. A silently defaulted false alarm tolerance would make
  # an auditable commitment on the engineer's behalf without their
  # acknowledgement. This is the same principle as EWMA and CUSUM,
  # but here it is the only input path -- there is nothing else to
  # configure.

  Scenario: Fitting fails when no false alarm tolerance is specified
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they attempt to fit Shewhart I-chart control limits without specifying a false alarm tolerance
    Then the fitting fails with an error classifiable as an invalid parameter
    And the error identifies that a false alarm tolerance parameter is required
    And no control limits are produced

  # --- Edge: error distinguishability (BR-13) ---

  # Fitting errors follow the ADR-002 pattern: programmatically
  # classifiable by category, with recovery guidance distinct per
  # category. Assertions are on category classification, not on
  # message substrings.

  Scenario: Fitting errors are distinguishable by category with distinct recovery guidance
    Given a fitting attempt has failed with an insufficient baseline error
    And a separate fitting attempt has failed with a degenerate baseline error
    And a third fitting attempt has failed with an invalid parameter error
    When the engineer compares the three errors
    Then each is classifiable under a different category without inspecting the error message text
    And the recovery guidance for each category is distinct from the others

  # --- Edge: immutability (BR-12) ---

  # Consistent with BIN-63 BR-3 (observations are immutable) and
  # BIN-59 BR-3 (scoring results are immutable). The fitted artefact
  # is a historical record of what was computed.

  Scenario: The fitted I-chart artefact is immutable after creation
    Given the engineer has fitted Shewhart I-chart control limits from a Phase I baseline
    When they attempt to modify the limits, parameters, baseline statistics, or provenance of the fitted artefact
    Then the modification is rejected
    And the artefact continues to report its original values

  # --- Boundary: false alarm tolerance at meaningful range limits (BR-4 boundary) ---

  Scenario Outline: False alarm tolerance at <boundary> produces fitted limits
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they fit Shewhart I-chart control limits with a false alarm tolerance at <boundary>
    Then the result contains upper and lower control limits and a centre line
    And the result reports the false alarm tolerance that was requested
    And the result reports the false alarm tolerance that was achieved by the calibration

    Examples:
      | boundary                      |
      | the smallest meaningful value |
      | the largest meaningful value  |
