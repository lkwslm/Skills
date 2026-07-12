# Evidence protocol

Evidence must contain commit/tree hash, related artifact hashes, runner, operating system, tool versions or image digest, start/end timestamps, raw log path/hash, test selector, pass/fail/skip counts, skip reasons and approvals, attempt ID, unverified items, and expiry or invalidation conditions.

Store summaries separately from raw results. Never treat an agent narrative as raw evidence. A retry is a new attempt; preserve prior failures. Evidence becomes stale when its commit, related artifact, environment contract, or explicit validity condition changes.

Completion evidence must be replayable: record exact command, exit code, artifact path and requirement/test IDs. Recompute the raw-log hash, match the delivery commit and registered artifact identities, and validate timestamp order before accepting it. A skipped mandatory check requires a non-expired `RISK_ACCEPTED` approval bound to the skipped requirement or test and its registered content hash.

Require `unverified_items` to be empty at the completion-evidence gate. Resolve a legitimate exception before this gate through a versioned traceability exemption and its governed approval; do not reinterpret an unresolved item inside evidence as an implicit risk acceptance. Keep missing production authorization in the release handoff and `release_ready` state, not as an unverified implementation item.
