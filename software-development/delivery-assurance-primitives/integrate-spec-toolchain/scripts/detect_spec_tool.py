#!/usr/bin/env python3
"""Detect repository-level Spec tools and verify declared read-only runtimes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


MARKERS = {
    "spec-kit": [".specify"],
    "openspec": ["openspec", "openspec.yaml", "openspec.yml"],
    "kiro": [".kiro/specs"],
}
MISSING = ["source-traceability", "role-isolation", "evidence-governance"]
ADOPTION_OPTIONS = ["spec-kit", "openspec", "kiro"]
ALLOWED_VERSION_ARGS = {("--version",), ("version",), ("-V",)}


def finalize(profile: dict) -> dict:
    profile["profile_hash"] = hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return profile


def base_profile(provider: str, mode: str) -> dict:
    return {"profile_id": f"PROFILE-{provider}", "profile_hash": "", "provider": provider, "mode": mode, "version": None, "version_source": None, "artifact_root": None, "authorities": {}, "id_mapping": {}, "capabilities": [], "missing_controls": MISSING, "command_entrypoints": {}, "configuration": None, "extensions": [], "runtime": None, "adoption_options": [], "next_actions": [], "trust": {"level": "review-required", "reasons": []}, "candidates": []}


def safe_relative_root(repo: Path, value: str) -> bool:
    candidate = (repo / value).resolve()
    return os.path.commonpath([str(repo), str(candidate)]) == str(repo)


def emit(profile: dict, errors: list[str], as_json: bool) -> None:
    result = {"ok": not errors, "errors": errors, "profile": profile}
    if as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        for error in errors:
            print("ERROR: " + error, file=sys.stderr)
    elif errors:
        for error in errors:
            print("ERROR: " + error, file=sys.stderr)
    else:
        print(f"PASS: provider={profile['provider']} mode={profile['mode']}")


def runtime_record(runtime: dict, resolved_path: str | None = None, observed_version: str | None = None) -> dict:
    return {
        "executable": runtime.get("executable"),
        "resolved_path": resolved_path,
        "version_args": runtime.get("version_args"),
        "expected_version": runtime.get("expected_version"),
        "observed_version": observed_version,
        "declared_installation_source": runtime.get("declared_installation_source"),
    }


def format_next_actions(names: list[str]) -> list[dict]:
    authorization = {
        "install-or-expose-declared-cli": ["installation"],
        "request-adoption": ["installation", "initialization"],
    }
    return [{"action": name, "authorization_required": authorization.get(name, [])} for name in names]


def block_runtime(profile: dict, runtime: dict, reason: str, error: str, actions: list[str], exit_code: int, as_json: bool) -> int:
    profile.update({
        "mode": "blocked",
        "runtime": runtime,
        "next_actions": format_next_actions(actions),
        "trust": {"level": "blocked", "reasons": [reason]},
    })
    finalize(profile)
    emit(profile, [error], as_json)
    return exit_code


def verify_runtime(profile: dict, configured_runtime: object, expected_version: str, repo: Path, as_json: bool) -> int | None:
    if not isinstance(configured_runtime, dict):
        return block_runtime(profile, runtime_record({}), "executable capabilities lack runtime configuration", "provider runtime configuration is missing", ["repair-provider-configuration", "rerun-detection"], 1, as_json)
    executable = configured_runtime.get("executable")
    version_args = configured_runtime.get("version_args")
    installation_source = configured_runtime.get("declared_installation_source")
    runtime = dict(configured_runtime)
    runtime["expected_version"] = expected_version
    if not isinstance(executable, str) or not executable or not isinstance(version_args, list) or not all(isinstance(item, str) for item in version_args) or not isinstance(installation_source, str) or not installation_source:
        return block_runtime(profile, runtime_record(runtime), "runtime configuration lacks executable, version_args, or declared_installation_source", "provider runtime configuration is incomplete", ["repair-provider-configuration", "rerun-detection"], 1, as_json)
    if tuple(version_args) not in ALLOWED_VERSION_ARGS:
        return block_runtime(profile, runtime_record(runtime), "version probe is not in the read-only allowlist", "provider version probe must be --version, version, or -V", ["repair-provider-configuration", "rerun-detection"], 1, as_json)
    for command in profile["command_entrypoints"].values():
        try:
            tokens = shlex.split(command, posix=os.name != "nt")
        except ValueError:
            tokens = []
        if not tokens or tokens[0] != executable:
            return block_runtime(profile, runtime_record(runtime), "command entrypoint does not use the declared provider executable", "provider command entrypoint and runtime executable differ", ["repair-provider-configuration", "rerun-detection"], 1, as_json)
    resolved = shutil.which(executable)
    if resolved is None:
        return block_runtime(profile, runtime_record(runtime), "declared provider executable is unavailable", f"declared provider executable is unavailable: {executable}", ["install-or-expose-declared-cli", "rerun-detection"], 3, as_json)
    record = runtime_record(runtime, str(Path(resolved).resolve()))
    try:
        result = subprocess.run([resolved, *version_args], cwd=repo, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False, timeout=5, shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return block_runtime(profile, record, "read-only version probe could not complete", f"provider version probe failed: {exc}", ["repair-provider-runtime", "rerun-detection"], 3, as_json)
    observed = next((line.strip() for line in (result.stdout + "\n" + result.stderr).splitlines() if line.strip()), "")[:512]
    record["observed_version"] = observed or None
    if result.returncode != 0 or not observed:
        return block_runtime(profile, record, "read-only version probe returned no usable version", "provider version probe returned no usable version", ["repair-provider-runtime", "rerun-detection"], 3, as_json)
    version_pattern = rf"(?<![A-Za-z0-9]){re.escape(expected_version)}(?![A-Za-z0-9])"
    if re.search(version_pattern, observed) is None:
        return block_runtime(profile, record, "installed provider version differs from repository configuration", f"provider version mismatch: expected {expected_version}, observed {observed}", ["resolve-version-mismatch", "rerun-detection"], 1, as_json)
    profile["runtime"] = record
    profile["version_source"] = " ".join([record["resolved_path"], *version_args])
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not repo.is_dir():
        emit({}, [f"repository is not a directory: {repo}"], args.json)
        return 2
    found = [provider for provider, markers in MARKERS.items() if any((repo / marker).exists() for marker in markers)]
    if len(found) > 1:
        profile = base_profile("conflict", "blocked")
        profile.update({"candidates": found, "trust": {"level": "blocked", "reasons": ["multiple repository-level Spec tools claim writable artifacts"]}})
        finalize(profile)
        emit(profile, ["multiple Spec tools detected; choose one authoritative writer per artifact type"], args.json)
        return 1
    if not found:
        profile = base_profile("fallback", "fallback")
        profile.update({"artifact_root": ".delivery", "adoption_options": ADOPTION_OPTIONS, "next_actions": format_next_actions(["continue-fallback", "request-adoption"]), "trust": {"level": "trusted", "reasons": ["no repository-level Spec tool is adopted; no executable provider will be called"]}})
        finalize(profile)
        emit(profile, [], args.json)
        return 0
    provider = found[0]
    root = next(marker for marker in MARKERS[provider] if (repo / marker).exists())
    config_candidates = [repo / root / "config.json", repo / ".kiro" / "config.json"]
    config_path = next((path for path in config_candidates if path.is_file()), None)
    profile = base_profile(provider, "blocked")
    profile.update({"artifact_root": root, "candidates": found})
    if config_path is None:
        profile["trust"] = {"level": "blocked", "reasons": ["repository marker exists but versioned configuration is missing"]}
        finalize(profile)
        emit(profile, ["cannot confirm provider version and authoritative artifact roots"], args.json)
        return 1
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        profile["trust"] = {"level": "blocked", "reasons": [f"configuration cannot be parsed: {exc}"]}
        finalize(profile)
        emit(profile, ["cannot parse provider configuration"], args.json)
        return 2
    version = config.get("version")
    artifact_roots = config.get("artifact_roots")
    capabilities = config.get("capabilities")
    if not isinstance(version, str) or not version or not isinstance(artifact_roots, dict) or not isinstance(capabilities, list) or not all(isinstance(item, str) and item for item in capabilities):
        profile["trust"] = {"level": "blocked", "reasons": ["configuration lacks version, artifact_roots, or capabilities"]}
        finalize(profile)
        emit(profile, ["provider configuration is incomplete"], args.json)
        return 1
    invalid_roots = [value for value in artifact_roots.values() if not isinstance(value, str) or not safe_relative_root(repo, value)]
    if invalid_roots:
        profile["trust"] = {"level": "blocked", "reasons": ["artifact root escapes the repository"]}
        finalize(profile)
        emit(profile, ["provider artifact root is outside the repository"], args.json)
        return 1
    missing_roots = [value for value in artifact_roots.values() if not (repo / value).exists()]
    commands = config.get("commands", {})
    extensions = config.get("extensions", [])
    valid_commands = isinstance(commands, dict) and all(isinstance(key, str) and key and isinstance(value, str) and value.strip() for key, value in commands.items())
    valid_extensions = isinstance(extensions, list) and all(isinstance(item, str) and item for item in extensions)
    if missing_roots or not valid_commands or not valid_extensions:
        profile["trust"] = {"level": "blocked", "reasons": ["configured artifact roots or command map cannot be confirmed"]}
        finalize(profile)
        emit(profile, ["configured provider artifacts or commands are missing"], args.json)
        return 1
    artifact_capabilities = {"spec", "design", "tasks"}
    command_capabilities = {"implement", "lifecycle"}
    unsupported = [item for item in capabilities if item in artifact_capabilities and item not in artifact_roots]
    unsupported += [item for item in capabilities if item in command_capabilities and item not in commands]
    if unsupported:
        profile["trust"] = {"level": "blocked", "reasons": ["declared capabilities lack repository evidence"]}
        finalize(profile)
        emit(profile, ["unconfirmed capabilities: " + ", ".join(sorted(unsupported))], args.json)
        return 1
    profile.update({
        "version": version,
        "version_source": str(config_path.relative_to(repo)).replace("\\", "/"),
        "authorities": {kind: {"uri": uri, "writer": provider} for kind, uri in artifact_roots.items()},
        "capabilities": capabilities,
        "command_entrypoints": commands,
        "configuration": str(config_path.relative_to(repo)).replace("\\", "/"),
        "extensions": extensions,
    })
    if commands:
        runtime_failure = verify_runtime(profile, config.get("runtime"), version, repo, args.json)
        if runtime_failure is not None:
            return runtime_failure
    profile.update({
        "mode": "native",
        "version_source": profile["version_source"] or str(config_path.relative_to(repo)).replace("\\", "/"),
        "next_actions": [],
        "trust": {"level": "review-required" if commands or extensions else "trusted", "reasons": ["configured executable entrypoints or extensions require review"] if commands or extensions else ["version and authorities read from repository configuration"]},
    })
    finalize(profile)
    emit(profile, [], args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
