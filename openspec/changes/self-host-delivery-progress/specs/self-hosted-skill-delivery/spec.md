## ADDED Requirements

### Requirement: Repository self-host pilot
The Skills repository SHALL contain an adopted native OpenSpec change and a signed `.delivery` ledger that records the change's governed task progress.

#### Scenario: Fresh checkout without external anchor
- **WHEN** an agent discovers the project descriptor but cannot resolve the external trust root and confirmed checkpoint
- **THEN** it reports `BLOCKED` and does not infer authority from repository files

#### Scenario: Fresh process with external anchor
- **WHEN** a fresh process resolves the external trust root and confirmed checkpoint using the documented convention
- **THEN** it validates the ledger, reads progress through `deliveryctl status`, and identifies the recorded task and next action without chat history

### Requirement: Provider-author separation
Provider-backed spec and task artifacts SHALL be registered only by a scoped spec-integrator through detector → `observe-provider`; the spec author SHALL record only trace and initial state after observing verified identities.

#### Scenario: Spec author finishes provider files
- **WHEN** provider-native files are committed and pass native validation
- **THEN** an independent integrator observes them before the author submits trace or initial task state operations
