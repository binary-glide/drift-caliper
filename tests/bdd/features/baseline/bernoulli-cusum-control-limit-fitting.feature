Feature: Fit a Bernoulli CUSUM chart from a binary pass/fail rubric baseline
  As a Python engineer whose rubric returns a binary pass/fail judgement
  I want to fit a control chart calibrated for my rubric's failure rate,
  with protection against a stale or mismatched judge once I start
  monitoring
  So that I get a false-alarm rate I can trust for binary data, instead of
  either monitoring nothing or hand-rolling an unverified aggregation
  outside the library

  # -- Governing decisions (ratified, superseding the PRD where they differ) --
  #
  # [RATIFIED 2026-09-16, ADR-012] Only the Bernoulli CUSUM ships in this
  #   release. The Bernoulli EWMA is deferred -- its statistic has no
  #   finite reachable lattice and needs its own accuracy argument before
  #   it can be verified. No scenario below assumes or names a second
  #   binary chart.
  #
  # [RATIFIED 2026-09-16, ADR-012 amendment] Sign convention: a binary
  #   observation is higher-is-better, exactly like every other Caliper
  #   score. Every scenario below describes outcomes as "passed" or
  #   "failed" and never by numeric encoding, so the convention cannot be
  #   violated by wording here. Caliper cannot detect an engineer who has
  #   encoded a rubric the wrong way round -- ADR-012's amendment states
  #   that failure mode is silent by construction -- so there is no
  #   observable behaviour to specify for it, and no scenario attempts to.
  #
  # [RATIFIED 2026-09-16, ADR-012 amendment] The chart is two-sided by
  #   default -- it also watches for a failure rate that has FALLEN,
  #   which under Caliper's convention means the process improved and the
  #   baseline may be stale. Configurable to one-sided.
  #   ⚠️ Flagging a direct conflict for requirements-reviewer and the
  #   product owner rather than resolving it silently: ADR-013 §8
  #   (2026-09-23) describes this same question as still "open, now
  #   unblocked, not yet acted on," which reads as incompatible with
  #   ADR-012's own amendment header ("ratified by the product owner"),
  #   its decision list, and the 2026-09-17 commit message that merged it
  #   ("sign convention, two-sided default, primacy reopened, g-chart
  #   rejected"). The two scenarios below follow ADR-012's explicit
  #   decision text, since it is the more specific, more detailed
  #   ratification on this exact point and nothing has formally reversed
  #   it -- but this should be confirmed, not assumed, before
  #   architecture relies on it.
  #
  # [RATIFIED 2026-09-23, ADR-013 §5] A baseline with no observed failures
  #   is no longer refused -- CONTINGENT on the detection-performance
  #   disclosure (below) shipping in the same release. The scenario for
  #   this case asserts both the successful fit AND the disclosure
  #   together, so neither can ship without the other and still pass.
  #
  # [RATIFIED 2026-09-23, ADR-013 §5] A baseline where every judgement
  #   failed is still refused, but its error is now classifiable under
  #   the SAME category as an unachievable detection sensitivity -- not
  #   as a degenerate baseline, which is what the PRD originally
  #   specified and what the all-passed case also used to share. GICP
  #   folds this case into the existing "design point is not a valid
  #   probability" path rather than needing a bespoke branch. One
  #   consequence worth flagging plainly: as ratified, no scenario in
  #   this file reaches a "degenerate baseline" classification at all --
  #   both cases the PRD described that way have moved elsewhere.
  #
  # [RATIFIED 2026-09-23, ADR-013 §2] ADR-005's absolute baseline-size
  #   floor governs binary charts too, unchanged. The PRD-era provisional
  #   uniform floor (measured, and explicitly named provisional, on
  #   2026-09-17) is superseded and does not appear here.
  #
  # [RATIFIED 2026-09-23, ADR-013 §4] A fitted chart reports a detection
  #   performance figure alongside its false-alarm figure, so an engineer
  #   is never left reading only the reassuring half of the artefact.
  #
  # [RATIFIED 2026-09-23, ADR-013 §6b / BIN-122] The largest detection
  #   sensitivity an error reports must itself be accepted if resupplied.
  #   Tested directly below as a round-trip.
  #
  # -- Decision made while writing these scenarios --
  #
  # [DECIDED] PRD OQ-5 -- what happens when a Phase II observation checked
  #   against a binary-fitted chart is not exactly a pass or a fail. No
  #   scenario is written for this here. Applying the project's own test
  #   ("would the question still exist in a language with a different
  #   type system?"): a binary-fitted chart describes a two-outcome
  #   process, and no ADR has yet given Phase II binary observations
  #   their own declared shape (ADR-012's own OQ-4/scope note leaves this
  #   open) -- today such an observation is the same unconstrained float
  #   every other Caliper score is. A language with a real two-valued
  #   type for this data could not construct the malformed input at all;
  #   the question exists because of a gap in the current API surface,
  #   not because of a capability Caliper does or doesn't promise. That
  #   is exactly the shape the project's ratified rule ("type-boundary
  #   defects do not need a scenario") already exempts. This belongs to
  #   domain-implementer's unit tests and the exception-contract registry
  #   once system-architect fixes the Phase II input contract for binary
  #   charts -- not to this file.
  #
  # -- Still open, not settled by any ADR (carried from the PRD or ADR-013) --
  #
  # OQ-A (PRD OQ-2 / ADR-013 §8): whether ADR-011's target_arl tiers
  #   (hard floor, advisory band, clean) apply unchanged to an exact,
  #   non-tabulated oracle. No scenario below names a target_arl tier
  #   boundary for that reason.
  # OQ-B (ADR-013 §4): the exact reported field name for the
  #   detection-performance figure is not ratified. Scenarios describe it
  #   by what it tells the engineer, never by field name.
  # OQ-C (ADR-013 §8): the lattice denominator, and the sensitivity of the
  #   ratified false-alarm risk appetite to the detection-multiple
  #   parameter, are implementation detail, not behaviour -- no scenario
  #   depends on either.
  # OQ-D (ADR-012's own scope note / BIN-61): whether a binary observation
  #   is declared as its own kind on the baseline, or simply inferred at
  #   fit time from pass/fail-valued data. No scenario below assumes a
  #   declared kind -- "a baseline of pass/fail judgements" is used
  #   throughout regardless of how that is eventually represented.

  # === Story 1: fit a calibrated chart from a binary-rubric baseline ===

  Scenario: Fitting succeeds from a baseline with a genuine mix of passes and failures
    Given a Phase I baseline of pass/fail judgements whose failure rate is
      neither zero nor total, with enough observations to meet the minimum
      Caliper requires for binary data
    When the engineer fits a chart requesting a specific false-alarm
      tolerance
    Then they receive a fitted chart reporting a false-alarm rate that
      matches their request to within the chart's stated tolerance
    And the fitted chart reports the failure rate it is tuned to detect a
      rise from
    And the fitted chart reports how quickly it is expected to catch the
      degradation it is tuned to detect

  Scenario: Fitting succeeds when the baseline has exactly the minimum number of observations Caliper requires for binary data
    Given a Phase I baseline of pass/fail judgements whose failure rate is
      neither zero nor total, with exactly the minimum number of
      observations Caliper requires for binary data
    When the engineer fits a chart requesting a specific false-alarm
      tolerance
    Then they receive a fitted chart reporting a false-alarm rate that
      matches their request to within the chart's stated tolerance

  Scenario: Fitting is refused when the baseline has too few observations
    Given a Phase I baseline of pass/fail judgements below the minimum
      Caliper requires for binary data
    When the engineer attempts to fit a chart
    Then the fitting fails with an error classifiable as an insufficient
      baseline
    And the error reports how many observations the baseline has and how
      many more that minimum requires
    And no control limits are produced

  Scenario: Fitting succeeds from a baseline where every judgement passed, and discloses its detection weakness
    Given a Phase I baseline of pass/fail judgements where every judgement
      passed, with enough observations to meet the minimum Caliper requires
      for binary data
    When the engineer fits a chart requesting a specific false-alarm
      tolerance
    Then they receive a fitted chart reporting a false-alarm rate that
      matches their request to within the chart's stated tolerance
    And the fitted chart reports how quickly it is expected to catch a
      failure rate rising from a baseline that showed no failures at all

  Scenario: Fitting is refused when every judgement in the baseline failed
    Given a Phase I baseline where every recorded judgement failed, with
      enough observations to meet the minimum Caliper requires for binary
      data
    When the engineer attempts to fit a chart
    Then the fitting fails with an error classifiable as an invalid
      parameter
    And the error explains that no valid detection design exists for a
      baseline with no passing judgements
    And no control limits are produced

  Scenario: Fitted Bernoulli CUSUM artefact carries baseline statistics and provenance for auditability
    Given the engineer has fitted a Bernoulli CUSUM chart from a Phase I
      baseline
    When they inspect the fitted artefact
    Then the artefact reports the observed failure rate and the number of
      baseline observations the chart was fitted from
    And the artefact reports the judge model version from the baseline
      provenance
    And the artefact reports the scoring criteria from the baseline
      provenance

  Scenario: The fitted Bernoulli CUSUM artefact is immutable after creation
    Given the engineer has fitted a Bernoulli CUSUM chart from a Phase I
      baseline
    When they attempt to modify the limits, parameters, baseline statistics,
      or provenance of the fitted artefact
    Then the modification is rejected
    And the artefact continues to report its original values

  # === Story 2: a working default without learning control-chart theory ===

  Scenario: Fitting without specifying a detection sensitivity uses the documented default
    Given a sufficient Phase I baseline of pass/fail judgements
    When the engineer fits a chart without specifying how large a rise in
      the failure rate to watch for
    Then they receive a fitted chart tuned to a documented default rise in
      the failure rate
    And the fitted chart reports what that rise is

  Scenario: The engineer requests a chart tuned to a specific degradation size
    Given a sufficient Phase I baseline of pass/fail judgements
    When the engineer fits a chart specifying how large a rise in the
      failure rate to watch for, expressed as a multiple of their own
      baseline's failure rate
    Then they receive a fitted chart tuned to that degradation
    And the fitted chart reports the same kind of false-alarm-rate
      guarantee as the default case

  Scenario: Fitting is refused when the requested sensitivity is not achievable
    Given a sufficient Phase I baseline of pass/fail judgements
    When the engineer requests a detection sensitivity so large that the
      failure rate it implies is no longer a valid probability
    Then the fitting fails with an error classifiable as an invalid
      parameter
    And the error reports the largest sensitivity their baseline's failure
      rate can support
    And no control limits are produced

  Scenario: The largest sensitivity reported by the error is itself accepted
    Given a fitting attempt was refused because the requested detection
      sensitivity was not achievable for the baseline's failure rate
    When the engineer fits a chart requesting exactly the largest
      sensitivity that the error reported, against the same baseline
    Then they receive a fitted chart tuned to that sensitivity
    And no error is raised

  Scenario: Fitting a chart watches for a falling failure rate by default
    Given a sufficient Phase I baseline of pass/fail judgements
    When the engineer fits a chart without specifying which directions of
      drift to watch
    Then they receive a fitted chart that reports it watches for both a
      rising and a falling failure rate

  Scenario: The engineer can restrict monitoring to a rising failure rate only
    Given a sufficient Phase I baseline of pass/fail judgements
    When the engineer fits a chart specifying that only a rise in the
      failure rate should be watched
    Then they receive a fitted chart that reports it watches for a rising
      failure rate only

  # === Story 3: protected from a stale or mismatched judge ===
  #
  # The generic version of this protection is already specified,
  # chart-type-agnostically, in provenance-mismatch-between-phases.feature
  # ("Provenance comparison produces the same error shape regardless of
  # chart type"). These two scenarios exist to confirm a Bernoulli CUSUM
  # chart is not a special case of that guarantee -- exactly BR-2's own
  # stated reason -- not to duplicate its mechanism.

  Scenario: A Phase II judgement made under a different judge model is refused
    Given a fitted Bernoulli CUSUM chart tied to a specific judge model
      version and rubric
    When the engineer records a Phase II judgement made under a different
      judge model version
    Then the recording fails with an error classifiable as a provenance
      mismatch, identifying which aspect of the judge changed and what it
      was expected to be
    And no drift signal is computed from that judgement

  Scenario: A Phase II judgement made under the same judge model and rubric is accepted
    Given a fitted Bernoulli CUSUM chart tied to a specific judge model
      version and rubric
    When the engineer records a Phase II judgement made under that same
      judge model version and rubric
    Then the judgement is accepted into monitoring and contributes to the
      chart's running state

  # === Edge cases spanning multiple business rules ===

  Scenario: Fitting errors are distinguishable by category with distinct recovery guidance
    Given a fitting attempt has failed because the baseline had too few
      observations
    And a separate fitting attempt has failed because the requested
      detection sensitivity was not achievable
    When the engineer compares the two errors
    Then each is classifiable under a different category without
      inspecting the error message text
    And the recovery guidance for each category is distinct from the other

  Scenario: Fitting the same baseline with the same parameters twice produces the same chart
    Given the engineer has a sufficient Phase I baseline of pass/fail
      judgements
    When they fit a chart from it twice, with identical parameters both
      times
    Then both fitted charts report identical false-alarm and detection
      figures
