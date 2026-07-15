## Context

The signed ledger already enforces CAS, authority hashes, roles, claims, gates, and trace closure. Its only supported read command returns counts, while workflow Skills need exact task identities and states after a context restart. Provider adapters also mix observed workflow status with content identity, and Spec Kit exposes only a run-shaped task.

The repository must prove the workflow against itself. OpenSpec is installed outside the checkout as a pinned interpreter runtime; `.delivery` stores only signed public state, while trust roots, private keys, and the caller-confirmed head remain in a standard external anchor directory.

## Goals / Non-Goals

**Goals:**

- Provide a fail-closed machine-readable progress snapshot after full replay and authority verification.
- Keep workflow status observations without replacing unchanged spec/task identities.
- Give Spec Kit runs separate spec and task identities with an explicit dependency.
- Make provider observation and author trace/state writes an unambiguous two-transaction handoff.
- Record and recover this repository's own development state through the public CLI.

**Non-Goals:**

- Store private keys or authoritative trust anchors in Git.
- Treat native provider completion as Delivery acceptance.
- Auto-approve, auto-retry CAS conflicts, or migrate state across actual content changes.

## Decisions

1. `deliveryctl status` performs the same verified replay as `validate`, then returns both the full reducer state and a deterministic progress summary. This keeps one authoritative read path and avoids parsing generated view files.
2. Provider artifact equality excludes the observation-only `status` field but still compares delivery/native IDs, parent, type, authority path, content hash, and canonicalization. Actual content changes continue to supersede.
3. A Spec Kit run produces `SPECKIT-SPEC-<run>` from immutable run inputs and `SPECKIT-RUN-<run>` as a task derived from that spec. Mutable run state remains observation evidence rather than task content identity.
4. Spec authors commit provider-native files first. A separate integrator runs detector → `observe-provider`; only then may the author record trace nodes, edges, and initial task states using identities returned by verified `status`.
5. Self-host trust material lives under the user's external Codex data directory. A committed non-secret project descriptor identifies the ledger and relative anchor convention; it never supplies authority by itself.

## Risks / Trade-offs

- A full status snapshot may be large → retain strict bounded ledger inputs and provide a compact `progress` section for normal use.
- Ignoring provider status could hide an important content change → only the status field is ignored; hashes and all identity fields still gate supersession.
- Provider task file content changes intentionally reset typed identity → status reports such tasks as untracked until they are explicitly re-registered and approved.
- External anchors reduce checkout portability → the project descriptor makes the requirement discoverable, and missing anchors fail closed.

## Migration Plan

1. Add CLI/read tests and provider identity tests.
2. Update Skill contracts and role permissions.
3. Initialize OpenSpec, create this change, and commit a pinned provider state.
4. Bootstrap `.delivery` with distinct external actors, observe OpenSpec, and record task progress.
5. Start a fresh process, recover through `deliveryctl status`, run release tests, and record evidence/audit.
6. Push the signed ledger and provider artifacts with the implementation.

Rollback removes the unmerged branch. Once merged, ledger history remains append-only; later corrections use supersession and new signed events.

## Open Questions

None for this pilot.
