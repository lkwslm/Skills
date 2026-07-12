#!/usr/bin/env python3
"""Unit and dry-run tests for delivery governance scripts."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ASSETS = SCRIPTS.parent / "assets"
sys.path.insert(0, str(SCRIPTS))
from _delivery_common import validate_schema  # noqa: E402


def run(name: str, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)], text=True, capture_output=True, check=False)


class DeliveryScriptsTest(unittest.TestCase):
    def test_all_scripts_support_help(self) -> None:
        for name in ["validate_delivery_artifacts.py", "check_delivery_traceability.py", "check_delivery_staleness.py", "check_delivery_permissions.py", "verify_delivery_evidence.py", "validate_spec_structure.py", "check_contract.py", "check_authorized_diff.py"]:
            with self.subTest(name=name):
                self.assertEqual(run(name, "--help").returncode, 0)

    def test_all_schemas_load(self) -> None:
        for path in ASSETS.glob("*.schema.json"):
            with self.subTest(path=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsInstance(schema, dict)
                self.assertTrue(validate_schema({}, schema), "schema must reject an empty object")

    def test_greenfield_dry_run_reaches_verified(self) -> None:
        root = FIXTURES / "valid" / "greenfield"
        result = run("validate_delivery_artifacts.py", "--root", root, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(run("check_delivery_traceability.py", root / ".delivery/traceability.json", "--json").returncode, 0)
        self.assertEqual(run("verify_delivery_evidence.py", root / ".delivery/evidence/EVID-1.json", "--json").returncode, 0)
        state = json.loads((root / ".delivery/state.json").read_text(encoding="utf-8"))
        self.assertEqual(next(x["state"] for x in state["objects"] if x["object_id"] == "DEL-1"), "verified")
        self.assertEqual(next(x["state"] for x in state["objects"] if x["object_id"] == "CONTRACT-1"), "frozen")
        packages = [json.loads(path.read_text(encoding="utf-8")) for path in (root / ".delivery/context-packages").glob("*.json")]
        self.assertEqual({item["level"] for item in packages}, {"L0", "L1", "L2"})
        self.assertTrue(all(item["content_hash"] for item in packages))
        self.assertEqual(sum(item["level"] == "L1" for item in packages), 2)
        registry = json.loads((root / ".delivery/artifact-registry.json").read_text(encoding="utf-8"))
        contract = next(item for item in registry["artifacts"] if item["artifact_id"] == "CONTRACT-1")
        self.assertEqual(set(contract["consumers"]), {"domain-a", "domain-b"})
        transitions = state["transitions"]
        frozen_at = datetime.fromisoformat(next(item["at"] for item in transitions if item["object_id"] == "CONTRACT-1" and item["new_state"] == "frozen").replace("Z", "+00:00"))
        implementing_at = datetime.fromisoformat(next(item["at"] for item in transitions if item["object_id"] == "TASK-1" and item["new_state"] == "implementing").replace("Z", "+00:00"))
        self.assertLess(frozen_at, implementing_at)
        self.assertEqual([item["old_state"] for item in transitions if item["object_id"] == "DEL-1"][0], "captured")

    def test_brownfield_dry_run_stops_at_release_ready(self) -> None:
        root = FIXTURES / "valid" / "brownfield"
        result = run("validate_delivery_artifacts.py", "--root", root, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(run("check_delivery_traceability.py", root / ".delivery/traceability.json", "--json").returncode, 0)
        self.assertEqual(run("verify_delivery_evidence.py", root / ".delivery/evidence/EVID-B1.json", "--json").returncode, 0)
        state = json.loads((root / ".delivery/state.json").read_text(encoding="utf-8"))
        states = {item["state"] for item in state["objects"]}
        self.assertIn("release_ready", states)
        self.assertNotIn("released", states)
        trace = json.loads((root / ".delivery/traceability.json").read_text(encoding="utf-8"))
        types = {item["type"] for item in trace["nodes"]}
        self.assertTrue({"current-behavior", "target-behavior", "unchanged-behavior", "migration-plan", "observation-plan", "stop-condition"}.issubset(types))

    def test_traceability_positive_and_negative(self) -> None:
        valid = FIXTURES / "valid/greenfield/.delivery/traceability.json"
        invalid = FIXTURES / "invalid/traceability-missing-audit.json"
        self.assertEqual(run("check_delivery_traceability.py", valid, "--json").returncode, 0)
        self.assertEqual(run("check_delivery_traceability.py", invalid, "--json").returncode, 1)

    def test_traceability_cannot_disable_required_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            traceability = Path(temp) / "traceability.json"
            traceability.write_text(json.dumps({"nodes": [], "edges": [], "required_paths": []}), encoding="utf-8")
            result = run("check_delivery_traceability.py", traceability, "--suite", "greenfield", "--json")
            self.assertEqual(result.returncode, 2)

    def test_traceability_exemption_must_resolve_to_risk_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "valid/greenfield", root)
            traceability_path = root / ".delivery/traceability.json"
            traceability = json.loads(traceability_path.read_text(encoding="utf-8"))
            traceability["required_paths"] = [item for item in traceability["required_paths"] if item["start"] != "REQ-1"]
            next(item for item in traceability["nodes"] if item["id"] == "REQ-1")["exemption_approval"] = "APP-FABRICATED"
            traceability_path.write_text(json.dumps(traceability), encoding="utf-8")
            self.assertEqual(run("check_delivery_traceability.py", traceability_path, "--json").returncode, 1)

    def test_stale_hash_propagates_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            registry = Path(temp) / "artifact-registry.json"
            traceability = Path(temp) / "traceability.json"
            shutil.copy2(FIXTURES / "valid/greenfield/.delivery/artifact-registry.json", registry)
            shutil.copy2(FIXTURES / "valid/greenfield/.delivery/traceability.json", traceability)
            result = run("check_delivery_staleness.py", registry, "--traceability", traceability, "--changed", "SRC-1@1=changedhash", "--write", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            stale = set(json.loads(result.stdout)["stale"])
            self.assertTrue({"REQ-1", "CONTRACT-1", "SPEC-1", "TASK-1", "EVID-1", "AUDIT-1"}.issubset(stale))
            updated = json.loads(registry.read_text(encoding="utf-8"))
            statuses = {item["artifact_id"]: item["status"] for item in updated["artifacts"]}
            self.assertTrue(all(statuses[item] == "stale" for item in stale))

    def test_missing_commit_is_schema_error(self) -> None:
        result = run("verify_delivery_evidence.py", FIXTURES / "invalid/evidence-missing-commit.json", "--json")
        self.assertEqual(result.returncode, 2)

    def test_permissions_fail_closed(self) -> None:
        for name in ["permission-implementer-spec.json", "permission-unapproved-task.json", "permission-green-child-parent.json", "permission-traversal.json"]:
            with self.subTest(name=name):
                self.assertEqual(run("check_delivery_permissions.py", FIXTURES / "invalid" / name, "--json").returncode, 1)
        brownfield = FIXTURES / "valid/brownfield/.delivery"
        governance = ("--approvals", brownfield / "approvals.json", "--registry", brownfield / "artifact-registry.json")
        self.assertEqual(run("check_delivery_permissions.py", FIXTURES / "invalid/permission-release-no-auth.json", *governance, "--json").returncode, 1)
        self.assertEqual(run("check_delivery_permissions.py", FIXTURES / "valid/permission-release-authorized.json", *governance, "--json").returncode, 0)

    def test_release_authorization_must_resolve_to_governed_approval(self) -> None:
        brownfield = FIXTURES / "valid/brownfield/.delivery"
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / "permission.json"
            data = json.loads((FIXTURES / "valid/permission-release-authorized.json").read_text(encoding="utf-8"))
            data["authorization"]["approval_id"] = "APP-FABRICATED"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            result = run(
                "check_delivery_permissions.py",
                manifest,
                "--approvals",
                brownfield / "approvals.json",
                "--registry",
                brownfield / "artifact-registry.json",
                "--json",
            )
            self.assertEqual(result.returncode, 1)

    def test_illegal_state_transition_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "valid/greenfield", root)
            shutil.copy2(FIXTURES / "invalid/illegal-state.json", root / ".delivery/state.json")
            self.assertEqual(run("validate_delivery_artifacts.py", "--root", root, "--json").returncode, 1)

    def test_failed_gate_cannot_advance_normal_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "valid/greenfield", root)
            state_path = root / ".delivery/state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["transitions"][0]["gate_result"] = "FAIL"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            self.assertEqual(run("validate_delivery_artifacts.py", "--root", root, "--json").returncode, 1)

    def test_required_delivery_directories_cannot_be_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "valid/greenfield", root)
            shutil.rmtree(root / ".delivery/audits")
            result = run("validate_delivery_artifacts.py", "--root", root, "--json")
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing required directory", result.stdout)

    def test_state_history_must_be_contiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "valid/greenfield", root)
            state_path = root / ".delivery/state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["transitions"] = [item for item in state["transitions"] if not (item["object_id"] == "DEL-1" and item["new_state"] == "planned")]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            self.assertEqual(run("validate_delivery_artifacts.py", "--root", root, "--json").returncode, 1)

    def test_registry_derivation_hash_must_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "valid/greenfield", root)
            registry_path = root / ".delivery/artifact-registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            spec = next(item for item in registry["artifacts"] if item["artifact_id"] == "SPEC-1")
            spec["derived_from"][0]["content_hash"] = "badbadbad"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            self.assertEqual(run("validate_delivery_artifacts.py", "--root", root, "--json").returncode, 1)

    def test_traceability_identity_must_resolve_to_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "valid/greenfield", root)
            traceability_path = root / ".delivery/traceability.json"
            traceability = json.loads(traceability_path.read_text(encoding="utf-8"))
            traceability["nodes"][0]["version"] = "unknown"
            traceability_path.write_text(json.dumps(traceability), encoding="utf-8")
            self.assertEqual(run("validate_delivery_artifacts.py", "--root", root, "--json").returncode, 1)

    def test_context_package_source_must_resolve_to_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "valid/greenfield", root)
            package_path = root / ".delivery/context-packages/L2-1.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["sources"][0]["content_hash"] = "deadbeef"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            self.assertEqual(run("validate_delivery_artifacts.py", "--root", root, "--json").returncode, 1)

    def test_spec_tool_profile_reference_must_resolve_to_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "valid/greenfield", root)
            delivery_path = root / ".delivery/delivery.json"
            delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
            delivery["spec_tool_profile"]["content_hash"] = "deadbeef"
            delivery_path.write_text(json.dumps(delivery), encoding="utf-8")
            self.assertEqual(run("validate_delivery_artifacts.py", "--root", root, "--json").returncode, 1)

    def test_traceability_rejects_shortcuts(self) -> None:
        result = run("check_delivery_traceability.py", FIXTURES / "invalid/traceability-shortcut.json", "--json")
        self.assertEqual(result.returncode, 1)

    def test_evidence_verifies_raw_log_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "valid/greenfield", root)
            evidence_path = root / ".delivery/evidence/EVID-1.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["raw_log_hash"] = "0" * 64
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            self.assertEqual(run("verify_delivery_evidence.py", evidence_path, "--json").returncode, 1)

    def test_evidence_uses_real_time_order_and_confined_log_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "valid/greenfield", root)
            evidence_path = root / ".delivery/evidence/EVID-1.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["started_at"] = "2026-01-01T03:00:00Z"
            evidence["ended_at"] = "2026-01-01T10:00:00+08:00"
            evidence["raw_log_path"] = "../outside.log"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            result = run("verify_delivery_evidence.py", evidence_path, "--json")
            self.assertEqual(result.returncode, 1)
            self.assertIn("ended_at precedes started_at", result.stdout)
            self.assertIn("contains traversal", result.stdout)

    def test_completion_evidence_rejects_unverified_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            shutil.copytree(FIXTURES / "valid/greenfield", root)
            evidence_path = root / ".delivery/evidence/EVID-1.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["unverified_items"] = ["critical NFR"]
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            self.assertEqual(run("verify_delivery_evidence.py", evidence_path, "--json").returncode, 1)

    def test_spec_structure_and_contract_gates(self) -> None:
        self.assertEqual(run("validate_spec_structure.py", FIXTURES / "valid/spec-structure.json", "--json").returncode, 0)
        self.assertEqual(run("validate_spec_structure.py", FIXTURES / "invalid/spec-cycle.json", "--json").returncode, 1)
        delivery = FIXTURES / "valid/greenfield/.delivery"
        self.assertEqual(run("check_contract.py", FIXTURES / "valid/contract.json", "--approvals", delivery / "approvals.json", "--registry", delivery / "artifact-registry.json", "--json").returncode, 0)

    def test_contract_approval_must_match_registered_content_hash(self) -> None:
        delivery = FIXTURES / "valid/greenfield/.delivery"
        with tempfile.TemporaryDirectory() as temp:
            approvals_path = Path(temp) / "approvals.json"
            approvals = json.loads((delivery / "approvals.json").read_text(encoding="utf-8"))
            approval = next(item for item in approvals["approvals"] if item["approval_id"] == "APP-C1")
            approval["content_hash"] = "deadbeef"
            approvals_path.write_text(json.dumps(approvals), encoding="utf-8")
            result = run(
                "check_contract.py",
                FIXTURES / "valid/contract.json",
                "--approvals",
                approvals_path,
                "--registry",
                delivery / "artifact-registry.json",
                "--json",
            )
            self.assertEqual(result.returncode, 1)

    def test_real_git_diff_is_checked_against_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "src").mkdir()
            (repo / "src/base.txt").write_text("base", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "base"], check=True, capture_output=True)
            (repo / "src/base.txt").write_text("allowed", encoding="utf-8")
            allowed = run("check_authorized_diff.py", "--repo", repo, "--base", "HEAD", "--allowed-path", "src", "--json")
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            (repo / "spec").mkdir()
            (repo / "spec/secret.md").write_text("unauthorized", encoding="utf-8")
            blocked = run("check_authorized_diff.py", "--repo", repo, "--base", "HEAD", "--allowed-path", "src", "--json")
            self.assertEqual(blocked.returncode, 1)


if __name__ == "__main__":
    unittest.main()
