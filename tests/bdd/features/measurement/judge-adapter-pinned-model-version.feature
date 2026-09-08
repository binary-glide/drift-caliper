Feature: Judge adapter with required pinned model version
  As a Python engineer wiring quality measurement into my LLM agent
  I want to create a judge that requires a specific model version
  So that I can trust that score changes reflect my agent's behaviour
  and not silent model updates

  # -- Ratified decision (product owner, 2026-09-08) --
  # A missing or invalid model version causes judge creation to FAIL
  # loudly. It does NOT merely warn.
  #
  # Rationale: an unpinned judge model silently invalidates every
  # statistical claim downstream, and the cost is asymmetric -- relaxing
  # an error to a warning later is non-breaking, whereas tightening a
  # warning to an error is a breaking change.
  #
  # The scenarios below encode that decision. What remains open for
  # system-architect is the enforcement MECHANISM only -- exception type
  # and message content -- not whether it fails.

  # --- Happy path (BR-1 happy, BR-2 happy) ---

  Scenario: Engineer creates a judge with a pinned model version
    Given the engineer has identified a model version string for their chosen provider
    When they create a judge specifying that model version
    Then the judge should be created successfully
    And the judge should report the specified model version when inspected

  # --- Sad paths: missing or invalid model version (BR-1 sad, BR-2 sad, BR-4) ---

  Scenario: Engineer attempts to create a judge without specifying a model version
    Given the engineer has not provided a model version
    When they attempt to create a judge
    Then the judge should not be created
    And the engineer should be told that a model version is required for measurement stability
    And the message should include an example of correct usage

  Scenario: Engineer provides an empty string as the model version
    Given the engineer provides an empty string where a model version is expected
    When they attempt to create a judge
    Then the judge should not be created
    And the engineer should be told that a non-empty model version is required
    And the message should explain that model pinning protects measurement stability
    And the message should include an example of correct usage

  Scenario: Engineer provides a whitespace-only string as the model version
    Given the engineer provides a string containing only whitespace as the model version
    When they attempt to create a judge
    Then the judge should not be created
    And the engineer should be told that a non-empty model version is required
    And the message should explain that model pinning protects measurement stability
    And the message should include an example of correct usage

  # --- Edge cases: preservation and immutability (BR-3) ---

  Scenario: Model version is preserved exactly as provided
    Given the engineer creates a judge with a model version containing mixed case and special characters
    When they inspect the judge's model version
    Then the reported version should match the original string character for character

  Scenario: Model version cannot be changed after judge creation
    Given the engineer has created a judge with a pinned model version
    When they attempt to change the judge's model version
    Then the change should be rejected
    And the judge should continue to report its original model version

  # --- Boundary value: whitespace padding (BR-2 boundary) ---

  Scenario: Model version with surrounding whitespace is accepted and preserved
    Given the engineer creates a judge with a model version that has leading and trailing spaces
    When they inspect the judge's model version
    Then the reported version should include the surrounding spaces exactly as provided
