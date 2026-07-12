#!/usr/bin/env python3
"""Compare the real Git diff with explicitly authorized repository paths."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess

from _delivery_common import emit
from check_delivery_permissions import normalize_relative, within


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--base", required=True, help="Approved base commit or tree")
    parser.add_argument("--allowed-path", action="append", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if shutil.which("git") is None:
        emit(False, ["git executable is unavailable"], {"summary": "environment unavailable"}, args.json)
        return 3
    if not repo.is_dir() or any(normalize_relative(scope.rstrip("/")) is None for scope in args.allowed_path):
        emit(False, ["invalid repository or allowed path"], {"summary": "input error"}, args.json)
        return 2
    if git(repo, "rev-parse", "--verify", f"{args.base}^{{tree}}").returncode != 0:
        emit(False, [f"invalid base revision: {args.base}"], {"summary": "input error"}, args.json)
        return 2
    diff = git(repo, "diff", "--name-only", "-z", args.base, "--")
    untracked = git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    if diff.returncode != 0 or untracked.returncode != 0:
        emit(False, ["git diff inspection failed"], {"summary": "environment unavailable"}, args.json)
        return 3
    paths = sorted({item.decode("utf-8") for item in (diff.stdout + untracked.stdout).split(b"\0") if item})
    unauthorized = [path for path in paths if not within(path, args.allowed_path)]
    emit(not unauthorized, [f"path outside approved scope: {path}" for path in unauthorized], {"summary": f"checked {len(paths)} changed paths", "changed_paths": paths, "unauthorized_paths": unauthorized}, args.json)
    return 0 if not unauthorized else 1


if __name__ == "__main__":
    raise SystemExit(main())
