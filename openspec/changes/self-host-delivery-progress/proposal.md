## Why

The delivery Skills can validate signed ledger data but cannot yet recover actionable progress through a public interface or use this repository as their own governed pilot. This change closes that gap against `software-development/SYSTEM-DELIVERY-SKILL-SUITES.md`.

## What Changes

- Add a verified `deliveryctl status` interface for cross-process recovery.
- Preserve provider artifact identity when only native runtime status changes.
- Map Spec Kit runs to explicit spec and task identities.
- Require provider artifacts to flow through detector → `observe-provider` before trace/state writes.
- Bootstrap this repository with OpenSpec and a signed `.delivery` ledger, then record this change's progress.
- Add an end-to-end self-host recovery test and release CI coverage.

## Capabilities

### New Capabilities

- `delivery-progress-status`: Reconstruct current tasks, dependencies, claims, providers, and trace state from a verified ledger.
- `provider-identity-alignment`: Keep provider observation state separate from governed artifact content identity.
- `self-hosted-skill-delivery`: Use this Skills repository as a governed OpenSpec and `.delivery` pilot.

### Modified Capabilities

None.

## Impact

This affects `deliveryctl`, provider adapters, authorization, the design-to-verified workflow Skills, repository documentation, CI tests, and new `openspec/` plus `.delivery/` state. Trust roots and private keys remain outside the repository.
