#!/usr/bin/env python3
"""Tests for read-only Spec-tool detection."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "detect_spec_tool.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOVERN_SCRIPTS = SCRIPT.parents[2] / "govern-delivery-artifacts" / "scripts"
sys.path.insert(0, str(GOVERN_SCRIPTS))
from _delivery_common import validate_schema  # noqa: E402


def run(fixture: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(FIXTURES / fixture), "--json"], text=True, capture_output=True, check=False)


class DetectSpecToolTest(unittest.TestCase):
    def test_help(self) -> None:
        self.assertEqual(subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True).returncode, 0)

    def test_native_openspec(self) -> None:
        result = run("native-openspec")
        self.assertEqual(result.returncode, 0)
        profile = json.loads(result.stdout)["profile"]
        self.assertEqual((profile["provider"], profile["mode"]), ("openspec", "native"))
        self.assertEqual(profile["version"], "1.0")
        self.assertEqual(profile["authorities"]["tasks"]["uri"], "openspec/tasks")
        self.assertEqual(len(profile["profile_hash"]), 64)
        schema = json.loads((SCRIPT.parents[1] / "assets/spec-tool-profile.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_schema(profile, schema), [])
        self.assertTrue(validate_schema({}, schema))

    def test_fallback(self) -> None:
        result = run("fallback")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["profile"]["mode"], "fallback")

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
