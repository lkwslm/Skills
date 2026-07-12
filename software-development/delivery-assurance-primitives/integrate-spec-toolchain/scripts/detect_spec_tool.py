#!/usr/bin/env python3
"""Detect repository-level Spec tools without executing or installing them."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


MARKERS = {
    "spec-kit": [".specify"],
    "openspec": ["openspec", "openspec.yaml", "openspec.yml"],
    "kiro": [".kiro/specs"],
}
MISSING = ["source-traceability", "role-isolation", "evidence-governance"]


def finalize(profile: dict) -> dict:
    profile["profile_hash"] = hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return profile


def base_profile(provider: str, mode: str) -> dict:
    return {"profile_id": f"PROFILE-{provider}", "profile_hash": "", "provider": provider, "mode": mode, "version": None, "version_source": None, "artifact_root": None, "authorities": {}, "id_mapping": {}, "capabilities": [], "missing_controls": MISSING, "command_entrypoints": {}, "configuration": None, "extensions": [], "trust": {"level": "review-required", "reasons": []}, "candidates": []}


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
        profile.update({"artifact_root": ".delivery", "trust": {"level": "trusted", "reasons": ["no executable provider selected"]}})
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
    if not isinstance(version, str) or not version or not isinstance(artifact_roots, dict) or not isinstance(capabilities, list):
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
    if missing_roots or not isinstance(commands, dict):
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
        "mode": "native",
        "version": version,
        "version_source": str(config_path.relative_to(repo)).replace("\\", "/"),
        "authorities": {kind: {"uri": uri, "writer": provider} for kind, uri in artifact_roots.items()},
        "capabilities": capabilities,
        "command_entrypoints": commands,
        "configuration": str(config_path.relative_to(repo)).replace("\\", "/"),
        "extensions": config.get("extensions", []),
        "trust": {"level": "review-required" if commands or config.get("extensions") else "trusted", "reasons": ["configured executable entrypoints or extensions require review"] if commands or config.get("extensions") else ["version and authorities read from repository configuration"]},
    })
    finalize(profile)
    emit(profile, [], args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
