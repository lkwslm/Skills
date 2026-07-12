# Artifact protocol

Use `.delivery/` as the governance sidecar: `delivery.json`, `artifact-registry.json`, `state.json`, `traceability.json`, `approvals.json`, `context-packages/`, `evidence/`, `audits/`, and `runs/`. Do not copy external Spec-tool bodies.

Register each artifact with a stable ID, type, authority URI/kind, owner role, unique writer, version, content hash, derivations, status, creation time, and validation time. Record derivations as upstream ID/version/hash triples. Create a new version for content changes; never overwrite approved identity. For external artifacts without a content hash, record a stable provider version and retrieval time.

Keep exactly one registry record and one authoritative writer for each artifact ID/version. Resolve every derivation to an existing upstream ID/version with the recorded hash. Treat confidence as discovery metadata, never as approval. Use canonical hashes only with a recorded canonicalization version.

Use one identity tuple, `artifact_id + version + content_hash`, across the registry, traceability, approvals, context packages, evidence, audits, and state-transition inputs. Reject a cross-file reference when its ID/version is absent, its type differs, or its hash does not match the registry. Never accept an approval, evidence record, or traceability node as an isolated self-assertion.

Use uppercase `PASS`, `FAIL`, and `BLOCKED` only for gate results; use lowercase names such as `blocked`, `failed`, and `stale` only for lifecycle states; use uppercase `APPROVED`, `REJECTED`, and `RISK_ACCEPTED` only for approval decisions.
