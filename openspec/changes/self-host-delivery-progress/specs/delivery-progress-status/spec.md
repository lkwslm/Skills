## ADDED Requirements

### Requirement: Verified progress snapshot
`deliveryctl status` SHALL replay the ledger at a caller-confirmed external head, verify all pinned authorities, and return the exact reducer state plus a deterministic progress summary.

#### Scenario: Resume after process restart
- **WHEN** a new process supplies the repository, external trust root, confirmed head, repository mapping, and trusted Git pins
- **THEN** status returns current provider profiles, task identities and states, dependencies, claims, trace counts, and the same signed revision

#### Scenario: Untrusted head or authority
- **WHEN** the supplied head differs from `.delivery/HEAD.json` or a pinned authority fails verification
- **THEN** status fails without returning a usable progress snapshot

### Requirement: Actionable task readiness
The progress summary SHALL identify tasks ready for implementation only when they are active, approved, unclaimed, and all task dependencies are accepted.

#### Scenario: Draft task
- **WHEN** a current task has delivery state `draft`
- **THEN** it is reported but is not listed as ready

#### Scenario: Approved unblocked task
- **WHEN** an active task is approved, has no unresolved task dependency, and has no active claim
- **THEN** its artifact ID is listed in `ready_task_ids`
