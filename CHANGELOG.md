# Changelog

All notable changes to `drift-caliper`.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

⚠️ **Generated from commit history by [git-cliff](https://git-cliff.org)** --
run `uv run git-cliff -o CHANGELOG.md` before tagging. Narrative release notes
on the [GitHub releases page](https://github.com/binary-glide/drift-caliper/releases)
are written by hand and say *why*; this file is the complete record of *what*.

⚠️ **Pull request numbers below `0.1.0a1` refer to a different repository.**
This history was exported from the private `binary-glide/caliper`, whose
numbering restarted at 1 here -- so `(#75)` is an old-repository reference and
resolves nowhere public, while `(#12)` on a later entry is this repository's.
They are kept verbatim because they are accurate provenance; they are
deliberately **not** hyperlinked, since a link would silently point at the
wrong pull request once the two ranges overlap.


## Unreleased

### Fixed

- Pin gh-action-pypi-publish by version tag, not commit SHA (#11)

### Documentation

- The package is published — say so, and correct the --pre claim (#12)

### Internal

- Enforce lint, types and commit format at commit time (#15)
- Run CodeQL's security-extended suite, not security-and-quality (#14)
- Pin every action by commit SHA, and record the checks we will not meet (#13)

## [0.1.0a1] -- 2026-09-16

### Added

- BIN-135 — add HasProvenance, implementing ADR-004's amendment (#63)
- BIN-134 — report bounds as structured fields, restoring the round-trip guard (#62)
- ADR-011 ARL₀ tiering and bool score rejection (BIN-131, BIN-132) (#55)
- Signal delivery and the log receiver (BIN-75, BIN-76) (#44)
- Phase II record and signal check, and session history (BIN-69, BIN-72) (#39)
- Wire BIN-66's scenarios and add audit_summary() (#36)
- Compare provenance across the Phase I/II boundary (BIN-68) (#35)
- Bring the public API up to standard (BIN-110) (#34)
- Implement Shewhart I-chart control limit fitting
- Implement CUSUM control limit fitting
- Implement EWMA control limit fitting
- Implement Baseline.check_sufficiency()
- Implement Baseline.record() invariants
- Implement Judge.score() orchestration and ScoringResult validation
- Implement ScoringCriteria validation
- Implement Judge with required pinned model version

### Fixed

- Correct the README import line missed by the package rename (#73)
- Normalise probed provenance to exact str, closing BIN-139 (#61)
- BIN-140 — fit_ewma returned a negative achieved_arl (#60)
- BIN-121 parts 1 & 3 — hostile objects at the comparison boundary (#58)
- Guard duck-typed attribute access — BIN-121's audit now reads zero (#54)
- Type-guard the value objects, closing BIN-104's seven leaks (#53)
- Type-guard fit_ewma's baseline and smoothing_param (#52)
- Type-guard six public entry points, and stop bool masquerading as an ARL target (BIN-126) (#50)
- Compute an overflow-safe mean so representable baselines fit (BIN-123) (#47)
- Stop four non-CaliperError leaks from the public API (BIN-119, BIN-120) (#46)
- Reject unattainable CUSUM targets and guard signal-delivery formatting (BIN-117, BIN-118) (#45)
- Make SufficiencyResult's immutability real, not documented
- Move agent-provenance markers out of package docstrings

### Changed

- BIN-141 — consolidate _require_target_arl and guard re-triplication (#65)
- Hoist _has_zero_variance into the numerical layer (#64)
- Split ewma_fitting so beartype stops guarding a public boundary (BIN-130) (#51)
- Use d2's exact closed form, drop the citation chain
- Split measurement package into domain/ and ports/
- Migrate value objects to Pydantic BaseModel
- Extract ModelVersion to its own module
- Declare category per type; unpin mypy target

### Documentation

- Say that a framework-bound judge is the right judge (#3)
- Lead the install instructions with uv (#2)
- Make the README wordmark lowercase monospace (#79)
- Host on Read the Docs rather than GitHub Pages (#78)
- Give the README's citations their own heading (#77)
- Name the decided replacement for the p-chart (#76)
- State what each chart is for, reject the p-chart, and correct three claims (#71)
- Mark ADR-004's 2026-09-12 amendment as unimplemented
- ADR-005 amendment — target-dependent baseline adequacy (#41)
- Field-level Monitor and MonitoringResult for E3 (#38)
- ADR-009 for E3, and close every primary-source gap (#37)
- Set the bar for nested context values in ADR-002
- Amend ADR-002 -- provenance_mismatch reports a mismatches mapping
- Correct the d2 framing left backwards by the swap
- Record that d2 has an exact closed form
- Mark BIN-63 and BIN-64 operations as implemented
- Settle OQ-2 — criteria equality is exact, no normalisation
- Close the changelog's OQ-9 loose end
- Settle OQ-9 — a changed judge requires a refit, no override
- Refresh domain model against ADR-006/007/008 and E1
- ADR-007 two type checkers, ADR-008 error assertion discipline
- Type Provenance's fields as ModelVersion/ScoringCriteria, not str
- Rename ADR-006's scoring parameters to agent_output/agent_input
- Add ADR-006 scoring API surface and judge provider port
- Fix the punctuation and phrasing of the criteria recovery hint
- Amend ADR-004 and ADR-005 — sigma estimate moves to shared core
- Correct sigma estimator — MR-based for all charts
- Add domain model for caliper SPC library
- ADR-005 minimum Phase I baseline size for LLM judge scores
- Settle fitted artefact protocol and fitting API surface
- Reject bootstrapped MEWMA for control-limit calibration
- Record A2 as ratified in the feature file header
- Correct inverted CUSUM arm mapping in ADR-001
- Rename invalid_parameter discriminator to kind
- Amend ADR-002 — positive reason discriminator and API-shape dependency
- Error contract — exception taxonomy with structured recovery guidance
- Ratify fail-loudly on unpinned judge model
- Ratify OQ-1 — invalid criteria raise
- ADR-001 SPC engine in-house with scipy

### Internal

- Release 0.1.0a1 (#9)
- Give every workflow a manual trigger (#7)
- Add a security policy and least-privilege CI permissions (#6)
- Let the security workflows be triggered manually (#5)
- Correct a stale ty comment, and fix the package metadata (#4)
- Bump mutmut in the dev-toolchain group (#1)
- Bump the dev-toolchain group with 2 updates (#69)
- Bump astral-sh/setup-uv in the actions group (#68)
- Add Dependabot, and record two launch-blocking decisions (#67)
- BIN-128 — enforce five project invariants structurally (#66)
- BIN-136 — cross every hostile-input kind against every entry point (#59)
- BIN-122 contract composition — the legal region must be coherent (#57)
- Guard Hypothesis parameter bounds against library drift (BIN-124, round two) (#56)
- Audit the exception contract across the whole public surface (BIN-121) (#49)
- Guard against Hypothesis strategies drifting out of sync with the library's contract (BIN-124) (#48)
- Dependency audit, and numpydoc docstrings with honest citations (#43)
- Enable ruff's security rules (S, ASYNC, DTZ, LOG) (#42)
- Property-based SPC verification for BIN-84 (#40)
- Add failing tests for Shewhart control limit fitting
- Pin the calibration promise and correct a beartype comment
- Record an end-to-end simulation of fitted CUSUM charts
- Verify Siegmund by simulation; pin target_arl's meaning
- Add failing tests for CUSUM control limit fitting
- Adopt beartype for the EWMA numerical internals, dev-only
- Pin the discretisation as an accuracy claim; explain a survivor
- Pin the helpers that cancel out of fit_ewma's output
- Make the EWMA numerical proof actually load-bearing
- Record an independent recomputation of the EWMA constants
- Add failing BIN-65 tests for EWMA control limit fitting
- Pin the zero-variance boundaries
- Tighten three BDD assertions to exact sets
- Add failing BIN-64 tests for baseline sufficiency check
- Remove agent-provenance markers from source
- Assert the exact missing-fields set, not membership
- Add failing BIN-63 tests for Phase I baseline collection
- Bring tests/ into test-patterns conformance
- Adopt the house test stack, coverage and mutation config
- Add red tests for scoring a single agent output
- Drop an agent-provenance marker from a public docstring
- Rename a BIN-58 test whose name claimed a case it does not test
- Add red tests for ScoringCriteria text rubric
- Stop the package smoke test freezing the public surface
- Add failing tests for judge adapter pinned model version
- Add ty as first type gate; pin setup-uv to an exact tag
- Scaffold Python package, toolchain and CI
- Add Phase II provenance comparison scenarios
- Add review fitted control limits scenarios
- Correct overstated order-dependence assertion in SC4
- Add Shewhart I-chart control limit fitting scenarios
- Add CUSUM control limit fitting scenarios
- Migrate six feature files to the ADR-002 error contract
- Add EWMA control limit fitting scenarios
- Amend baseline sufficiency scenarios for M1 m1 m2 m3
- Add baseline sufficiency check scenarios
- Add Phase I baseline collection scenarios
- Add judge adapter pinned model version scenarios
- Add scoring criteria text rubric scenarios
- Add score-agent-output-structured-results scenarios
- Initialise caliper repository

### Other

- Normalise scores to exact floats before anything hashes them (#10)
- Publish to PyPI via Trusted Publishing (#8)
- Narrow direction before hashing it, at both membership sites (#80)
- Control limits must be finite, or the fit must refuse (#75)
- Documentation site, README rewrite, and the badges' supporting workflows (#74)
- Rename to drift-caliper — the PyPI name this project committed to is taken (#72)

<!-- generated by git-cliff -->
