## ADDED Requirements

### Requirement: Observation status is not content identity
Provider reconciliation SHALL retain the existing governed artifact identity when only the native observation status changes and all content identity fields and hashes remain equal.

#### Scenario: Workflow status advances
- **WHEN** a provider run changes from paused to completed without changing its pinned spec/task content
- **THEN** a new provider profile observation is recorded and no artifact is superseded

#### Scenario: Governed content changes
- **WHEN** the provider content hash, canonicalization, path, type, parent, or stable native identity changes
- **THEN** reconciliation creates a new governed artifact version and existing typed state does not silently transfer

### Requirement: Spec Kit exposes a spec-task graph
Each persisted Spec Kit run SHALL map to a stable spec artifact and a stable task artifact derived from that spec.

#### Scenario: Persisted run detected
- **WHEN** a valid Spec Kit run contains matching inputs, state, log, and CLI status
- **THEN** the detector emits `SPECKIT-SPEC-<run>` and `SPECKIT-RUN-<run>` mappings with an exact parent relationship
