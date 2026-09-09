Feature: Score a single agent output and receive structured results
  As a Python engineer wiring quality measurement into my LLM agent
  I want to score an agent output and receive a structured result
  containing the score, the judge's reasoning, and the provenance
  of how the score was produced
  So that I can inspect and act on the assessment and feed it into
  downstream quality monitoring

  # -- Pending decisions --
  # The following open questions are owned by system-architect and
  # are not yet settled. These scenarios are written to survive any
  # resolution.
  #
  # OQ-1 (HIGH): Whether the score is a float, integer, or other
  #   numeric type. The PRD recommends float for EWMA/CUSUM
  #   compatibility. Scenarios assert "numeric score" without
  #   constraining the type.
  #
  # OQ-2: Whether the score occupies a fixed range (e.g. 0.0-1.0),
  #   an engineer-declared range, or is unconstrained. Scenarios do
  #   not assert any range.
  #
  # OQ-3: The minimum testable contract for error message content.
  #   Scenarios assert classifiability by category and presence of
  #   recovery guidance, not specific message text.
  #
  # OQ-4: Whether the library retries transient provider failures or
  #   leaves retry to the caller. Scenarios assert that provider
  #   failures propagate visibly; they do not assume retry behaviour.
  #
  # OQ-5: Whether scoring accepts or rejects an empty-string agent
  #   output. Scenarios do not test empty agent output.
  #
  # OQ-6 (MEDIUM): Whether the scoring interface takes both agent
  #   input and output, or output alone. Scenarios use "agent output"
  #   without assuming whether input is also required.
  #
  # BIN-58 OQ-3: Whether criteria attach at the judge, the monitor,
  #   or per-call. Scenarios require criteria to be available at
  #   scoring time regardless of where they were configured.

  # --- Happy path (BR-1 happy, BR-2 happy) ---

  Scenario: Engineer scores an agent output and receives a structured result
    Given the engineer has a judge configured with a pinned model version and scoring criteria
    When they score an agent output
    Then they receive a result containing a numeric score
    And the result contains the judge's textual reasoning for the score

  Scenario: Scoring result carries provenance of the measurement configuration
    Given the engineer has a judge with a specific pinned model version and specific scoring criteria
    When they score an agent output and inspect the result
    Then the result reports the model version that produced the score
    And the result reports the criteria the score was assessed against
    And the provenance values match the judge's configuration exactly

  # --- Sad paths: scoring failures (BR-1 sad, BR-4, BR-5, BR-6) ---

  Scenario: Provider error during scoring propagates to the engineer
    Given the engineer has a judge configured with criteria
    When they attempt to score an agent output and the judge's provider returns an error
    Then the scoring call fails with an error that is programmatically classifiable as a provider failure
    And the error carries recovery guidance identifying the provider and the failed operation
    And no result is returned

  Scenario: Malformed judge response fails visibly
    Given the engineer has a judge configured with criteria
    When they attempt to score an agent output and the judge produces a response that cannot be interpreted as a structured result
    Then the scoring call fails with an error that is programmatically classifiable as a malformed response
    And the error carries recovery guidance identifying the expected response shape
    And no partial or default result is returned

  Scenario: Scoring without criteria fails before reaching the judge
    Given the engineer has a judge but no scoring criteria are available
    When they attempt to score an agent output
    Then the scoring call fails immediately with an error that is programmatically classifiable as a missing prerequisite
    And the error identifies that scoring criteria are required

  # --- Edge case: immutability (BR-3) ---

  Scenario: Scoring result cannot be modified after creation
    Given the engineer has scored an agent output and received a result
    When they attempt to modify the score, reasoning, or provenance of that result
    Then the modification is rejected
    And the result continues to report its original values

  # --- Boundary: error category distinguishability (BR-4 / BR-5 boundary) ---

  Scenario: Different scoring failure categories are distinguishable and carry distinct recovery guidance
    Given a scoring call has failed with a provider error
    And a separate scoring call has failed with a malformed judge response
    And a third scoring call has failed with a missing prerequisite
    When the engineer examines the three errors
    Then each is classifiable under a different category without inspecting the error message text
    And the recovery guidance for each category is distinct from the others
