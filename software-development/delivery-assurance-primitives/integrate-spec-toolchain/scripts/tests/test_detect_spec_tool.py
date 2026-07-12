#!/usr/bin/env python3
"""Tests for read-only Spec-tool detection."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "detect_spec_tool.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROFILE_SCHEMA = json.loads((SCRIPT.parents[1] / "assets/spec-tool-profile.schema.json").read_text(encoding="utf-8"))
GOVERN_SCRIPTS = SCRIPT.parents[2] / "govern-delivery-artifacts" / "scripts"
sys.path.insert(0, str(GOVERN_SCRIPTS))
from _delivery_common import validate_schema  # noqa: E402


def run(fixture: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(FIXTURES / fixture), "--json"], text=True, capture_output=True, check=False, env=env)


def run_repo(repo: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--json"], text=True, capture_output=True, check=False, env=env)


def fake_openspec(directory: Path, version: str = "1.0") -> dict[str, str]:
    env = os.environ.copy()
    if os.name == "nt":
        executable = directory / "openspec.cmd"
        executable.write_text(f"@echo off\r\necho OpenSpec {version}\r\n", encoding="utf-8")
    else:
        executable = directory / "openspec"
        executable.write_text(f"#!/bin/sh\nprintf 'OpenSpec {version}\\n'\n", encoding="utf-8")
        executable.chmod(0o755)
    env["PATH"] = str(directory) + os.pathsep + env.get("PATH", "")
    return env


class DetectSpecToolTest(unittest.TestCase):
    def test_help(self) -> None:
        self.assertEqual(subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True).returncode, 0)

    def test_native_openspec(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run("native-openspec", fake_openspec(Path(directory)))
        self.assertEqual(result.returncode, 0)
        profile = json.loads(result.stdout)["profile"]
        self.assertEqual((profile["provider"], profile["mode"]), ("openspec", "native"))
        self.assertEqual(profile["version"], "1.0")
        self.assertEqual(profile["authorities"]["tasks"]["uri"], "openspec/tasks")
        self.assertEqual(profile["runtime"]["observed_version"], "OpenSpec 1.0")
        self.assertTrue(profile["runtime"]["resolved_path"])
        self.assertEqual(len(profile["profile_hash"]), 64)
        self.assertEqual(validate_schema(profile, PROFILE_SCHEMA), [])
        self.assertTrue(validate_schema({}, PROFILE_SCHEMA))

    def test_fallback(self) -> None:
        result = run("fallback")
        self.assertEqual(result.returncode, 0)
        profile = json.loads(result.stdout)["profile"]
        self.assertEqual(profile["mode"], "fallback")
        self.assertEqual([item["action"] for item in profile["next_actions"]], ["continue-fallback", "request-adoption"])
        self.assertEqual(profile["next_actions"][1]["authorization_required"], ["installation", "initialization"])
        self.assertIn("openspec", profile["adoption_options"])
        self.assertEqual(validate_schema(profile, PROFILE_SCHEMA), [])

    def test_declared_provider_without_cli_is_blocked(self) -> None:
        env = os.environ.copy()
        env["PATH"] = ""
        result = run("native-openspec", env)
        self.assertEqual(result.returncode, 3)
        profile = json.loads(result.stdout)["profile"]
        self.assertEqual(profile["mode"], "blocked")
        self.assertEqual(profile["runtime"]["executable"], "openspec")
        self.assertIsNone(profile["runtime"]["resolved_path"])
        actions = {item["action"]: item["authorization_required"] for item in profile["next_actions"]}
        self.assertIn("install-or-expose-declared-cli", actions)
        self.assertEqual(actions["install-or-expose-declared-cli"], ["installation"])
        self.assertEqual(validate_schema(profile, PROFILE_SCHEMA), [])

    def test_installed_version_mismatch_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run("native-openspec", fake_openspec(Path(directory), "2.0"))
        self.assertEqual(result.returncode, 1)
        profile = json.loads(result.stdout)["profile"]
        self.assertEqual(profile["mode"], "blocked")
        self.assertEqual(profile["runtime"]["observed_version"], "OpenSpec 2.0")
        self.assertIn("resolve-version-mismatch", [item["action"] for item in profile["next_actions"]])
        self.assertEqual(validate_schema(profile, PROFILE_SCHEMA), [])

    def test_invalid_command_map_is_blocked_before_runtime_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            shutil.copytree(FIXTURES / "native-openspec", repo)
            config_path = repo / "openspec" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["commands"]["implement"] = 7
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = run_repo(repo)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["profile"]["mode"], "blocked")

    def test_command_entrypoint_must_use_declared_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            shutil.copytree(FIXTURES / "native-openspec", repo)
            config_path = repo / "openspec" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["commands"]["implement"] = "another-tool apply"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = run_repo(repo)
        self.assertEqual(result.returncode, 1)
        self.assertIn("runtime executable differ", result.stderr)

    def test_conflicting_task_writers_are_blocked(self) -> None:
        result = run("conflict")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["profile"]["mode"], "blocked")

    def test_incomplete_provider_configuration_is_blocked(self) -> None:
        result = run("incomplete-openspec")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["profile"]["mode"], "blocked")

    def test_missing_repository_is_input_error(self) -> None:
        result = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(FIXTURES / "missing"), "--json"], text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("ERROR:"))


if __name__ == "__main__":
    unittest.main()
