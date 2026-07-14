# Strict detection rules

Recognize OpenSpec only from `openspec/config.yaml` plus actual specs/changes and per-change `.openspec.yaml`. Recognize Spec Kit only from `.specify/integration.json` plus persisted workflow runs. A directory name, obsolete `config.json`, global executable or remembered convention is not adoption evidence.

OpenSpec uses only `openspec --version`, `openspec status --change <id> --json`, and `openspec instructions apply --change <id> --json`. Spec Kit uses only `specify version` and `specify workflow status <run-id> --json`. Run with `shell=False`, fixed timeout and schema/identity checks.

Provider CLIs are accepted only from absolute, hash-pinned paths outside the repository and current directory. Native CLIs must have the platform executable magic; Node/Python providers use the fixed argv `[pinned interpreter, pinned entrypoint, ...]`. A separately hash-pinned runtime manifest must exactly cover every regular file in the hermetic runtime root and is reverified before each invocation; scripts, links, reparses, undeclared dependencies, and PATH launchers are rejected. OpenSpec completed wildcard outputs are expanded to individual confined files; pending or blocked wildcard declarations are observations only and never become authoritative artifacts. Spec Kit run directory names must match `[A-Za-z0-9][A-Za-z0-9._-]{0,127}` so no shell metacharacter or option prefix can reach the CLI.

Return blocked/nonzero for zero or multiple providers, missing CLI, invalid JSON/YAML/JSONL, missing native metadata, unsafe paths, empty mapping, status mismatch, duplicate IDs or unsupported provider. There is no alternate format or inferred profile.
