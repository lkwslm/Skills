## 1. Verified Progress Interface

- [x] 1.1 Add `deliveryctl status` with verified state, task dependencies, claims, and readiness; verify with `test_status_returns_verified_state_for_cross_process_resume`.
- [x] 1.2 Permit fact-extractor/spec-author initial state registration without transition authority; verify with the focused permission test.

## 2. Provider Identity Alignment

- [x] 2.1 Preserve artifact identity for status-only observations and map Spec Kit runs to spec/task pairs; verify both provider E2E tests.
- [x] 2.2 Map OpenSpec checkbox items to stable individual task identities; verify checkbox toggles keep content hashes and Git authority validation passes.

## 3. Self-Hosted Pilot

- [x] 3.1 Initialize official OpenSpec plus an external pinned runtime and create the signed `.delivery` trust/actor policy.
- [x] 3.2 Observe provider artifacts, register design trace and task states, then recover progress from a fresh process using public `deliveryctl status`.

## 4. Release

- [ ] 4.1 Run all Skill, detector, ledger, self-host, compile, YAML, and diff checks; record signed evidence/audit and publish the branch to GitHub.
