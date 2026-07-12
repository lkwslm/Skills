# Detection rules

Inspect project-level instructions and markers before any CLI call. Recognize Spec Kit from `.specify/` or configured Spec Kit metadata, OpenSpec from `openspec/` or `openspec.yaml`, and Kiro Specs from `.kiro/specs/` or Kiro project configuration. A global executable alone is not adoption evidence.

Use `native` only when repository artifacts and versioned configuration identify the observed capabilities and authoritative roots for each writable artifact type. A marker without confirmable version/configuration is `blocked`, not inferred capability. Use `bridge` only with an external authority and explicit one-way sync; report `fallback` when nothing is adopted. Enter `adopt` only after explicit user approval.

If multiple providers claim writable spec, design, or tasks, return a conflict instead of choosing. Read actual version/configuration before proposing commands; never rely on remembered paths or syntax.
