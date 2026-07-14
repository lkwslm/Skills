# Signed artifact protocol

`.delivery/HEAD.json` atomically selects one committed generation. Each generation contains one Ed25519-signed `delivery_transaction`, a manifest, a byte-identical reducer state view, and optional content-addressed blobs. Events use contiguous sequence numbers and `previous_event_hash`; `event_hash` covers the signature.

Every command receives an external trust-root history and caller-held `sequence:event_hash`. The trust root binds `ledger_id` and root-key validity intervals; the expected head detects complete tail rollback that a repository-local hash chain alone cannot detect.

Use identity `artifact_id + version + typed digest`. A digest is exactly `{algorithm: sha256, canonicalization: raw-v1|utf8-nfc-lf-v1|delivery-json-v1, value: 64 lowercase hex}`. Authority is exactly one of pinned Git URI+full commit+path, provider profile digest+native ID+pinned Git authority, or a committed delivery blob. Reject symlinks, submodules, traversal, missing checkout maps and unpinned content.

`artifact_registered` creates a stable ID; `artifact_superseded` names the explicit current version. Never infer current from array order. Superseding an upstream artifact deterministically marks its transitive dependents stale.

Only `deliveryctl` mutates the ledger. `commit` locks, replays, verifies CAS, stages and fsyncs a complete generation, installs it, then replaces HEAD. A complete prepared transaction or generation beyond HEAD requires `recover`; a pre-prepared `.building` residue requires the separately audited, locked `discard-building` command. No implicit cleanup occurs.
