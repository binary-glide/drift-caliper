Feature: Review fitted control limits and their parameters
  As a Python engineer who has fitted control limits from a Phase I baseline
  I want to review the fitted configuration consistently regardless of chart
  type
  So that I can verify the configuration matches my expectations before
  deploying to production monitoring and present the configuration to an
  auditor when required

  # -- Pending decisions --
  # The following assumptions and open questions are not yet settled.
  # These scenarios are written to survive any resolution.
  #
  # [ASSUMPTION] A1 -- HIGH: A common protocol should exist across
  #   chart types, enabling chart-type-agnostic review of the shared
  #   audit information. The mechanism is for system-architect. The PRD
  #   takes the position that a shared protocol with chart-specific
  #   extensions is preferred over three parallel types or a union type.
  #   SC3 asserts the capability (chart-type-agnostic access) without
  #   prescribing the mechanism. If the assumption is wrong and the
  #   three artefact types have no shared interface, SC3 and SC5 would
  #   need rewriting to accept per-type review paths.
  #   Owner: system-architect
  #
  # OQ-1: Should the review include a serialisable form (dictionary)
  #   for audit logging? The PRD recommends in-scope here as a
  #   secondary capability alongside review, but not a blocker.
  #   Owner: system-architect
  #
  # OQ-2: Does review need to survive a persistence round trip?
  #   The artefact is self-contained; this is arguably BIN-72/73 scope.
  #   Owner: system-architect
  #
  # OQ-3 (shared): API shape for specifying false alarm tolerance --
  #   ARL0, false alarm rate (alpha), or both? Inherited from
  #   BIN-65/94/95. Review must present whichever form was used.
  #   Owner: system-architect
  #
  # OQ-4 (shared): Whether fitting calls the sufficiency check
  #   internally or externally. Not directly relevant to review.
  #   Owner: system-architect
  #
  # BIN-92 (SP-2): Minimum viable baseline size unknown. Review
  #   presents whatever was fitted; not affected by the threshold.
  #
  # BIN-93 (SP-3): Calibration method may change. Review presents
  #   the method that was used, by name; not affected by the choice.
  #
  # Error paths: The PRD explicitly claims zero error paths for
  #   review. This claim was tested against the BIN-64 precedent
  #   (where requirements-reviewer found a missed path in a
  #   configurable parameter). Review has NO configurable parameters,
  #   NO computation, and NO external dependencies. The artefact is
  #   immutable and fully validated at creation time (upstream
  #   BR-10/11/12). Read-only inspection of a valid immutable object
  #   has no failure mode. The zero-error claim holds.

  # --- Happy path: complete audit information (AC-1, BR-4) ---

  # Each upstream fitting story individually guarantees its own fields
  # are present. This scenario asserts the REVIEW capability presents
  # them coherently -- chart-agnostically, without specifying which
  # chart type was fitted.

  Scenario: Engineer reviews a fitted artefact and sees all audit-relevant information
    Given the engineer has fitted control limits from a Phase I baseline
    When they review the fitted artefact
    Then the review presents the detection boundaries that define the in-control region
    And the review presents the baseline statistics including the mean, the spread measure, and the observation count
    And the review presents the provenance including the judge model version and the scoring criteria
    And the review presents the requested and achieved false alarm tolerance and the calibration method
    And the review identifies which chart type the artefact represents

  # --- Happy path: chart-specific parameters alongside shared core
  #     (AC-2, BR-2) ---

  # Chart-specific parameters (smoothing parameter for EWMA, reference
  # value and direction for CUSUM, sigma estimate and estimation method
  # for Shewhart) complete the audit record. A review that shows only
  # the shared fields is incomplete.

  Scenario: Review presents chart-specific parameters alongside the shared audit information
    Given the engineer has fitted control limits using a specific chart type
    When they review the fitted artefact
    Then the review presents the chart-type-specific parameters that were used or derived during fitting
    And the chart-specific parameters are presented alongside the shared audit information

  # --- Happy path: cross-chart-type consistency (AC-3, BR-1) ---
  #
  # This is the scenario the three upstream fitting stories do not
  # cover. Each individually guarantees its own auditability. This
  # scenario asserts that the shared core is reachable the same way
  # regardless of which chart was fitted -- the protocol-forcing
  # function that resolves OQ-2 from all three fitting PRDs.

  Scenario: Shared audit information is accessible without knowing the chart type
    Given the engineer has fitted artefacts from each of the three supported chart types
    When they review each artefact
    Then the baseline statistics, provenance, false alarm tolerance, and calibration method are presented through the same review mechanism for all three
    And the engineer does not need to determine the chart type before reviewing the shared information

  # --- Happy path: human-readable summary (AC-4, BR-4) ---

  Scenario: Engineer obtains a human-readable summary suitable for an audit log
    Given the engineer has fitted control limits from a Phase I baseline
    When they obtain a textual representation of the fitted artefact
    Then the text includes the chart type, detection boundaries, chart-specific parameters, baseline statistics, provenance, and both the requested and achieved false alarm tolerance
    And the text is formatted for human reading

  # --- Happy path: summary consistency across chart types (AC-5, BR-5) ---

  Scenario: The human-readable summary is consistent in structure across chart types
    Given the engineer has fitted artefacts from each of the three supported chart types
    When they obtain a textual representation of each
    Then the shared audit fields appear in the same position and with the same labelling in all three summaries
    And the chart-specific parameters appear in a clearly identified section
