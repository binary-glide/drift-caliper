Feature: Fit EWMA control limits from the baseline
  As a Python engineer who has collected and validated a Phase I baseline
  for my LLM agent
  I want to fit EWMA control limits with a stated false alarm tolerance
  So that my production monitoring has a quantifiable, auditable statistical
  basis and I can distinguish expected score variation from genuine quality
  drift

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
  #   causes the standard deviation estimate to be zero and control
  #   limits collapse to the centre line; every non-identical Phase II
  #   observation would signal.
  #   SC6 asserts refusal. If the assumption is wrong, SC6 would be
  #   removed or rewritten.
  #   Owner: system-architect
  #
  # [ASSUMPTION] A3 -- HIGH (false alarm tolerance) / MEDIUM (lambda):
  #   False alarm tolerance should be REQUIRED with no silent default.
  #   The smoothing parameter (lambda) should have a library default.
  #   SC9 covers the omitted false alarm tolerance case. SC4 covers
  #   the library default for lambda. If the assumption about false
  #   alarm tolerance is wrong (a default is acceptable), SC9 would
  #   be removed.
  #   Owner: system-architect
  #
  # [ASSUMPTION] A4 -- HIGH: The fitted artefact should report the
  #   ACHIEVED false alarm properties alongside the REQUESTED ones.
  #   Calibration is numerical (Markov-chain or equivalent); achieved
  #   may not exactly equal requested. SC1 asserts both are reported
  #   on the fitting result. If the assumption is wrong, the
  #   "achieved" assertions would be removed.
  #   Owner: system-architect
  #
  # OQ-1: API shape for specifying false alarm tolerance -- ARL0,
  #   false alarm rate (alpha), or both? Scenarios use the neutral
  #   term "false alarm tolerance" throughout, without committing to
  #   a specific parameterisation.
  #   Owner: system-architect
  #
  # OQ-2: Whether the fitted EWMA artefact shares a common base type
  #   or protocol with CUSUM (BIN-94) and Shewhart (BIN-95) artefacts.
  #   Scenarios specify only the EWMA-specific contract.
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
  # BIN-92 (SP-2): The minimum viable baseline size for LLM judge
  #   scores is unknown. No scenario names a specific observation
  #   count or sufficiency threshold. All scenarios reference "the
  #   sufficiency check" or "the sufficiency threshold" abstractly.
  #
  # BIN-93 (SP-3): The bootstrapped MEWMA approach may replace or
  #   supplement the Markov-chain calibration method. Scenarios assert
  #   that the calibration method is reported on the artefact but do
  #   not name a specific method.
  #
  # BIN-58 OQ-3: Whether criteria attach at the judge, the monitor,
  #   or per-call. Scenarios reference provenance carried through the
  #   baseline, not a specific attachment point.

  # --- Happy path: core fitting (BR-1 happy, BR-2 happy, BR-3 happy,
  #     BR-6 happy, BR-7, BR-8) ---

  Scenario: Engineer fits EWMA control limits from a sufficient baseline with a specified false alarm tolerance
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they fit EWMA control limits with a specified false alarm tolerance
    Then the result contains upper and lower control limits and a centre line
    And the result reports the smoothing parameter that was used
    And the result reports the false alarm tolerance that was requested
    And the result reports the false alarm tolerance that was achieved by the calibration
    And the result reports the calibration method that was used

  # --- Happy path: auditability (BR-7, BR-8, BR-9) ---

  # The fitted artefact is the audit record. An auditor must be able
  # to determine: what was fitted, from what data, with what parameters,
  # using what method, and what false alarm properties were achieved
  # versus what was requested. This scenario asserts the baseline
  # statistics and provenance half of that record.

  Scenario: Fitted EWMA artefact carries baseline statistics and provenance for auditability
    Given the engineer has fitted EWMA control limits from a Phase I baseline
    When they inspect the fitted artefact
    Then the artefact reports the baseline mean and variance used to compute the limits
    And the artefact reports the number of baseline observations the limits were fitted from
    And the artefact reports the judge model version from the baseline provenance
    And the artefact reports the scoring criteria from the baseline provenance

  # --- Happy path: custom smoothing parameter (BR-4 happy) ---

  Scenario: Engineer fits EWMA limits with a custom smoothing parameter
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they fit EWMA control limits with a specified false alarm tolerance and a custom smoothing parameter
    Then the result uses the engineer's specified smoothing parameter rather than the library default
    And the result reports the smoothing parameter that was used

  # --- Happy path: default smoothing parameter (BR-4 happy) ---

  Scenario: Engineer fits EWMA limits using the library default smoothing parameter
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they fit EWMA control limits with a specified false alarm tolerance without specifying a smoothing parameter
    Then the result uses the library's default smoothing parameter
    And the result reports which smoothing parameter was used

  # --- Sad path: insufficient baseline (BR-1 sad) ---

  # Fitting ENFORCES sufficiency (A1). The sufficiency check (BIN-64)
  # is advisory; fitting is where the damage from insufficient data
  # actually occurs -- confident-looking limits from too little data.

  Scenario: Fitting fails when the baseline does not meet the sufficiency threshold
    Given the engineer has a Phase I baseline that does not pass the sufficiency check
    When they attempt to fit EWMA control limits
    Then the fitting fails with an error classifiable as an insufficient baseline
    And the error reports how many observations the baseline has and how many are needed
    And the error guides the engineer to collect more observations before fitting

  # --- Sad path: zero-variance baseline (BR-2 sad) ---

  # Zero variance produces sigma of zero, control limits collapse to
  # the centre line, and every non-identical Phase II observation
  # signals. Degenerate limits are mathematically defined but
  # practically useless.

  Scenario: Fitting fails when the baseline has zero score variance
    Given the engineer has a Phase I baseline that passes the sufficiency count threshold
    But every observation in the baseline has an identical numeric score
    When they attempt to fit EWMA control limits
    Then the fitting fails with an error classifiable as a degenerate baseline
    And the error explains that EWMA control limits require score variation in the baseline
    And the error guides the engineer on what to do next

  # --- Sad path: invalid smoothing parameter (BR-5 sad) ---

  # Every configurable parameter needs its invalid-input path covered
  # (BIN-64 M1). The valid range is determined by the EWMA chart's
  # mathematical definition and verified from primary sources at
  # implementation time.

  Scenario Outline: Fitting fails when the smoothing parameter is <invalid case>
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they attempt to fit EWMA control limits with a smoothing parameter that is <invalid case>
    Then the fitting fails with an error classifiable as an invalid parameter
    And the error identifies which parameter is invalid and what the valid range is

    Examples:
      | invalid case                |
      | zero                        |
      | negative                    |
      | above the valid upper bound |

  # --- Sad path: invalid false alarm tolerance (BR-6 sad) ---

  # Same principle as BR-5. The meaningful range is determined by
  # the statistical definition and verified from primary sources.

  Scenario Outline: Fitting fails when the false alarm tolerance is <invalid case>
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they attempt to fit EWMA control limits with a false alarm tolerance that is <invalid case>
    Then the fitting fails with an error classifiable as an invalid parameter
    And the error identifies what was invalid about the false alarm tolerance and what values are acceptable

    Examples:
      | invalid case                |
      | zero                        |
      | negative                    |
      | outside the meaningful range |

  # --- Sad path: missing false alarm tolerance (BR-3 sad) ---

  # The false alarm tolerance is a statistical commitment the engineer
  # must own explicitly. Unlike the smoothing parameter (which has a
  # library default), a silently defaulted false alarm tolerance would
  # make an auditable commitment on the engineer's behalf without
  # their acknowledgement.

  Scenario: Fitting fails when no false alarm tolerance is specified
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they attempt to fit EWMA control limits without specifying a false alarm tolerance
    Then the fitting fails with an error indicating that a false alarm tolerance is required
    And no control limits are produced

  # --- Edge: error distinguishability (BR-11) ---

  # Fitting errors follow the BIN-59 pattern: programmatically
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

  # --- Edge: immutability (BR-10) ---

  # Consistent with BIN-63 BR-3 (observations are immutable) and
  # BIN-59 BR-3 (scoring results are immutable). The fitted artefact
  # is a historical record of what was computed.

  Scenario: The fitted EWMA artefact is immutable after creation
    Given the engineer has fitted EWMA control limits from a Phase I baseline
    When they attempt to modify the limits, parameters, baseline statistics, or provenance of the fitted artefact
    Then the modification is rejected
    And the artefact continues to report its original values

  # --- Boundary: smoothing parameter at valid range limits (BR-5 boundary) ---

  # Boundary value analysis: confirm that values at the edges of the
  # valid range are accepted, complementing the invalid-case scenarios
  # above which test just outside the range.

  Scenario Outline: Smoothing parameter at <boundary> produces fitted limits
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they fit EWMA control limits with a specified false alarm tolerance and a smoothing parameter at <boundary>
    Then the result contains upper and lower control limits and a centre line
    And the result reports the smoothing parameter that was used

    Examples:
      | boundary                 |
      | the smallest valid value |
      | the largest valid value  |

  # --- Boundary: false alarm tolerance at meaningful range limits (BR-6 boundary) ---

  Scenario Outline: False alarm tolerance at <boundary> produces fitted limits
    Given the engineer has a Phase I baseline that passes the sufficiency check
    And the baseline scores show non-zero variance
    When they fit EWMA control limits with a false alarm tolerance at <boundary>
    Then the result contains upper and lower control limits and a centre line
    And the result reports the false alarm tolerance that was requested
    And the result reports the false alarm tolerance that was achieved by the calibration

    Examples:
      | boundary                      |
      | the smallest meaningful value |
      | the largest meaningful value  |
