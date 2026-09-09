Feature: Check whether the baseline has sufficient observations
  As a Python engineer building a quality baseline for my LLM agent
  I want to check whether my baseline has enough observations for
  reliable control limit fitting and learn exactly what is missing
  when it does not
  So that I do not fit limits from too little data and can plan my
  collection accordingly

  # -- Pending decisions --
  # The following open questions are not yet settled. These scenarios
  # are written to survive any resolution.
  #
  # [ASSUMPTION] MEDIUM: The sufficiency check should be advisory
  #   (reporting status) rather than enforcing (raising an error
  #   when insufficient). Scenarios assert that the check returns
  #   a result with readiness information. If the assumption is
  #   wrong and the check should raise on insufficient baselines,
  #   SC2, SC4, SC6, and SC10 would need rewriting.
  #   Owner: system-architect
  #
  # [ASSUMPTION] HIGH: The sufficiency check should include
  #   zero-variance detection alongside the count-based check,
  #   rather than deferring all data-quality concerns to fitting.
  #   SC7 asserts a data quality concern for all-identical scores.
  #   If the assumption is wrong, SC7 would be removed.
  #   Owner: system-architect
  #
  # [ASSUMPTION] MEDIUM: The sufficiency mechanism should support
  #   per-chart-type thresholds, with a single default threshold
  #   until BIN-92 provides evidence. SC8 asserts that a
  #   chart-type-specific threshold is respected when configured.
  #   If the assumption is wrong, SC8 would need rewriting.
  #   Owner: system-architect, BIN-92 (threshold values)
  #
  # OQ-1: Whether the sufficiency result should include a richer
  #   readiness assessment beyond count and variance (staleness,
  #   distribution shape, autocorrelation). Scenarios assert only
  #   count, threshold, gap, and zero-variance detection.
  #   Owner: system-architect
  #
  # OQ-2: Where the boundary sits between sufficiency checking
  #   (this story) and fitting-time validation (BIN-65/94/95).
  #   Scenarios test sufficiency only; fitting-time validation
  #   is BIN-65/94/95's concern.
  #   Owner: system-architect
  #
  # BIN-92 (SP-2): The minimum viable baseline size for LLM judge
  #   scores is unknown. No scenario names a specific threshold
  #   number. All scenarios reference "the configured minimum" or
  #   "the library default" abstractly.
  #
  # BIN-93 (SP-3): The bootstrapped MEWMA approach may lower the
  #   threshold or make it chart-type-dependent. Scenarios are
  #   neutral on threshold values and accommodate per-chart-type
  #   thresholds without requiring them.
  #
  # BIN-58 OQ-3: Whether criteria attach at the judge, the
  #   monitor, or per-call. Scenarios describe baselines by their
  #   content, not by a specific configuration point.
  #
  # BIN-63 OQ-3: Whether observations carry a timestamp or
  #   sequence index. Not relevant to sufficiency checking.
  #
  # BIN-63 OQ-4: Whether there is a maximum baseline size.
  #   Scenarios do not assert or assume any size limit.
  #
  # BIN-63 OQ-6: What mechanism compares criteria for equality.
  #   Not relevant to sufficiency checking.

  # --- Happy path (BR-1 happy, BR-4, BR-7) ---

  Scenario: Engineer checks a baseline that has enough observations for fitting control limits
    Given the engineer has a Phase I baseline with observations meeting or exceeding the required minimum
    When they check whether the baseline is sufficient for fitting control limits
    Then the result reports the baseline as sufficient
    And the result reports the current observation count
    And the result reports the minimum threshold that was applied

  # --- Sad path (BR-1 sad, BR-2) ---

  # When the baseline is insufficient, the engineer must learn the
  # gap -- not just "insufficient." An engineer who knows how many
  # more observations to collect is more likely to complete baseline
  # fitting than one who knows only "not enough."

  Scenario: Engineer checks a baseline that does not have enough observations
    Given the engineer has a Phase I baseline with fewer observations than the required minimum
    When they check whether the baseline is sufficient for fitting control limits
    Then the result reports the baseline as insufficient
    And the result reports the current observation count
    And the result reports the minimum threshold that was applied
    And the result reports how many more observations are needed to reach the minimum

  # --- Boundary: exactly at the minimum (BR-1 boundary) ---

  Scenario: Baseline with exactly the minimum number of observations is sufficient
    Given the engineer has a Phase I baseline with exactly the minimum required number of observations
    When they check whether the baseline is sufficient for fitting control limits
    Then the result reports the baseline as sufficient
    And the remaining observations needed is zero

  # --- Edge case: empty baseline (BR-2 edge) ---

  # An empty baseline is the extreme case of insufficiency. The
  # gap equals the full threshold.

  Scenario: Engineer checks an empty baseline for sufficiency
    Given the engineer has a Phase I baseline with no recorded observations
    When they check whether the baseline is sufficient for fitting control limits
    Then the result reports the baseline as insufficient
    And the result reports zero as the current observation count
    And the result reports the full minimum threshold as the number of observations still needed

  # --- Configurable threshold (BR-3 happy, BR-7) ---

  # The minimum threshold for reliable control limits depends on
  # the chart type and the score distribution. BIN-92 (SP-2) has
  # not resolved the threshold for LLM judge scores. BIN-93 (SP-3)
  # may change it further. The engineer can override the default
  # for their use case.

  Scenario: Engineer configures a custom minimum threshold for sufficiency
    Given the engineer has configured a specific minimum observation count for the sufficiency determination
    And they have a Phase I baseline with observations
    When they check whether the baseline is sufficient
    Then the determination uses the engineer's configured minimum rather than the library default
    And the result reports the configured minimum as the threshold that was applied

  # --- Temporal: freshness after recording (BR-1, BR-2) ---

  # The sufficiency result is computed from the baseline's current
  # state at the time of the check. It is not cached or stale.

  Scenario: Sufficiency result reflects additional observations recorded since the last check
    Given the engineer has previously checked a baseline and it was insufficient
    And they have since recorded additional observations into the baseline
    When they check the baseline for sufficiency again
    Then the result reports the updated observation count
    And the number of remaining observations needed has decreased accordingly

  # --- Data quality: zero-variance (A2) ---

  # An all-identical baseline produces a zero variance estimate.
  # Control limits collapse to the mean regardless of observation
  # count, making the chart unable to detect any deviation. This
  # is a degenerate case that a count-only check misses entirely.

  Scenario: Baseline meeting the count threshold but with zero score variance is flagged
    Given the engineer has a Phase I baseline meeting the minimum observation count
    But every observation in the baseline has an identical numeric score
    When they check whether the baseline is sufficient for fitting control limits
    Then the result indicates a data quality concern
    And the concern identifies that the scores show no variation

  # --- Per-chart-type threshold (BR-5 happy) ---

  # ADR-001 documents different ARL calibration methods per chart
  # type (EWMA, CUSUM, Shewhart). The minimum baseline size may
  # differ across chart types. The mechanism accommodates this
  # without forcing the engineer to specify a chart type for
  # every check.

  Scenario: Engineer requests sufficiency for a specific chart type and receives that type's threshold
    Given the engineer has configured distinct minimum thresholds for different chart types
    And they have a Phase I baseline with observations
    When they check whether the baseline is sufficient for a specific chart type
    Then the result reports the threshold configured for that chart type
    And the determination uses that chart type's threshold rather than the general default

  # --- Advisory nature: read-only inspection (BR-6) ---

  # The sufficiency check reports readiness but does not prevent
  # the engineer from proceeding. Whether fitting refuses an
  # insufficient baseline is BIN-65/94/95's concern. The check
  # does not modify the baseline in any way.

  Scenario: Sufficiency check does not modify the baseline
    Given the engineer has a Phase I baseline with recorded observations
    When they check whether the baseline is sufficient for fitting control limits
    Then the baseline contains the same number of observations as before the check
    And the observations in the baseline are unchanged

  # --- Boundary: just below the minimum (boundary analysis) ---

  Scenario: Baseline with one fewer observation than the minimum is insufficient
    Given the engineer has a Phase I baseline with one fewer observation than the configured minimum
    When they check whether the baseline is sufficient for fitting control limits
    Then the result reports the baseline as insufficient
    And the result reports that exactly one more observation is needed
