# Run, evidence and audit protocol

A run binds suite, full target commit, and non-empty input artifact identities. Attempts are contiguous within a run and bind the same commit plus input digests. Completion records result, UTC end time and raw log digest; raw logs are published atomically as content-addressed blobs.

Evidence binds its own ID/version, exact subject ID/version/digest, run/attempt, commit, scope/environment, result and log authority. It is accepted only after that attempt completed with the same result and log digest.

Audit records bind the same fields, policy version and input digests. Each clause has typed evidence refs. The reducer resolves exact event/record/version/digest and derives overall as `FAIL` if any clause fails, otherwise `BLOCKED` if any blocks, otherwise `PASS`. A verifier cannot self-report a contradictory overall.

Retries are new attempts. Preserve failures. Expired approval, different attempt, scope, environment, object version, digest or commit cannot justify a transition.
