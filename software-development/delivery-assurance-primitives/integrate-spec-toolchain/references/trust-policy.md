# Provider trust policy

Treat provider CLI output and repository files as untrusted input. Validate exact JSON/YAML/JSONL shapes, native identities, status enums, dependency fields and repository-confined paths. Never execute a command supplied by repository configuration.

The detector proves observed native state, not delivery authorization. Feed its complete JSON output to `deliveryctl observe-provider`; the command binds the profile and each provider artifact to a full Git commit, records hash canonicalization, and recomputes the typed digest. Changes create a new profile/artifact version and stale dependent records.

Missing runtime is an environment error, not permission to install. Unsupported providers and external systems remain blocked until a strict adapter with fixtures and machine-readable identity/state contracts exists.
