# Detection rules

Inspect project-level instructions and markers before any CLI call. Recognize Spec Kit from `.specify/` or configured Spec Kit metadata, OpenSpec from `openspec/` or `openspec.yaml`, and Kiro Specs from `.kiro/specs/` or Kiro project configuration. A global executable alone is not adoption evidence.

Use `native` only when repository artifacts and versioned configuration identify the observed capabilities and authoritative roots for each writable artifact type. When executable capabilities are declared, require runtime configuration containing the executable name, one allowlisted read-only version form (`--version`, `version`, or `-V`), and the declared installation source. Every configured command entrypoint must use that same executable. Resolve the executable from the active environment and require its observed version to match the repository configuration. Do not describe the declared installation source as independently verified evidence.

A marker without confirmable configuration is `blocked`. An adopted provider with a missing CLI, failed version probe, or version mismatch is also `blocked` and must never be reclassified as `fallback`. Exit `3` for an unavailable runtime and `1` for a valid configuration that fails a compatibility gate.

Use `bridge` only with an external authority and explicit one-way sync. Report `fallback` only when no repository-level adoption evidence exists; include `continue-fallback` and `request-adoption` as explicit next actions. Enter `adopt` only after explicit user approval, and hand installation or initialization to a separately authorized executor before rerunning detection.

If multiple providers claim writable spec, design, or tasks, return a conflict instead of choosing. Read actual version/configuration before proposing commands; never rely on remembered paths or syntax. Treat changes to configuration, resolved executable, observed version, or authority roots as profile changes that make dependent mappings stale.
