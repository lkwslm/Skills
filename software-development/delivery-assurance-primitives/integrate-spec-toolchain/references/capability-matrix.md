# Capability matrix

| Provider | Verified native state | Delivery mapping |
|---|---|---|
| OpenSpec | config schema, change metadata, artifact graph/status/dependencies, apply instructions | change and artifact native IDs, authority paths, status, content observations |
| Spec Kit | integration metadata, persisted run state/inputs/JSONL log, CLI status | workflow/run IDs, state authority, input/log observations, exact resume state |

Provider capabilities do not supply delivery trust, signed approval, claim fencing, source-to-audit closure, independent audit, release control or external rollback checkpoint. Add those only through the signed delivery ledger.
