Feature: Phase II provenance comparison against fitted artefact
  As a Python engineer who has fitted control limits from a Phase I baseline
  I want the library to detect when a Phase II scoring result's measurement
  provenance differs from the provenance recorded in the fitted artefact
  So that I do not unknowingly monitor with limits derived from a different
  measurement system

  # -- Pending decisions --
  # The following open questions are owned by system-architect and
  # are not yet settled. These scenarios are written to survive any
  # resolution.
  #
  # [RATIFIED 2026-09-09] A2: The comparison checks BOTH provenance
  #   dimensions -- model version AND criteria.
  #   Settled by the product owner. BIN-63's BR-1 already rejects an
  #   observation whose provenance disagrees with the baseline's, and
  #   provenance is BOTH dimensions -- so a criteria mismatch already
  #   raises within Phase I. Checking only model version here would
  #   mean the same dimension raises inside Phase I and is ignored
  #   across the boundary, breaking the consistency SC6 enforces.
  #   Open: the comparison MECHANISM only (OQ-2, exact vs normalised).
  #
  # [RATIFIED 2026-09-10] OQ-1: How the dimension field represents a dual
  #   mismatch (both model version and criteria differ).
  #   Settled by system-architect: context["mismatches"], a
  #   dict[str, dict[str, str]] keyed by dimension name ("model_version",
  #   "scoring_criteria"), each holding {"expected": ..., "received": ...}.
  #   Replaces the originally-specified dimension/expected/received keys.
  #   See ADR-002 Amendment (2026-09-10) and docs/domain-model.md OQ-11.
  #   The scenarios below were written to survive this resolution
  #   unchanged -- they assert that both dimensions are reported without
  #   prescribing the shape, and remain correct against it.
  #
  # [RATIFIED 2026-09-10] OQ-2: What criteria comparison mechanism
  #   applies -- exact string match or normalised.
  #   Settled by the product owner: exact string match. No stripping, no
  #   whitespace collapsing, no case folding, no Unicode normalisation.
  #   Inherited from BIN-63 OQ-6, applies identically here. See
  #   docs/domain-model.md "Criteria equality is exact".
  #
  # [RATIFIED 2026-09-10] OQ-3: Whether an explicit override or
  #   acknowledgement path exists for an engineer who knowingly changed
  #   the judge between phases.
  #   Settled by the product owner: no override. The engineer refits.
  #   compare_provenance() takes no acknowledge/force parameter of any
  #   kind -- an acknowledged mismatch is still a mismatch. See
  #   docs/domain-model.md "Provenance change requires a refit" (OQ-9).

  # --- Happy path (BR-1 happy) ---

  Scenario: Provenance matches between Phase II scoring result and the fitted artefact
    Given the engineer has a fitted control limit artefact from a Phase I baseline
    And they have a Phase II scoring result produced with the same judge model version and scoring criteria as the baseline
    When they compare the scoring result's provenance against the fitted artefact's provenance
    Then the comparison confirms the provenances are compatible

  # --- Sad paths: provenance mismatches (BR-1 sad, BR-2, BR-3) ---

  # Provenance consistency across phases is the final link in the
  # integrity chain. A Phase II observation measured by a different
  # instrument than Phase I renders control limits meaningless --
  # the same violation as BIN-63's intra-baseline check, at the
  # Phase I to Phase II boundary.

  Scenario: Comparison fails when the judge model version differs between phases
    Given the engineer has a fitted control limit artefact carrying a specific judge model version in its provenance
    And they have a Phase II scoring result produced by a different judge model version
    When they compare the scoring result's provenance against the fitted artefact's provenance
    Then the comparison fails with an error that is programmatically classifiable as a provenance mismatch
    And the error identifies the differing dimension as model version
    And the error identifies the fitted artefact's model version as the expected value
    And the error identifies the scoring result's model version as the received value

  Scenario: Comparison fails when the scoring criteria differ between phases
    Given the engineer has a fitted control limit artefact carrying specific scoring criteria in its provenance
    And they have a Phase II scoring result produced against different criteria
    When they compare the scoring result's provenance against the fitted artefact's provenance
    Then the comparison fails with an error that is programmatically classifiable as a provenance mismatch
    And the error identifies the differing dimension as criteria
    And the error identifies the fitted artefact's criteria as the expected value
    And the error identifies the scoring result's criteria as the received value

  # --- Sad path: dual mismatch (BR-4, OQ-1 pending) ---

  # When both dimensions differ, the error reports both -- not just
  # the first one checked. Reporting only one forces the engineer
  # through a fix-one-discover-the-other cycle. The representation
  # of a dual mismatch in the structured context (string, list, or
  # paired entries) is OQ-1, owned by system-architect.

  Scenario: Comparison reports both dimensions when model version and criteria both differ
    Given the engineer has a fitted control limit artefact with specific provenance
    And they have a Phase II scoring result where both the judge model version and the scoring criteria differ from the fitted artefact
    When they compare the scoring result's provenance against the fitted artefact's provenance
    Then the comparison fails with an error that is programmatically classifiable as a provenance mismatch
    And the error identifies that both provenance dimensions differ
    And the error reports the expected and received values for each differing dimension

  # --- Edge case: chart-type independence (BR-6) ---

  Scenario: Provenance comparison produces the same error shape regardless of chart type
    Given the engineer has fitted artefacts from different chart types, each carrying the same baseline provenance
    And they have a Phase II scoring result with a different judge model version
    When they compare the scoring result against any of the fitted artefacts
    Then each comparison fails with an error that is programmatically classifiable as a provenance mismatch
    And the structured context follows the same shape for all chart types

  # --- Category consistency with Phase I (BR-2, ADR-002) ---
  #
  # This scenario IS the ratified decision: a Phase II mismatch and
  # a Phase I intra-baseline mismatch are the same category of
  # violation, carrying structured context with the same required
  # fields. This stops the two boundaries drifting apart.

  Scenario: Phase II provenance mismatch is classifiable as the same category as a Phase I baseline recording mismatch
    Given the engineer has encountered a provenance mismatch error from recording an observation with inconsistent provenance into a Phase I baseline
    And they have encountered a provenance mismatch error from comparing a Phase II scoring result against a fitted artefact
    When they compare the two errors programmatically
    Then both are classifiable as the same provenance mismatch category
    And both carry structured context with the same required fields
