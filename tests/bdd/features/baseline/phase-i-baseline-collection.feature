Feature: Record observations into a Phase I baseline collection
  As a Python engineer building a quality baseline for my LLM agent
  I want to record judged scoring results into a Phase I baseline collection
  So that I can build a trusted reference dataset from known-good runs
  for control limit fitting

  # -- Pending decisions --
  # The following open questions are owned by system-architect and
  # are not yet settled. These scenarios are written to survive any
  # resolution.
  #
  # [ASSUMPTION] HIGH: The baseline should reject observations with
  #   inconsistent provenance (different judge model version or
  #   criteria) rather than accepting them with a warning. Scenarios
  #   assert rejection. If the assumption is wrong, SC5, SC6, and
  #   SC8 would need rewriting.
  #
  # [ASSUMPTION] HIGH: The baseline should retain the full scoring
  #   result (score, reasoning, and provenance), not just the numeric
  #   score. Scenarios assert full retention. If the assumption is
  #   wrong, SC3 and SC4 would need rewriting.
  #
  # OQ-3: Whether observations carry an explicit timestamp, a
  #   sequence index, or rely solely on insertion order. Scenarios
  #   assert ordering without assuming a specific mechanism.
  #
  # OQ-4: Whether there is a maximum baseline size. Scenarios do
  #   not assert or assume any size limit.
  #
  # OQ-5: Whether baselines support a name or label for
  #   identification. Scenarios do not reference baseline names.
  #
  # OQ-6: What mechanism compares scoring criteria for equality
  #   (exact string match, normalised comparison, or structural
  #   comparison). Scenarios assert that "different criteria" are
  #   rejected without assuming the comparison method.
  #
  # BIN-58 OQ-3: Whether criteria attach at the judge, the monitor,
  #   or per-call. Scenarios describe provenance as carried by the
  #   scoring result, not by a specific configuration point.

  # --- Happy paths (BR-1 happy, BR-2 happy, BR-7 happy) ---

  Scenario: Engineer records a scoring result into a baseline and inspects the collection
    Given the engineer has a Phase I baseline collection
    And they have a scored agent output with a numeric score, reasoning, and provenance
    When they record the scoring result into the baseline
    Then the baseline contains the recorded observation
    And the engineer can inspect the total number of observations in the baseline

  # Observation order is not cosmetic. EWMA and CUSUM charts are
  # inherently sequential -- shuffled observations produce different
  # control limits from the same data.

  Scenario: Baseline preserves the order in which observations were recorded
    Given the engineer has a Phase I baseline collection with several recorded observations
    When they inspect the observations in the baseline
    Then the observations appear in the order they were recorded

  # The baseline must retain the full scoring result, not just the
  # numeric score. BIN-68 (judge model version change warning)
  # depends on the baseline carrying provenance to compare Phase I
  # and Phase II measurement configurations.

  Scenario: Baseline observations retain the full provenance from their scoring results
    Given the engineer has recorded a scoring result into a Phase I baseline
    When they inspect the recorded observation
    Then the observation reports the model version that produced the score
    And the observation reports the criteria the score was assessed against
    And the provenance values match the original scoring result exactly

  Scenario: Recorded observation retains the score and reasoning from the original scoring result
    Given the engineer has recorded a scoring result with a specific numeric score and specific reasoning into a Phase I baseline
    When they inspect the recorded observation
    Then the observation reports the same numeric score as the original scoring result
    And the observation reports the same reasoning as the original scoring result

  # --- Sad paths: recording failures (BR-1 sad, BR-4, BR-5) ---

  # Provenance consistency is the primary guard against baseline
  # contamination. Mixing observations from different measurement
  # configurations silently invalidates control limits -- the most
  # dangerous failure mode the library can produce, because it is
  # invisible until wrong control limits produce incorrect signals.

  Scenario: Recording fails when the scoring result has a different judge model version than existing observations
    Given the engineer has a Phase I baseline containing observations scored by a specific judge model version
    When they attempt to record a scoring result produced by a different judge model version
    Then the recording fails with an error that is programmatically classifiable as a provenance mismatch
    And the error describes what the engineer should do next
    And the baseline is unchanged

  Scenario: Recording fails when the scoring result has different scoring criteria than existing observations
    Given the engineer has a Phase I baseline containing observations scored against specific criteria
    When they attempt to record a scoring result produced against different criteria
    Then the recording fails with an error that is programmatically classifiable as a provenance mismatch
    And the error describes what the engineer should do next
    And the baseline is unchanged

  Scenario: Recording something that is not a complete scoring result fails before modifying the baseline
    Given the engineer has a Phase I baseline collection
    When they attempt to record something that is not a complete scoring result with score, reasoning, and provenance
    Then the recording fails with an error that is programmatically classifiable as an invalid observation
    And the error describes what the engineer should do next
    And the baseline is unchanged

  # --- Boundary: provenance signature establishment (BR-1 boundary) ---

  Scenario: First recorded observation establishes the baseline's provenance signature
    Given the engineer has a new empty Phase I baseline collection
    When they record their first scoring result
    Then the baseline reports one observation
    And the baseline reports the judge model version and scoring criteria from that observation as its expected provenance

  # --- Edge case: observation immutability (BR-3) ---

  # Observations are historical measurement records. Modifying an
  # observation after recording would break the audit chain and
  # could invalidate control limits fitted from this baseline.

  Scenario: Recorded observation cannot be modified after entering the baseline
    Given the engineer has recorded a scoring result into a Phase I baseline
    When they attempt to modify the score, reasoning, or provenance of the recorded observation
    Then the modification is rejected
    And the observation continues to report its original values

  # --- Boundary: error category distinguishability (BR-4 / BR-5 boundary) ---

  Scenario: Recording errors are distinguishable by category with distinct recovery guidance
    Given a recording attempt has failed with a provenance mismatch
    And a separate recording attempt has failed with an invalid observation
    When the engineer examines the two errors
    Then each is classifiable under a different category without inspecting the error message text
    And the recovery guidance for each category is distinct from the other
