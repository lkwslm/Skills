#!/usr/bin/env python3
"""Strictly detect and verify an adopted OpenSpec or Spec Kit provider."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from spec_providers import OpenSpecProvider, ProviderError, SpecKitProvider


def emit(ok: bool, profile: dict | None, candidates: list[str], errors: list[ProviderError], as_json: bool) -> None:
    payload = {
        "ok": ok,
        "errors": [{"code": error.code, "message": error.message} for error in errors],
        "profile": profile,
        "candidates": candidates,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    elif ok and profile is not None:
        print(f"PASS: provider={profile['provider']} mode={profile['mode']}")
    for error in errors:
        print(f"ERROR [{error.code}]: {error.message}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--provider-cli", type=Path)
    parser.add_argument("--provider-cli-sha256")
    parser.add_argument("--provider-cli-manifest", type=Path)
    parser.add_argument("--provider-cli-manifest-sha256")
    parser.add_argument("--provider-cli-entrypoint", type=Path)
    parser.add_argument("--provider-cli-entrypoint-sha256")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not repo.is_dir():
        error = ProviderError("REPOSITORY_INVALID", f"repository is not a directory: {repo}", 2)
        emit(False, None, [], [error], args.json)
        return error.exit_code

    candidates: list[str] = []
    if (repo / "openspec" / "config.yaml").is_file():
        candidates.append("openspec")
    if (repo / ".specify" / "integration.json").is_file():
        candidates.append("spec-kit")
    if not candidates:
        error = ProviderError("PROVIDER_NOT_ADOPTED", "no supported provider adoption metadata found")
        emit(False, None, [], [error], args.json)
        return error.exit_code
    if len(candidates) != 1:
        error = ProviderError("PROVIDER_CONFLICT", "multiple supported providers are adopted")
        emit(False, None, candidates, [error], args.json)
        return error.exit_code

    try:
        if args.provider_cli is None or args.provider_cli_sha256 is None or args.provider_cli_manifest is None or args.provider_cli_manifest_sha256 is None:
            raise ProviderError("PROVIDER_CLI_UNPINNED", "adopted provider requires executable and runtime manifest paths with SHA-256 pins", 3)
        adapter = (
            OpenSpecProvider(repo, args.provider_cli, args.provider_cli_sha256, args.provider_cli_manifest, args.provider_cli_manifest_sha256, None, None, args.provider_cli_entrypoint, args.provider_cli_entrypoint_sha256)
            if candidates[0] == "openspec"
            else SpecKitProvider(repo, args.provider_cli, args.provider_cli_sha256, args.provider_cli_manifest, args.provider_cli_manifest_sha256, None, None, args.provider_cli_entrypoint, args.provider_cli_entrypoint_sha256)
        )
        profile = adapter.detect()
    except ProviderError as error:
        emit(False, None, candidates, [error], args.json)
        return error.exit_code
    emit(True, profile, candidates, [], args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
